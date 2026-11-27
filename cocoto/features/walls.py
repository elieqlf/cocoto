"""Amélioration automatique des murs, payée avec le loot farmé (comme CoCoBot).

Quand l'or ou l'élixir farmé depuis START atteint « Wall cost » : panneau Build → lignes « Wall »
lues par OCR → mur au bon prix → (« Walls when storage ≥ X % » : Upgrade More + « +1 Add Wall »
pour en prendre plusieurs d'un coup) → bouton Upgrade de la ressource → Confirm / Okay."""
from __future__ import annotations

import re
import time

import cv2
import numpy as np

from .. import layout, ocr, vision
from ..config import LiveConfig
from ..game import Game
from ..logger import log
from ..parsing import parse_amount
from .panel import BuildPanel
from .village import storage_fill

WALL_RECHECK_EVERY = 5      # combats d'attente après « aucun mur à ce prix »
WALL_SCROLL_NOTCHES = 3     # 1 cran ≈ 175 px (un message par cran) → ~525 px par page sur ~860 visibles


class WallState:
    def __init__(self):
        self.wait_battles = 0
        self.alerted = False
        self.costs_seen: set[int] = set()


def wall_fill_target(cfg: LiveConfig) -> float:
    v = parse_amount(cfg.text("wall_fill"))
    return min(0.97, v / 100) if v else 0.0


def storage_ready(game: Game, cfg: LiveConfig) -> bool:
    """« Walls when storage ≥ X % » : la réserve d'or ou d'élixir a atteint le seuil (sinon True)."""
    target = wall_fill_target(cfg)
    if not target:
        return True
    fill = storage_fill(game.grab())
    best = max(fill.get("gold", 0), fill.get("elixir", 0))
    if not best:
        return True
    if best < target:
        log(f"🧱 Murs : réserves à {best:.0%} < {target:.0%} → plus tard")
        return False
    return True


def due(state: WallState) -> bool:
    if state.wait_battles > 0:
        state.wait_battles -= 1
        log(f"🧱 Murs : nouvel essai dans {state.wait_battles} combat(s)")
        return False
    return True


def wall_rows(panel: BuildPanel, screen) -> list[tuple[int, str]]:
    rows = panel.rows(screen)
    return [(y, t) for y, t in rows if re.search(r"\b(wall|mur)\b", t, re.I) or t.lower().startswith("wal")]


def find_wall(panel: BuildPanel, cost: int, max_pages: int = 30) -> tuple[int, int] | None:
    """(y de la ligne, prix lu) d'un mur au prix voulu, en descendant dans la liste."""
    prev = None
    for page in range(max_pages):
        screen = panel.game.wait_still(layout.WALL_LIST_BOX)
        for y, text in wall_rows(panel, screen):
            price = panel.read_cost(screen, y)
            if price is None:
                continue
            # « Wall x 25 — New — FREE » : les lettres passent pour des chiffres ; un vrai prix a
            # toujours son icône de ressource
            if panel.cost_resource(screen, y) is None:
                continue
            if price == cost and not panel.cost_is_red(screen, y):
                return y, price
        zone, _, _ = vision.crop(screen, layout.WALL_LIST_BOX)
        if prev is not None and vision.same_image(prev, zone):
            break    # bout de la liste
        prev = zone.copy()
        panel.scroll(-1, WALL_SCROLL_NOTCHES)
    return None


def selected_walls(game: Game, screen) -> int | None:
    """Nombre de murs sélectionnés, lu dans « Wall (Level 13) x 2 »."""
    text = ocr.read_box_text(screen, layout.WALL_SELECTED_TITLE_BOX)
    m = re.search(r"x\s*(\d{1,3})", text)
    return int(m.group(1)) if m else (1 if "wall" in text.lower() else None)


def add_one_button(game: Game, screen=None):
    """« +1 Add Wall ». Le jeu affiche Remove Wall, +10 Add Wall, +1 Add Wall dans cet ordre et le
    texte « Add Wall » est le même : on prend le plus à droite (jamais le +10)."""
    screen = game.grab() if screen is None else screen
    tpl = game.tpl.get("wall_add1")
    if tpl is None:
        return None
    hits = vision.match_all(screen, tpl, 0.8, layout.UPGRADE_WINDOW_BUTTONS, min_dist=60)
    hits = [m for m in hits if abs(m.y - hits[0].y) < 20] if hits else []
    return max(hits, key=lambda m: m.x) if len(hits) >= 2 else None


