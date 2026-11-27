"""Combat du village principal : côté d'attaque, points de pose, lecture de l'armée, troupes, sorts,
capacités des héros, fin anticipée (Surrender) et lecture de l'écran de fin.

Fonctionnement relevé dans CoCoBot :
  1. côté au hasard (jamais 2 fois de suite le même), souris au centre, 3 à 5 crans de molette
     (dézoom), glissement de 400 px vers le bas (côtés du haut) ou le haut (côtés du bas) : la vue
     est alors en butée et le bord voulu de la carte (un losange) est à une place connue ;
  2. armée « auto » : la barre des cartes est lue (cartes colorées, compteur « x12 », bandeau violet
     = sort) ; sinon Slot / Count per Slot / Spell Slot de la carte ARMY ;
  3. chaque carte est sélectionnée puis posée en balayant le bord (une part du bord par troupe) ;
     les sorts sur une ligne parallèle plus à l'intérieur ; carte encore pleine → reposée ailleurs ;
  4. capacités des héros après le délai réglé (« 5 » ou « 2+1 » = 1 à 3 s) ;
  5. pendant l'attente de l'écran de fin : popup « Pick a Reward! », fin anticipée, petits gestes."""
from __future__ import annotations

import math
import random
import re
import threading
import time
from dataclasses import dataclass, field

import cv2
import numpy as np

from .. import humanize, layout, ocr, vision
from ..config import HERO_KEYS, HERO_NAMES, LiveConfig
from ..game import Game
from ..logger import log
from ..parsing import (EarlyEndRule, is_auto, parse_counts, parse_slots, pick_hero_delay)

_last_side: str | None = None


# ====================================================================== géométrie
def map_corners(view: str, half_w: float | None = None, half_h: float | None = None):
    cx, cy = layout.MAP_CX, layout.MAP_VIEW_CY[view]
    hw, hh = half_w or layout.MAP_HALF_W, half_h or layout.MAP_HALF_H
    return {"left": (cx - hw, cy), "right": (cx + hw, cy), "top": (cx, cy - hh), "bottom": (cx, cy + hh)}


SIDE_EDGES = {   # côté → (vue après glissement, coin de départ, coin d'arrivée, part du bord gardée)
    "top_left": ("down", "left", "top", layout.ATTACK_EDGE_SPAN["top"]),
    "top_right": ("down", "top", "right", layout.ATTACK_EDGE_SPAN["top"]),
    "bottom_left": ("up", "left", "bottom", layout.ATTACK_EDGE_SPAN["bottom"]),
    "bottom_right": ("up", "bottom", "right", layout.ATTACK_EDGE_SPAN["bottom"]),
}


def inward_normal(side: str) -> tuple[float, float]:
    """Normale unitaire au bord, orientée vers le centre de la carte (= vers la base)."""
    view, a, b, _ = SIDE_EDGES[side]
    c = map_corners(view)
    (ax, ay), (bx, by) = c[a], c[b]
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    nx, ny = -dy / length, dx / length
    cx, cy = layout.MAP_CX, layout.MAP_VIEW_CY[view]
    mx, my = (ax + bx) / 2, (ay + by) / 2
    if (cx - mx) * nx + (cy - my) * ny < 0:
        nx, ny = -nx, -ny
    return nx, ny


def on_screen(x: float, y: float) -> bool:
    """Point posable : dans l'écran, pas sur la barre de l'armée ni sur les boutons des coins."""
    if not (20 <= x <= layout.W - 20 and 20 <= y <= layout.ARMY_BAR_Y[0] - 15):
        return False
    if x < 360 and y < 270:       # loot disponible en haut à gauche
        return False
    if x > 1700 and y > 760:      # bouton Next / Surrender
        return False
    return True


