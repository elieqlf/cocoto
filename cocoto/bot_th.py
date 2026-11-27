"""Boucle du village principal (TH), dans l'ordre observé dans CoCoBot (start_bot.bot_sequence) :

  au START : village affiché / langue / bon village → budget = réserves → raids de la Capitale
  puis à chaque tour :
    pauses / plages horaires / délai → réserves pleines (attente, compte suivant ou visite BH)
    → Jeux de clan → dons (pastille du chat) → Battle → (Ranked) → Find a Match → Cake / renforts
    → Attack! → scout + Next jusqu'au loot minimum → pose de l'armée + héros → surveillance
    (Pick a Reward, fin anticipée) → écran de fin (étoiles, loot, bonus de ligue) → Return Home
    → coffre du Treasure Event → Star bonus → récolte (tous les 7-10 combats) → bâtiments
    → suggestions → laboratoire → murs → stats Discord → rotation des comptes."""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Callable

from . import layout, notify, vision
from .config import LiveConfig
from .features import attack, search
from .features.accounts import AccountSet, switch_to_next
from .features.breaks import BreakScheduler, check_schedule, wait_between_battles
from .features.clan_games import ClanGames
from .features.donate import chat_badge_visible, process_donations
from .features.raids import run_capital_raids
from .features.reconnect import reload_game
from .features.upgrades import Upgrader
from .features.village import (VillageError, check_village, collect_resources, load_village_resources,
                               open_treasure_chest, read_village_resources, star_bonus, storage_fill,
                               travel_to_village)
from .features.walls import WallState, due as walls_due, storage_ready, upgrade_walls
from .game import Game
from .logger import log
from .parsing import parse_amount, parse_early_end
from .state import BotStopped, Reconnect

END_TIMEOUT = 240


@dataclass
class BotContext:
    game: Game
    cfg_th: LiveConfig
    cfg_bh: LiveConfig
    settings: object
    apply_profile: Callable[[str, str], None] = lambda mode, name: None
    popup: Callable[[str, str], None] = lambda title, msg: None
    raid_store: dict = field(default_factory=dict)


class StopWithMessage(Exception):
    def __init__(self, title: str, message: str):
        super().__init__(message)
        self.title, self.message = title, message


