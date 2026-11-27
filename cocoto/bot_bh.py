"""Boucle de la base des ouvriers (BH).

Combat : Battle → Find Now! → « Battle starts in » → dézoom (tout le terrain tient à l'écran),
côté au hasard → héros d'abord (Battle Machine à l'étape 1, Battle Copter à l'étape 2 ; échange par le
bouton vert si un seul est activé) → cartes de l'étape 1 (auto = toutes les cartes colorées, « 4x »
lu sur la carte) → vitesse 1x → 4x → capacité du héros quand la jauge a assez de segments →
étape 2 (cartes encore colorées) → écran de fin : étoiles (étape 2 : 3 + argentées), récompenses.
Au village : Okay du Star Bonus, charrette d'élixir, récolte (3-5 combats), bâtiments puis murs
payés avec les réserves de la BH, recherche au Laboratoire stellaire."""
from __future__ import annotations

import random
import re
import time
from typing import Callable

from . import layout, notify, ocr, vision
from .bot_th import BotContext, StopWithMessage
from .config import BH_HERO_KEYS
from .features import search
from .features.accounts import AccountSet, switch_to_next
from .features.attack import card_alive
from .features.breaks import BreakScheduler, check_schedule, wait_between_battles
from .features.reconnect import reload_game
from .features.upgrades import BH_LAB_TROOPS, Upgrader, pending
from .features.village import BH_COLLECT_KEYS, VillageError, check_village, collect_resources
from .features.walls import WallState, due as walls_due, upgrade_walls
from .logger import log
from .parsing import is_auto, parse_amount, parse_counts, parse_slots
from .state import Reconnect

CART_KEYS = ("bh_cart_oct", "bh_cart", "bh_cart_full", "bh_cart_empty", "bh_cart_grass")


# ---------------------------------------------------------------- géométrie
def bh_edge_points(stage: int, side: str, n: int, inset: float = 30) -> list[tuple[int, int]]:
    (ax, ay), (bx, by) = layout.BH_ARENAS[stage][side]
    t0, t1 = (0.1, 0.9)
    dx, dy = bx - ax, by - ay
    length = max(1.0, (dx * dx + dy * dy) ** 0.5)
    nx, ny = -dy / length, dx / length
    if (960 - ax) * nx + (540 - ay) * ny < 0:
        nx, ny = -nx, -ny
    pts = []
    for i in range(max(1, n)):
        t = random.uniform(t0 + (t1 - t0) * i / n, t0 + (t1 - t0) * (i + 1) / n)
        x, y = int(ax + dx * t + nx * inset), int(ay + dy * t + ny * inset)
        if 30 < x < 1890 and 80 < y < 860:
            pts.append((x, y))
    return pts or [(960, 500)]


def slot_x(slot: int, hero_present: bool) -> int:
    """Centre de la carte slot (1-10) ; sans carte héros, les cartes sont décalées d'une place."""
    if hero_present:
        return layout.BH_SLOT_POSITIONS[slot]
    return layout.BH_SLOT_POSITIONS.get(slot, 0) - (layout.BH_SLOT_POSITIONS[2] - layout.BH_SLOT_POSITIONS[1])


def read_card_count(screen, cx: int) -> int:
    """« 4x » en haut à droite de la carte : 4 ; 1 sans compteur ; 0 si illisible."""
    y = layout.BH_CARD_Y
    zone, _, _ = vision.crop(screen, (cx - 20, y - 70, cx + 55, y - 35))
    mask = vision.white_text_mask(zone, 200, 70)
    if len(vision.components(mask, 8, 30, 10)) < 2:
        return 1
    m = re.search(r"(\d{1,2})", "".join(ocr.read_text(255 - mask, allowlist="0123456789x")))
    return int(m.group(1)) if m else 0