def edge_points(side: str, n: int | None = None, inset: float | None = None,
                depth: float = 0.0) -> list[tuple[int, int]]:
    """Points régulièrement espacés sur le bord du côté, décalés vers l'intérieur de inset (+ depth)."""
    view, a, b, (t0, t1) = SIDE_EDGES[side]
    c = map_corners(view)
    (ax, ay), (bx, by) = c[a], c[b]
    nx, ny = inward_normal(side)
    n = n or layout.ATTACK_EDGE_N_POINTS
    d = (layout.ATTACK_EDGE_INSET if inset is None else inset) + depth
    pts = []
    for i in range(n):
        t = t0 + (t1 - t0) * (i / max(1, n - 1))
        x, y = ax + (bx - ax) * t + nx * d, ay + (by - ay) * t + ny * d
        if on_screen(x, y):
            pts.append((int(x), int(y)))
    return pts


def sweep_points(side: str, n: int, spread_pct: float = 0.0) -> list[tuple[int, int]]:
    """n points pour une carte : le bord est coupé en n parts égales et chaque troupe tombe au hasard
    dans sa part (tout le bord reste couvert, sans points fixes). spread_pct > 0 : plus d'écart."""
    pts = edge_points(side, n=60)
    if not pts:
        return []
    if spread_pct > 0:                 # « Troop spacing % » : resserre au centre du bord sinon
        keep = max(2, int(len(pts) * min(1.0, 0.35 + spread_pct / 100 * 0.65)))
        start = (len(pts) - keep) // 2
        pts = pts[start:start + keep]
    out = []
    for i in range(n):
        lo = int(len(pts) * i / n)
        hi = max(lo + 1, int(len(pts) * (i + 1) / n))
        x, y = random.choice(pts[lo:hi])
        out.append((x + humanize.offset(6), y + humanize.offset(6)))
    return out


def spell_points(side: str, n: int) -> list[tuple[int, int]]:
    """n points sur une parallèle au bord, plus à l'intérieur (sur les défenses)."""
    depth = random.uniform(230, 330)
    pts = edge_points(side, n=max(3, n + 2), depth=depth)[1:-1] or edge_points(side, n=n, depth=depth)
    out = []
    for i in range(n):
        x, y = pts[i % len(pts)] if pts else layout.SCREEN_CENTER
        out.append((x + humanize.offset(25), y + humanize.offset(25)))
    return out


def choose_side() -> str:
    global _last_side
    sides = [s for s in layout.ATTACK_SIDES if s != _last_side]
    _last_side = random.choice(sides)
    return _last_side


def prepare_view(game: Game, side: str) -> None:
    """Dézoom puis glissement : la vue se cale en butée, le bord du côté est à sa place connue."""
    game.zoom_out(random.randint(3, 5))
    view = SIDE_EDGES[side][0]
    cx, cy = layout.SCREEN_CENTER
    sx, sy = cx + random.randint(-60, 60), cy + random.randint(-40, 40)
    dist = layout.DRAG_DISTANCE * random.uniform(1.0, 1.1)
    ey = sy + dist if view == "down" else sy - dist
    game.drag(sx, sy, sx + random.randint(-20, 20), int(max(30, min(layout.H - 30, ey))), 0.35)
    game.sleep(0.3)
    log(f"🗺️ Côté d'attaque : {side}")


# ====================================================================== barre de l'armée
@dataclass
class Card:
    x: int
    left: int
    right: int
    count: int | None      # None = héros / machine (pas de compteur), 0 = illisible
    spell: bool = False
    hero: str | None = None


def _colored_columns(screen: np.ndarray) -> np.ndarray:
    y1, y2 = layout.ARMY_BAR_Y
    band = cv2.cvtColor(screen[y1 + 20:y2 - 10], cv2.COLOR_BGR2HSV)
    sat = band[:, :, 1].astype(np.float32)
    val = band[:, :, 2].astype(np.float32)
    return ((sat > 70) & (val > 70)).mean(axis=0)


def card_alive(screen: np.ndarray, x: int) -> bool:
    """Carte encore utilisable (colorée) ; vide = grise."""
    y1, y2 = layout.ARMY_BAR_Y
    return vision.gray_ratio(screen, (x - 30, y1 + 25, x + 30, y2 - 15), max_sat=45) < 0.6