class HomeVillageBot:
    def __init__(self, ctx: BotContext):
        self.ctx = ctx
        self.g = ctx.game
        self.cfg = ctx.cfg_th
        self.state = ctx.game.state
        self.breaks = BreakScheduler(self.cfg)
        self.walls = WallState()
        self.upgrader = Upgrader(self.g, self.cfg, "TH")
        self.clan_games = ClanGames(self.g)
        self.accounts = AccountSet(ctx.settings, "accounts")
        self.collect_in = random.randint(7, 10)
        self.full_marks: dict[str, float] = {}
        self.first = True

    # ================================================================ boucle
    def run(self, auto: bool = False) -> None:
        self.state.running_mode = "TH"
        while True:
            try:
                self._session(auto)
                return
            except Reconnect:
                self._reconnect()
                auto = True
            except search.SearchFailed as exc:
                self._fail(str(exc), "search")
            except VillageError as exc:
                raise StopWithMessage(exc.title, exc.message)

    def _fail(self, reason: str, key: str) -> None:
        screen = self.g.grab_now()
        jpeg = vision.to_jpeg(screen) if screen is not None else None
        notify.save_error_shot(reason, jpeg)
        notify.send_alert(f"bot arrêté : {reason}", key, jpeg)
        raise StopWithMessage("Cocoto arrêté", reason)

    def _reconnect(self) -> None:
        self.state.set_status("reconnecting")
        screen = self.g.grab_now()
        notify.send_alert("déconnexion du jeu, rechargement…", "reco",
                          vision.to_jpeg(screen) if screen is not None else None)
        if not reload_game(self.g):
            self._fail("le jeu ne s'est pas rechargé après la déconnexion", "reco_failed")
        self.state.reconnecting = False
        self.state.set_status("farming")
        log("🔌 Jeu rechargé, reprise du bot")

    def _session(self, auto: bool) -> None:
        self.state.set_status("farming")
        check_village(self.g, "TH", travel_ok=auto or self.cfg.flag("bh_when_full"),
                      timeout=60 if auto else 12)
        if self.first:
            load_village_resources(self.g)
            self.first = False
            if self.cfg.flag("donate"):
                self._donate()
        if self.cfg.flag("raids"):
            run_capital_raids(self.g, self.ctx.raid_store)
        while True:
            self.state.check()
            if not self.breaks.check(self.g, notify.send_info):
                return
            if not check_schedule(self.g, self.cfg, notify.send_info):
                return
            if self.cfg.flag("stop_when_full") and not self._storages_ok():
                continue
            if self.cfg.flag("clan_games") and self.clan_games.due():
                self.clan_games.run()
            if self.cfg.flag("donate") and chat_badge_visible(self.g.grab()):
                self._donate()
            if not self.g.wait_village(20):
                self._fail("le bouton Battle n'est pas visible (popup, menu ouvert ?)", "no_village")
            self.battle()
            self.after_battle()
            wait_between_battles(self.g, self.cfg)

    # ================================================================ combat
    def battle(self) -> None:
        g, cfg = self.g, self.cfg
        ranked = search.launch_attack(g, cfg)
        loot = [0, 0, 0] if ranked else search.find_target(g, cfg)
        rule = parse_early_end(cfg.text("early_end"))
        early = attack.EarlyEnd(g, rule, loot)
        idle = attack.BattleIdle(g)
        deployed = attack.deploy_army(g, cfg)
        early.deployed_at = deployed.finished_at
        attack.start_hero_abilities(g, cfg, deployed)

        def watch(screen):
            if attack.handle_pick_reward(g, screen):
                return None
            early(screen)
            idle(screen)
            return None

        names = ["return_home", "return_home1"] + (["claim"] if cfg.flag("treasure_enabled") else [])
        found = g.wait_any(names, timeout=END_TIMEOUT, on_screen=watch, interval=0.8)
        if not found:
            self._fail("écran de fin de combat introuvable depuis 4 min", "end_timeout")
        g.sleep(0.8)
        screen = g.grab()
        stars = attack.count_stars(screen)
        gained = attack.read_end_loot(screen, ranked)
        # contrôle : on ne peut pas gagner plus que le loot disponible au scout (+ bonus)
        if not ranked:
            gained = [v if (not cap or v <= cap * 1.02) else 0 for v, cap in zip(gained, loot)]
        bonus = attack.read_league_bonus(g, 3) or [0, 0, 0]
        total = [a + b for a, b in zip(gained, bonus)]
        st = self.state
        st.add("attacks")
        st.add("wins" if stars >= 1 else "losses")
        st.add("stars", stars)
        for k, v in zip(("gold", "elixir", "dark"), total):
            st.add(k, v)
        st.farmed(*total)
        st.battles += 1
        log(f"🏁 Fin : {stars}⭐ | +{total[0]:,} or +{total[1]:,} élixir +{total[2]:,} noir"
            .replace(",", " "))
        if found[0] == "claim":
            g.click_match(found[1])
            g.sleep(1.0)
            open_treasure_chest(g)
        g.click_box(layout.RETURN_HOME)
        g.sleep(2.0)
        if not g.wait_village(25):
            g.dismiss_common_popups(g.grab())
        star_bonus(g)

    # ================================================================ après le combat
    def after_battle(self) -> None:
        g, cfg, st = self.g, self.cfg, self.state
        if cfg.flag("collect_enabled"):
            self.collect_in -= 1
            if self.collect_in <= 0:
                collect_resources(g)
                self.collect_in = random.randint(7, 10)
        if self.upgrader.due(st.accum):
            self.upgrader.run(st.accum)
        if cfg.flag("suggested_upgrades"):
            res = read_village_resources(g.grab())
            self.upgrader.suggested({k: v or 0 for k, v in res.items()})
        if any((cfg.get("lab") or {}).values()):
            self.upgrader.lab(st.accum)
        if cfg.flag("click_wall_enabled"):
            cost = parse_amount(cfg.text("wall_cost")) or 0
            enough = cost and max(st.accum["gold"], st.accum["elixir"]) >= cost
            if enough and walls_due(self.walls) and storage_ready(g, cfg):
                upgrade_walls(g, cfg, self.walls)
        notify.send_stats("TH", st.stats["TH"], st.uptime())
        if self.accounts.rotation_due():
            switch_to_next(g, self.accounts, "TH", lambda p: self.ctx.apply_profile("TH", p))

    def _donate(self) -> None:
        try:
            process_donations(self.g, self.ctx.settings.get("donate_free_units") or [])
        except (BotStopped, Reconnect):
            raise
        except Exception as exc:
            log(f"⚠️ Dons : {exc}")

    # ================================================================ réserves pleines
    def watched_kinds(self) -> list[str]:
        kinds = [k for k in self.cfg.text("stop_full_kinds").split() if k in ("gold", "elixir", "dark")]
        return kinds or ["gold", "elixir"]

    def _storages_ok(self) -> bool:
        """Réserves surveillées pleines : compte suivant (pas vu plein depuis 1 h), visite de la BH
        (« Then BH »), sinon attente au village jusqu'à ce que tu dépenses."""
        fill = storage_fill(self.g.grab())
        kinds = self.watched_kinds()
        if not all(fill.get(k, 0) >= 0.95 for k in kinds):
            return True
        text = ", ".join(f"{k} {fill.get(k, 0):.0%}" for k in kinds)
        log(f"🏦 Réserves pleines ({text})")
        if self.accounts.enabled():
            self.full_marks[self.state.current_account or "?"] = time.time()
            candidates = [n for n, _ in self.accounts.accounts()
                          if time.time() - self.full_marks.get(n, 0) > 3600]
            if candidates and switch_to_next(self.g, self.accounts, "TH",
                                             lambda p: self.ctx.apply_profile("TH", p)):
                return False
        if self.cfg.flag("bh_when_full"):
            from .bot_bh import BuilderBaseBot
            if travel_to_village(self.g, "BH"):
                end = time.monotonic() + 45 * 60
                BuilderBaseBot(self.ctx).run(until=lambda: time.monotonic() >= end)
                travel_to_village(self.g, "TH")
                self.state.running_mode = "TH"
                return False
        notify.send_alert(f"réserves pleines ({text}) : le bot a arrêté d'attaquer. "
                          "Dépense tes ressources et il repart tout seul.", "full")
        self.state.set_status("full")
        while True:
            self.state.sleep(60)
            fill = storage_fill(self.g.grab())
            if not all(fill.get(k, 0) >= 0.95 for k in kinds):
                self.state.set_status("farming")
                return False