def select_more(game: Game, wanted: int) -> int:
    """Upgrade More puis « +1 Add Wall » jusqu'à wanted murs (jamais plus : on ne paie pas plus)."""
    more = game.find("wall_more", box=layout.UPGRADE_WINDOW_BUTTONS)
    if not more:
        return 1
    game.click_match(more)
    game.sleep(0.6)
    count = 1
    for _ in range(wanted - 1):
        add = add_one_button(game)
        if not add:
            break
        game.click_match(add)
        game.sleep(0.25)
        count += 1
    shown = selected_walls(game, game.grab())
    return shown or count


PRICE_ICON_HSV = {"gold": ((17, 150, 170), (35, 255, 255)), "elixir": ((135, 120, 140), (165, 255, 255))}


def upgrade_button_for(game: Game, resource: str):
    """Bouton Upgrade payé avec resource, repéré par l'icône de son prix (pièce / goutte) sur la
    rangée des prix, avec le prix en chiffres blancs juste à gauche. Mesuré GPG 2026-11 : un mur →
    or (749, 830) / élixir (903, 829) ; mode « Upgrade More » (deux marteaux, le template up ne
    matche plus) → or (825, 830) / élixir (979, 829). Le bouton est sous l'icône, décalé à gauche."""
    screen = game.grab()
    x1, y1, x2, y2 = layout.UPGRADE_PRICE_BAND
    band = vision.hsv(screen, (x1, y1, x2, y2))
    if band.size == 0:
        return None
    lo, hi = PRICE_ICON_HSV[resource]
    mask = cv2.inRange(band, np.array(lo), np.array(hi))
    n, _labels, stats, cents = cv2.connectedComponentsWithStats(mask, 8)
    found = []
    for i in range(1, n):
        _bx, _by, bw, bh, area = stats[i]
        # pièce / goutte ≈ 16x15 ; le décor jaune derrière les boutons (ex. 32x24 près de « Select
        # Row », vu GPG 2026-11) passait l'ancien filtre et faisait sélectionner toute la rangée
        if not (90 <= area <= 320 and max(bw, bh) <= 24 and 0.7 <= bw / max(1, bh) <= 1.4):
            continue
        ix, iy = int(cents[i][0]) + x1, int(cents[i][1]) + y1
        white = vision.white_text_mask(vision.crop(screen, (ix - 115, iy - 10, ix - 12, iy + 10))[0],
                                       v_min=200, s_max=60)
        if white.size and (white > 0).mean() > 0.08:
            found.append(vision.Match(1.0, ix + layout.UPGRADE_ICON_TO_BUTTON[0],
                                      iy + layout.UPGRADE_ICON_TO_BUTTON[1], 110, 90))
    return min(found, key=lambda m: m.x) if found else None


CLOSE_X_MIN = 0.7          # croix de fenêtre (image agrandie depuis 1765 px : ≈0,77-0,93)