CARD_W = (100, 116)            # largeur d'une carte (mesuré GPG 2026-11 : 108-111 px, pas de 121)


def card_edges(screen: np.ndarray) -> list[tuple[int, int]]:
    """Cartes repérées par leurs deux bords verticaux, nets sur toute la hauteur de la barre.
    (Le fond de la barre est translucide : la couleur seule rate les cartes claires — siège, sorts.)"""
    y1, y2 = layout.ARMY_BAR_Y
    gray = cv2.cvtColor(screen[y1:y2], cv2.COLOR_BGR2GRAY).astype(np.int16)
    if gray.shape[0] < 20:
        return []
    frac = (np.abs(np.diff(gray, axis=1)) > 25).mean(axis=0)
    peaks = [x for x in range(1, len(frac) - 1)
             if frac[x] > 0.8 and frac[x] >= frac[x - 1] and frac[x] >= frac[x + 1]]
    cards, last_right = [], -1
    for left in peaks:
        if left <= last_right:
            continue
        rights = [r for r in peaks if CARD_W[0] <= r - left <= CARD_W[1]]
        if rights:
            right = max(rights)
            cards.append((left, right + 1))
            last_right = right + 1
    return cards


def find_cards(screen: np.ndarray) -> list[tuple[int, int]]:
    """(gauche, droite) des cartes encore utilisables (pas grises) de la barre, de gauche à droite."""
    edges = card_edges(screen)
    if edges:
        return [(l, r) for l, r in edges if card_alive(screen, (l + r) // 2)]
    col = _colored_columns(screen)
    on = col > 0.35
    cards, start = [], None
    for x, v in enumerate(list(on) + [False]):
        if v and start is None:
            start = x
        elif not v and start is not None:
            if x - start >= 60:
                width = x - start
                n = max(1, round(width / 118))   # cartes collées : découpe à la largeur d'une carte
                for k in range(n):
                    cards.append((start + width * k // n, start + width * (k + 1) // n))
            start = None
    return cards


def is_spell_card(screen: np.ndarray, left: int, right: int) -> bool:
    """Bandeau du haut violet (sort) plutôt que bleu (troupe), sur toute la largeur."""
    y1 = layout.ARMY_BAR_Y[0]
    h = vision.hsv(screen, (left + 6, y1 + 8, right - 6, y1 + 22))
    if h.size == 0:
        return False
    # mesuré GPG 2026-11 : troupe H≈104, sort H≈126 (les cadres des héros sont violets aussi :
    # read_army n'appelle ceci que pour les cartes qui ont un compteur « xN »)
    hue = h[:, :, 0]
    violet = np.count_nonzero((hue >= 117) & (hue <= 160) & (h[:, :, 1] > 60))
    blue = np.count_nonzero((hue >= 90) & (hue < 117) & (h[:, :, 1] > 60))
    return violet > blue * 1.5


def read_card_count(screen: np.ndarray, left: int, right: int) -> int | None:
    """« x12 » en haut de la carte : 12 ; None sans compteur (héros) ; 0 si illisible."""
    y1 = layout.ARMY_BAR_Y[0]
    # « xN » est aligné à droite ; en haut à gauche, un héros peut porter l'icône de son familier
    # (vu GPG 2026-11 : Champion + familier lu « x1 ») → on ne regarde que la partie droite.
    box = (left + 46, y1 - 2, right - 4, y1 + 30)
    zone, _, _ = vision.crop(screen, box)
    mask = vision.white_text_mask(zone, v_min=200, s_max=70)
    comps = vision.components(mask, min_h=10, max_h=30, min_area=15)
    if len(comps) < 2:          # pas de « x » + chiffre : héros ou machine de siège
        return None
    comps = sorted(comps, key=lambda c: c[0])
    x_comp, digits = comps[0], comps[1:]
    # garder les chiffres alignés sur le « x » (pas de morceaux du dessin de la carte)
    yc = x_comp[1] + x_comp[3] / 2
    digits = [c for c in digits if abs(c[1] + c[3] / 2 - yc) < 8][:3]
    if not digits:
        return 0
    keep = np.zeros_like(mask)
    for dx, dy, dw, dh, _a in digits:
        keep[dy:dy + dh, dx:dx + dw] = mask[dy:dy + dh, dx:dx + dw]
    img = cv2.copyMakeBorder(255 - keep, 8, 8, 8, 8, cv2.BORDER_CONSTANT, value=255)
    img = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    text = re.sub(r"\D", "", "".join(ocr.read_text(img, allowlist="0123456789")))
    if len(text) == len(digits):
        return int(text)
    # EasyOCR perd souvent le « 1 » fin : composante étroite = 1, sinon lecture seule de la composante
    out = ""
    for dx, dy, dw, dh, _a in digits:
        if dw <= dh * 0.5:
            out += "1"
            continue
        one = cv2.copyMakeBorder(255 - keep[dy:dy + dh, dx:dx + dw], 8, 8, 8, 8,
                                 cv2.BORDER_CONSTANT, value=255)
        d = re.sub(r"\D", "", "".join(ocr.read_text(cv2.resize(one, None, fx=2, fy=2), allowlist="0123456789")))
        if len(d) != 1:
            return 0
        out += d
    return int(out)


def hero_on_card(game: Game, screen: np.ndarray, left: int, right: int) -> str | None:
    box = (left - 10, layout.ARMY_BAR_Y[0] - 10, right + 10, layout.ARMY_BAR_Y[1])
    best, key = 0.0, None
    for i, k in enumerate(HERO_KEYS, start=1):
        # portrait d'origine + skins capturés par l'utilisateur (%APPDATA%\Cocoto\img\heroN_*.png)
        for name in game.tpl.variants(f"hero{i}") or [f"hero{i}"]:
            s = game.score(name, screen, box)
            if s > best:
                best, key = s, k
    return key if best >= 0.75 else None


def read_army(game: Game, screen: np.ndarray) -> list[Card]:
    cards = []
    for left, right in find_cards(screen):
        count = read_card_count(screen, left, right)
        hero = hero_on_card(game, screen, left, right) if count is None else None
        spell = count is not None and is_spell_card(screen, left, right)
        cards.append(Card((left + right) // 2, left, right, count, spell, hero))
    return cards


def read_army_stable(game: Game, tries: int = 3) -> list[Card]:
    """Barre lue 2 fois à l'identique (places + compteurs), sinon la dernière lecture non vide."""
    prev, last = None, []
    for _ in range(tries):
        army = read_army(game, game.grab())
        sig = [(c.x // 10, c.count, c.spell) for c in army]
        if army and sig == prev:
            return army
        prev, last = sig, army or last
        game.sleep(0.3)
    return last


# ====================================================================== pose
def deploy_card(game: Game, card_x: int, points: list[tuple[int, int]], delay=(0.04, 0.11)) -> None:
    game.click(card_x, layout.ARMY_CARD_Y, jitter=10)
    for x, y in points:
        game.click(x, y, jitter=4, delay=delay)


def unit_on_field(screen: np.ndarray, x: int) -> bool:
    """Héros / machine de siège posé : sa carte montre une barre de vie verte au-dessus
    (mesuré GPG 2026-11 : y ≈ 895-907, H≈48 S≈245 V≈195). L'herbe du village vue derrière la barre
    est verte aussi mais terne (S≈139 V≈110) : seuils S/V stricts."""
    y1, y2 = layout.UNIT_HEALTH_BAR_Y
    return vision.mask_ratio(screen, (x - 40, y1, x + 40, y2), (38, 215, 160), (62, 255, 255)) > 0.25


def deploy_single(game: Game, card_x: int, side: str, spread: float = 0.0, tries: int = 2,
                  wait: float = 2.5) -> bool:
    """Héros / machine : un clic de pose, vérifié ; sinon un autre point du bord (point tombé sur
    une zone interdite : vu GPG 2026-11, Prince des sbires jamais posé).
    Recliquer la carte d'un héros DÉJÀ posé déclencherait sa capacité : on attend donc la barre de vie
    jusqu'à `wait` s (elle n'apparaît pas tout de suite) avant un seul nouvel essai."""
    for i in range(tries):
        deploy_card(game, card_x, sweep_points(side, 1, spread))
        end = time.monotonic() + wait
        while True:
            game.sleep(0.4)
            if unit_on_field(game.grab(), card_x):
                return True
            if time.monotonic() >= end:
                break
        log(f"↩️ Carte {card_x} pas posée (essai {i + 1}/{tries})")
    return False


def deploy_until_empty(game: Game, card_x: int, side: str, spell: bool = False, batch: int = 5,
                       max_rounds: int = 12) -> None:
    """Carte au compteur illisible ou encore pleine : séries de clics jusqu'à ce qu'elle soit grise."""
    for _ in range(max_rounds):
        if not card_alive(game.grab(), card_x):
            return
        pts = spell_points(side, 1) if spell else sweep_points(side, batch)
        deploy_card(game, card_x, pts)


def slot_gap(base: float = 0.35) -> float:
    """Attente entre 2 cartes : souvent courte, parfois longue (moyenne ≈ base)."""
    return random.expovariate(1 / base) if random.random() < 0.8 else random.uniform(base, base * 3)


@dataclass
class DeployResult:
    side: str
    heroes: dict = field(default_factory=dict)   # clé héros → x de sa carte
    finished_at: float = 0.0


def deploy_army(game: Game, cfg: LiveConfig) -> DeployResult:
    side = choose_side()
    prepare_view(game, side)
    spread = float(cfg.number("deploy_spread", 0))
    result = DeployResult(side)
    if is_auto(cfg.text("slots")):
        army = read_army_stable(game)
        log("🪖 Armée lue : " + ", ".join(
            f"{'S' if c.spell else (c.hero or 'T')}{'' if c.count is None else c.count}@{c.x}" for c in army))
        troops = [c for c in army if not c.spell]
        spells = [c for c in army if c.spell]
        for c in troops:
            game.state.check()
            if c.count is None:             # héros / machine : un seul clic, vérifié
                deploy_single(game, c.x, side, spread)
                if c.hero:
                    result.heroes[c.hero] = c.x
            elif c.count == 0:
                deploy_until_empty(game, c.x, side)
            else:
                deploy_card(game, c.x, sweep_points(side, c.count, spread))
                if card_alive(game.grab(), c.x):
                    deploy_until_empty(game, c.x, side)
            game.state.sleep(slot_gap())
        for c in spells:
            n = c.count or 1
            deploy_card(game, c.x, spell_points(side, n), delay=(0.15, 0.35))
            if c.count == 0:
                deploy_until_empty(game, c.x, side, spell=True)
    else:
        slots = parse_slots(cfg.text("slots"))
        counts = parse_counts(cfg.text("number"))
        spells = set(parse_slots(cfg.text("spell")))
        for i, slot in enumerate(slots):
            game.state.check()
            x = layout.SLOT_POSITIONS[slot]
            n = counts[i] if i < len(counts) else 1
            if slot in spells:
                deploy_card(game, x, spell_points(side, n), delay=(0.15, 0.35))
            else:
                deploy_card(game, x, sweep_points(side, n, spread))
            game.state.sleep(slot_gap())
        for slot in sorted(spells - set(slots)):
            deploy_card(game, layout.SLOT_POSITIONS[slot], spell_points(side, 1), delay=(0.15, 0.35))
        # héros : cartes reconnues par leur portrait
        screen = game.grab()
        for left, right in find_cards(screen):
            h = hero_on_card(game, screen, left, right)
            if h:
                result.heroes[h] = (left + right) // 2
    result.finished_at = time.monotonic()
    log("✅ Armée posée")
    return result


def start_hero_abilities(game: Game, cfg: LiveConfig, deployed: DeployResult) -> threading.Thread | None:
    """Clique la carte de chaque héros activé au délai tiré pour ce combat (thread séparé)."""
    plan = []
    for key in HERO_KEYS:
        h = cfg.hero(key)
        if h.get("enabled") and key in deployed.heroes:
            plan.append((pick_hero_delay(str(h.get("delay", "0"))), key, deployed.heroes[key]))
    if not plan:
        return None
    plan.sort()
    log("🦸 Capacités : " + ", ".join(f"{HERO_NAMES[HERO_KEYS.index(k)]} à {d:.1f}s" for d, k, _ in plan))

    def run():
        try:
            for delay, key, x in plan:
                wait = deployed.finished_at + delay - time.monotonic()
                if wait > 0:
                    game.state.sleep(wait)
                game.click(x, layout.ARMY_CARD_Y, jitter=8)
                log(f"⚡ Capacité de {HERO_NAMES[HERO_KEYS.index(key)]}")
        except Exception:
            pass

    t = threading.Thread(target=run, daemon=True, name="heroes")
    t.start()
    return t


# ====================================================================== pendant le combat
def read_damage(screen: np.ndarray) -> int | None:
    """% de destruction affiché pendant le combat (le « % » est retiré)."""
    zone, _, _ = vision.crop(screen, layout.DAMAGE_BOX)
    mask = vision.white_text_mask(zone, v_min=210, s_max=50)
    comps = vision.components(mask, min_h=14, max_h=50)
    if len(comps) < 2:
        return None
    x_cut = comps[-1][0]                       # la composante la plus à droite = « % »
    text = "".join(ocr.read_text(255 - mask[:, :x_cut], allowlist="0123456789"))
    return int(text) if text.isdigit() and int(text) <= 100 else None


def read_remaining_loot(screen: np.ndarray) -> list[int | None]:
    x1, x2 = layout.REMAINING_LOOT_X
    return [ocr.read_amount(screen, (x1, y1, x2, y2)) for (y1, y2) in layout.AVAILABLE_LOOT_ROWS.values()]


def surrender(game: Game) -> bool:
    game.click_box(layout.SURRENDER_BUTTON)
    m = game.wait("surrender_okay", 5, stable=True)
    if m:
        game.click_match(m)
        return True
    return False


class EarlyEnd:
    """Abandonne le combat quand le délai après la pose, le % de loot pris, la destruction ou le loot
    figé est atteint (une lecture illisible remet le décompte « loot figé » à zéro)."""

    def __init__(self, game: Game, rule: EarlyEndRule, initial_loot: list[int]):
        self.game, self.rule = game, rule
        self.initial = initial_loot
        self.deployed_at: float | None = None
        self.done = False
        self.last_loot = None
        self.loot_changed_at = time.monotonic()
        self.last_read = 0.0

    def taken_percent(self, remaining: list[int | None]) -> float | None:
        total = sum(v for v in self.initial if v)
        if not total or any(v is None for v in remaining[:2]):
            return None
        left = sum(r for r, i in zip(remaining, self.initial) if r is not None and i)
        return max(0.0, min(100.0, (total - left) * 100 / total))

    def __call__(self, screen: np.ndarray) -> str | None:
        if self.done or not self.rule.active or self.deployed_at is None:
            return None
        now = time.monotonic()
        reason = None
        if self.rule.seconds is not None and now - self.deployed_at >= self.rule.seconds:
            reason = f"{self.rule.seconds:.0f}s après la pose"
        if reason is None and now - self.last_read >= 2.0:
            self.last_read = now
            if self.rule.damage is not None:
                dmg = read_damage(screen)
                if dmg is not None and dmg >= self.rule.damage:
                    reason = f"destruction {dmg}%"
            if reason is None and (self.rule.percent is not None or self.rule.stale is not None):
                remaining = read_remaining_loot(screen)
                pct = self.taken_percent(remaining)
                if self.rule.percent is not None and pct is not None and pct >= self.rule.percent:
                    reason = f"{pct:.0f}% du loot pris"
                if all(v is not None for v in remaining[:2]):
                    if remaining != self.last_loot:
                        self.last_loot, self.loot_changed_at = remaining, now
                    elif self.rule.stale is not None and now - self.loot_changed_at >= self.rule.stale:
                        reason = f"loot figé depuis {self.rule.stale:.0f}s"
                else:
                    self.loot_changed_at = now
        if reason:
            self.done = True
            log(f"🏳️ Fin anticipée : {reason} → Surrender")
            surrender(self.game)
        return reason


def handle_pick_reward(game: Game, screen: np.ndarray) -> bool:
    """« Pick a Reward! » affiché : clic sur la carte de droite."""
    if game.find("pick_reward", screen, layout.PICK_REWARD_BOX):
        game.click_box(layout.PICK_REWARD_RIGHT_CARD)
        log("🎁 Pick a Reward! → carte de droite")
        game.sleep(1.0)
        return True
    return False


class BattleIdle:
    """1 à 3 petits mouvements de souris par combat, jamais sur une popup ni sur la barre."""

    def __init__(self, game: Game):
        self.game = game
        self.left = random.randint(1, 3)
        self.next_at = time.monotonic() + random.uniform(8, 25)

    def __call__(self, screen) -> None:
        if self.left <= 0 or time.monotonic() < self.next_at:
            return
        self.left -= 1
        self.next_at = time.monotonic() + random.uniform(10, 30)
        x, y = random.randint(500, 1400), random.randint(250, 750)
        try:
            self.game.backend.move(x, y, duration=random.uniform(0.2, 0.6))
        except Exception:
            pass


# ====================================================================== écran de fin
def count_stars(screen: np.ndarray, boxes=None, ratio: float | None = None) -> int:
    """Étoiles argentées/dorées allumées (pixels clairs peu saturés ou jaunes) dans chaque case."""
    n = 0
    for box in boxes or layout.STAR_BOXES:
        lit = vision.mask_ratio(screen, box, (0, 0, 170), (179, 70, 255)) + vision.yellow_ratio(screen, box)
        if lit >= (ratio or layout.STAR_SILVER_RATIO):
            n += 1
    return n


def read_end_loot(screen: np.ndarray, ranked: bool = False) -> list[int]:
    rows = layout.RANKED_LOOT_ROWS if ranked else layout.END_LOOT_ROWS
    x1, x2 = layout.RANKED_LOOT_X if ranked else layout.END_LOOT_X
    out = []
    for y1, y2 in rows.values():
        v = ocr.read_amount(screen, (x1, y1, x2, y2))
        out.append(v or 0)
    return out


def read_league_bonus_rows(screen: np.ndarray) -> list[int]:
    """« +90000 » / « +90000 » / « +950 » du cadre de bonus, une ligne à la fois (0 si illisible)."""
    x1, x2 = layout.LEAGUE_BONUS_X
    out = []
    for y1, y2 in layout.LEAGUE_BONUS_ROWS.values():
        zone, _, _ = vision.crop(screen, (x1, y1, x2, y2))
        if zone.size == 0:
            out.append(0)
            continue
        img, _n = ocr.prepare_digits(zone)
        text = "".join(ocr.read_text(img, allowlist="+0123456789"))
        digits = re.sub(r"\D", "", text.split("+")[-1])
        out.append(int(digits) if digits else 0)
    return out


def read_league_bonus(game: Game, timeout: float = 4.0) -> list[int] | None:
    """Bonus de ligue [or, élixir, noir] : deux lectures identiques de suite (le cadre glisse)."""
    end = time.monotonic() + timeout
    prev = None
    while time.monotonic() < end:
        screen = game.grab()
        if not game.find("league_bonus", screen):
            game.state.sleep(0.4)
            continue
        vals = read_league_bonus_rows(screen)
        if vals == prev:
            return vals
        prev = vals
        game.state.sleep(0.4)
    return None