class BuilderBaseBot:
    def __init__(self, ctx: BotContext):
        self.ctx = ctx
        self.g = ctx.game
        self.cfg = ctx.cfg_bh
        self.state = ctx.game.state
        self.breaks = BreakScheduler(self.cfg)
        self.walls = WallState()
        self.upgrader = Upgrader(self.g, self.cfg, "BH")
        self.accounts = AccountSet(ctx.settings, "accounts_bh")
        self.collect_in = random.randint(3, 5)
        self.cart_in = random.randint(3, 4)

    def run(self, auto: bool = False, until: Callable[[], bool] | None = None) -> None:
        """until : visite depuis le TH (« Then BH ») → rend la main quand until() est vrai."""
        self.state.running_mode = "BH"
        while True:
            try:
                self._session(auto, until)
                return
            except Reconnect:
                self.state.set_status("reconnecting")
                if not reload_game(self.g):
                    raise StopWithMessage("Cocoto arrêté", "le jeu ne s'est pas rechargé")
                self.state.reconnecting = False
                auto = True
            except search.SearchFailed as exc:
                notify.send_alert(f"BH : bot arrêté : {exc}", "bh_search")
                raise StopWithMessage("Cocoto arrêté", str(exc))
            except VillageError as exc:
                raise StopWithMessage(exc.title, exc.message)

    def _session(self, auto: bool, until) -> None:
        self.state.set_status("farming")
        check_village(self.g, "BH", travel_ok=True, timeout=60 if auto else 12)
        while True:
            self.state.check()
            if until and until():
                return
            if until is None:
                if not self.breaks.check(self.g, notify.send_info):
                    return
                if not check_schedule(self.g, self.cfg, notify.send_info):
                    return
            if not self.g.wait_village(20):
                raise search.SearchFailed("le bouton Battle n'est pas visible")
            self.battle()
            self.after_battle(until is not None)
            wait_between_battles(self.g, self.cfg)

    # ================================================================ combat
    def battle(self) -> None:
        g = self.g
        search.click_battle(g)
        if not search.click_launch_button(g, "bh_find_now", "Find Now!"):
            raise search.SearchFailed("le bouton « Find Now! » n'est pas apparu")
        if not g.wait("bh_battle_starts", 60, scales=(0.9, 1.0, 1.1)):
            raise search.SearchFailed("« Battle starts in » jamais affiché")
        g.zoom_out()
        side = random.choice(("left", "right"))
        stars_stage = 1
        self.deploy_stage(1, side)
        result = self.wait_stage_end()
        if result == "stage2":
            stars_stage = 2
            g.zoom_out()
            self.deploy_stage(2, side)
            result = self.wait_stage_end()
        if result != "end":
            raise search.SearchFailed("fin du combat BH introuvable")
        g.sleep(1.0)
        self.end_screen(stars_stage)

    def hero_present(self, screen) -> bool:
        return max(self.g.score("bh_hero_machine", screen, layout.BH_HERO_CARD_BOX),
                   self.g.score("bh_hero_copter", screen, layout.BH_HERO_CARD_BOX)) > 0.7

    def hero_on_card(self, screen) -> str | None:
        m = self.g.score("bh_hero_machine", screen, layout.BH_HERO_CARD_BOX)
        c = self.g.score("bh_hero_copter", screen, layout.BH_HERO_CARD_BOX)
        if max(m, c) < 0.7:
            return None
        return "machine" if m >= c else "copter"

    def deploy_hero(self, stage: int, side: str, screen) -> str | None:
        hero = self.hero_on_card(screen)
        if not hero:
            return None
        cfg_h = self.cfg.hero(hero)
        other = "copter" if hero == "machine" else "machine"
        if not cfg_h.get("enabled") and self.cfg.hero(other).get("enabled"):
            if vision.green_ratio(screen, layout.BH_SWAP_BUTTON) > 0.3:
                self.g.click_box(layout.BH_SWAP_BUTTON)
                self.g.sleep(0.4)
                hero = other
            else:
                return None
        elif not cfg_h.get("enabled"):
            return None
        self.g.click(*layout.BH_HERO_CARD)
        x, y = bh_edge_points(stage, side, 1)[0]
        self.g.click(x, y)
        log(f"🦾 Héros posé : {hero}")
        return hero

    def deploy_stage(self, stage: int, side: str) -> None:
        g = self.g
        screen = g.grab()
        hero_present = self.hero_present(screen)
        self.hero = self.deploy_hero(stage, side, screen)
        if stage == 1 and not is_auto(self.cfg.text("slots")):
            slots = parse_slots(self.cfg.text("slots"), 10)
            counts = parse_counts(self.cfg.text("number")) or []
            plan = [(s, counts[i] if i < len(counts) else 1) for i, s in enumerate(slots)]
        else:
            plan = []
            for slot in range(1, 11):
                x = slot_x(slot, hero_present)
                if x <= 0 or not card_alive(screen, x):
                    continue
                plan.append((slot, read_card_count(screen, x)))
        for slot, n in plan:
            g.state.check()
            x = slot_x(slot, hero_present)
            g.click(x, layout.BH_CARD_Y - 20, jitter=8)
            for px, py in bh_edge_points(stage, side, max(1, n)):
                g.click(px, py, jitter=4, delay=(0.05, 0.12))
            for _ in range(6):
                if not card_alive(g.grab(), x):
                    break
                for px, py in bh_edge_points(stage, side, 3):
                    g.click(px, py, jitter=4, delay=(0.05, 0.12))
        self.deployed_at = time.monotonic()
        log(f"✅ Étape {stage} posée ({len(plan)} carte(s))")

    def gauge_charges(self, screen) -> int:
        y1, y2 = layout.BH_GAUGE_Y
        return sum(1 for x1, x2 in layout.BH_GAUGE_SEGMENTS
                   if vision.mask_ratio(screen, (x1, y1, x2, y2), (15, 100, 150), (40, 255, 255)) > 0.5)

    def wait_stage_end(self, timeout: float = 200) -> str | None:
        """« stage2 » (Battle starts in revenu), « end » (Return Home) ou None (timeout).
        Clique la vitesse 1x (→ 4x) et la capacité du héros quand la jauge est assez pleine."""
        g = self.g
        end = time.monotonic() + timeout
        last_speed = last_ability = 0.0
        while time.monotonic() < end:
            g.state.check()
            screen = g.grab()
            if g.find("bh_return_home", screen):
                return "end"
            if time.monotonic() - self.deployed_at > 5 and g.find("bh_battle_starts", screen, scales=(0.9, 1.0, 1.1)):
                return "stage2"
            speed = g.find("bh_speed_1x", screen)
            if speed and time.monotonic() - last_speed > 3:
                g.state.sleep(random.uniform(0.5, 2.0))
                g.click_match(speed)
                last_speed = time.monotonic()
            if self.hero and time.monotonic() - last_ability > 4:
                level = parse_amount(str(self.cfg.hero(self.hero).get("level", "1"))) or 1
                if self.gauge_charges(screen) >= level:
                    g.click(*layout.BH_HERO_CARD)
                    last_ability = time.monotonic()
                    log("⚡ Capacité du héros BH")
            g.state.sleep(0.8)
        return None

    def end_screen(self, stage: int) -> None:
        g, st = self.g, self.state
        screen = g.grab()
        states = []
        for box in layout.BH_STAR_BOXES:
            gold = vision.yellow_ratio(screen, box)
            silver = vision.mask_ratio(screen, box, (0, 0, 170), (179, 60, 255))
            states.append("gold" if gold > 0.35 else ("silver" if silver > 0.35 else "empty"))
        stars = 3 + states.count("silver") if stage == 2 else states.count("gold") + states.count("silver")
        x1, x2 = layout.BH_REWARD_X
        (gy1, gy2), (ey1, ey2) = layout.BH_REWARD_ROWS["gold"], layout.BH_REWARD_ROWS["elixir"]
        gold = ocr.read_amount(screen, (x1, gy1, x2, gy2)) or 0
        elixir = ocr.read_amount(screen, (x1, ey1, x2, ey2)) or 0
        st.add("attacks", 1, "BH")
        st.add("wins" if stars >= 3 else "losses", 1, "BH")
        st.add("stars", stars, "BH")
        st.add("gold", gold, "BH")
        st.add("elixir", elixir, "BH")
        log(f"🏁 BH : {stars}⭐ | +{gold:,} or +{elixir:,} élixir".replace(",", " "))
        m = g.find("bh_return_home", screen)
        if m:
            g.click_match(m)
        g.sleep(2.0)
        ok = g.wait("bh_okay", 4)
        if ok:
            g.click_match(ok)
        g.wait_village(25)

    # ================================================================ village BH
    def after_battle(self, visiting: bool) -> None:
        g, cfg, st = self.g, self.cfg, self.state
        self.cart_in -= 1
        if self.cart_in <= 0:
            self.collect_cart()
            self.cart_in = random.randint(3, 4)
        if cfg.flag("collect_enabled"):
            self.collect_in -= 1
            if self.collect_in <= 0:
                collect_resources(g, BH_COLLECT_KEYS)
                self.collect_in = random.randint(3, 5)
        budget = self.read_storages()
        if pending(cfg) and self.upgrader.due(budget):
            self.upgrader.run(budget)
        cost = parse_amount(cfg.text("wall_cost")) or 0
        if cfg.flag("click_wall_enabled") and cost and max(budget.values() or [0]) >= cost and walls_due(self.walls):
            upgrade_walls(g, cfg, self.walls, budget=budget, stat_mode="BH")
        self.star_lab(budget)
        notify.send_stats("BH", st.stats["BH"], st.uptime())
        if not visiting and self.accounts.rotation_due():
            switch_to_next(g, self.accounts, "BH", lambda p: self.ctx.apply_profile("BH", p))

    def read_storages(self) -> dict:
        from .features.village import read_village_resources
        vals = read_village_resources(self.g.grab())
        return {"gold": vals.get("gold") or 0, "elixir": vals.get("elixir") or 0}

    def collect_cart(self) -> None:
        g = self.g
        g.zoom_out()
        screen = g.grab()
        best = None
        for key in CART_KEYS:
            m = g.find(key, screen, threshold=0.62, scales=(0.9, 1.0, 1.1))
            if m and (best is None or m.score > best.score):
                best = m
        if not best:
            return
        g.click_match(best)
        if not g.wait("bh_cart_title", 4):
            g.close_window()
            return
        c = g.wait("bh_collect", 3, stable=True)
        if c:
            g.click_match(c)
            log("🛒 Charrette d'élixir récoltée")
        g.sleep(0.5)
        g.click_box(layout.CLOSE_VILLAGE_CLICK)

    def star_lab(self, budget: dict) -> None:
        """Laboratoire stellaire : la recherche abordable la moins chère parmi les troupes cochées."""
        todo = pending(self.cfg, "lab").get("Lab", [])
        if not todo:
            return
        g = self.g
        m = g.find("bh_lab_label", scales=(0.9, 1.0, 1.1))
        if not m:
            return
        g.click_match(m)
        r = g.wait("bh_lab_research", 4, stable=True)
        if not r:
            g.click_box(layout.CLOSE_VILLAGE_CLICK)
            return
        g.click_match(r)
        if not g.wait("bh_lab_upgrade_title", 4):
            g.click_box(layout.CLOSE_VILLAGE_CLICK)
            return
        screen = g.grab()
        best = None
        for i, name in enumerate(BH_LAB_TROOPS):
            if name not in todo or i >= len(layout.BH_LAB_CARDS_X) * 2:
                continue
            x = layout.BH_LAB_CARDS_X[i % len(layout.BH_LAB_CARDS_X)]
            y = layout.BH_LAB_CARDS_Y[i // len(layout.BH_LAB_CARDS_X)]
            price = ocr.read_amount(screen, (x - 90, y + 40, x + 90, y + 80))
            if price and price <= budget.get("elixir", 0) and (best is None or price < best[0]):
                best = (price, name, x, y)
        if best:
            g.click(best[2], best[3])
            g.sleep(0.6)
            ok = g.find("upgrade_confirm") or g.find("bh_okay")
            if ok:
                g.click_match(ok)
                from .features.upgrades import decrement
                decrement(self.cfg, "lab", f"Lab|{best[1]}")
                log(f"🧪 Labo stellaire : {best[1]} ({best[0]:,})".replace(",", " "))
        g.click_box(layout.CLOSE_VILLAGE_CLICK)
        g.sleep(0.4)
        g.click_box(layout.CLOSE_VILLAGE_CLICK)