def discounted_upgrade_button(game: Game, screen=None):
    """Pendant une promotion, le bouton de confirmation n'est pas « Confirm » mais un gros bouton vert
    « Upgrade » avec le prix réduit et l'ancien prix barré (vu GPG 2026-11 : 1 500 000 / 3 000 000).
    À sa gauche, le bouton bleu « Wall Ring » : jamais cliqué (seul le vert est cherché)."""
    screen = game.grab() if screen is None else screen
    x1, y1, x2, y2 = layout.UPGRADE_WINDOW_GREEN_BOX
    band = vision.hsv(screen, (x1, y1, x2, y2))
    if band.size == 0:
        return None
    mask = cv2.inRange(band, np.array((35, 120, 120)), np.array((60, 255, 255)))
    n, _labels, stats, _c = cv2.connectedComponentsWithStats(mask, 8)
    for i in range(1, n):
        bx, by, bw, bh, area = stats[i]
        if 200 <= bw <= 420 and 90 <= bh <= 200 and area > 0.35 * bw * bh:   # texte non vert : ≈0,45
            return vision.Match(1.0, x1 + bx + bw // 2, y1 + by + bh // 2, bw, bh)
    return None


def confirm(game: Game) -> bool:
    """Confirm (un mur) ou Okay (plusieurs murs), vu 2 fois au même endroit ; sinon le bouton vert
    « Upgrade » d'une fenêtre à prix réduit. Rien trouvé : la fenêtre est fermée (pas laissée ouverte)."""
    found = game.wait_any(("wall_confirm", "bh_okay", "upgrade_confirm"), timeout=5)
    if found:
        m = found[1]
    else:
        m = discounted_upgrade_button(game) if game.find("close_x", threshold=CLOSE_X_MIN) else None
        if m:
            log("🏷️ Murs : prix réduit → bouton Upgrade vert")
    if not m:
        from ..notify import save_error_shot
        save_error_shot("murs_confirmation", vision.to_jpeg(game.grab(), max_w=1920, quality=90))
        x = game.find("close_x", threshold=CLOSE_X_MIN)
        if x:
            game.click_match(x)
            game.sleep(0.5)
        return False
    game.click_match(m)
    game.sleep(0.6)
    if game.find("need_more"):
        x = game.find("close_x", threshold=CLOSE_X_MIN)
        if x:
            game.click_match(x)
        return False
    return True


def upgrade_walls(game: Game, cfg: LiveConfig, ws: WallState, cost_key: str = "wall_cost",
                  budget: dict | None = None, stat_mode: str | None = None) -> int:
    """Améliore des murs tant que le budget (loot farmé, ou réserves BH) le permet. Retourne le nombre."""
    cost = parse_amount(cfg.text(cost_key))
    if not cost:
        log("❌ Murs : « Wall cost » invalide")
        return 0
    budget = budget if budget is not None else game.state.accum
    panel = BuildPanel(game)
    total = 0
    if not panel.open():
        return 0
    try:
        panel.to_top()
        at_top = True
        while True:
            game.state.check()
            resource = "gold" if budget.get("gold", 0) >= cost else ("elixir" if budget.get("elixir", 0) >= cost else None)
            if not resource:
                log("⛔ Murs : plus assez de loot farmé")
                break
            found = find_wall(panel, cost)
            if not found and not at_top:
                # rouvert après un achat : le panneau garde sa position, souvent SOUS la ligne du mur
                panel.to_top()
                found = find_wall(panel, cost)
            at_top = False
            if not found:
                ws.wait_battles = WALL_RECHECK_EVERY
                log(f"🧱 Aucun mur à {cost:,} dans la liste → nouvel essai dans {WALL_RECHECK_EVERY} combats"
                    .replace(",", " "))
                break
            y, _price = found
            panel.click_row(y)
            wanted = max(1, budget[resource] // cost) if wall_fill_target(cfg) else 1
            n = select_more(game, min(wanted, 30)) if wanted > 1 else 1
            btn = upgrade_button_for(game, resource)
            other = "elixir" if resource == "gold" else "gold"
            if not btn and budget.get(other, 0) >= cost * n:
                # le budget estimé peut dépasser la réserve réelle : prix en rouge (pas de chiffres
                # blancs) → on tente l'autre ressource
                btn = upgrade_button_for(game, other)
                if btn:
                    budget[resource] = 0
                    resource = other
            if not btn:
                from ..notify import save_error_shot
                save_error_shot("murs_bouton_upgrade", vision.to_jpeg(game.grab(), max_w=1920, quality=90))
                log("⚠️ Murs : bouton Upgrade introuvable")
                break
            game.click_match(btn)
            if not confirm(game):
                log("⚠️ Murs : confirmation impossible")
                break
            total += n
            budget[resource] = max(0, budget[resource] - cost * n)
            game.state.add("walls", n, stat_mode)
            log(f"🧱 {n} mur(s) amélioré(s) à l'{'or' if resource == 'gold' else 'élixir'}")
            if not panel.open():
                break
    finally:
        panel.close()
    return total
