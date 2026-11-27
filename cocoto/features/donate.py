"""Dons au clan : au START puis quand le bouton du chat affiche une pastille rouge, le bot ouvre le
chat et remplit les demandes de troupes / sorts des coéquipiers.

- demande précise (ligne « Requested: ») : seulement ce qui est demandé, reconnu par ses icônes ;
- demande libre (aucune troupe choisie) : les unités choisies dans « Free requests », par priorité
  (templates img/donate/tNN = troupes, sNN = sorts) ; rien de choisi = demande ignorée."""
from __future__ import annotations

import cv2

from .. import layout, vision
from ..game import Game
from ..logger import log

CHAT_BOX = (0, 80, 900, 1060)
DONATE_WINDOW_BOX = (700, 0, 1920, 1080)
UNIT_SCALES = (0.85, 0.95, 1.0, 1.05)


def chat_badge_visible(screen) -> bool:
    return vision.red_ratio(screen, layout.CHAT_BADGE_BOX) > 0.06


def unit_templates(game: Game, chosen: list[str]) -> list[str]:
    """Noms de templates (« donate/t03 ») des unités choisies, dans l'ordre de priorité."""
    return [f"donate/{u}" for u in chosen if game.tpl.exists(f"donate/{u}")]


def requested_icons(screen, button) -> list:
    """Icônes de la ligne « Requested: » au-dessus du bouton Donate : images découpées."""
    x1, y1 = max(0, button.x - 420), max(0, button.y - 95)
    zone = screen[y1:button.y - 30, x1:button.x + 60]
    if zone.size == 0:
        return []
    h = cv2.cvtColor(zone, cv2.COLOR_BGR2HSV)
    colored = (h[:, :, 1] > 80).mean(axis=0) > 0.25
    icons, start = [], None
    for x, on in enumerate(list(colored) + [False]):
        if on and start is None:
            start = x
        elif not on and start is not None:
            if x - start >= 25:
                icons.append(zone[:, start:x].copy())
            start = None
    return icons


def give(game: Game, m, clicks: int = 1) -> int:
    n = 0
    for _ in range(clicks):
        game.click_match(m, jitter=6)
        n += 1
        game.state.sleep(0.12)
    return n


def fill_window(game: Game, icons: list, free_units: list[str]) -> int:
    """Remplit la fenêtre de dons ouverte. Retourne le nombre de clics."""
    clicks = 0
    if not game.wait("donate_title", 4, stable=True):
        return 0
    for _ in range(12):
        screen = game.grab()
        if not game.find("donate_title", screen):
            break                     # fenêtre refermée seule : demande remplie
        target = None
        if icons:
            for icon in icons:
                for s in UNIT_SCALES:
                    tpl = cv2.resize(icon, None, fx=s * 1.6, fy=s * 1.6)
                    m = vision.match_image(screen, tpl, DONATE_WINDOW_BOX)
                    if m and m.score > 0.72 and vision.gray_ratio(screen, m.box, 35) < 0.5:
                        target = m
                        break
                if target:
                    break
        else:
            for name in unit_templates(game, free_units):
                m = game.find(name, screen, DONATE_WINDOW_BOX, 0.8, UNIT_SCALES)
                if m and vision.gray_ratio(screen, m.box, 35) < 0.5:   # carte grise = plus de place
                    target = m
                    break
        if not target:
            break
        clicks += give(game, target, 5)
    if game.find("donate_title"):
        game.close_window()
    return clicks


def process_donations(game: Game, free_units: list[str]) -> int:
    """Ouvre le chat, remplit les demandes visibles puis referme le chat."""
    game.click(*layout.CHAT_OPEN_BUTTON)
    if not game.wait("chat_close_tab", 5, stable=True):
        log("💬 Chat pas ouvert")
        return 0
    total = 0
    done_ys: list[int] = []
    for _ in range(6):
        screen = game.grab()
        buttons = vision.match_all(screen, game.tpl.get("donate_button"), 0.82, CHAT_BOX, min_dist=30)
        buttons = [b for b in buttons if all(abs(b.y - y) > 25 for y in done_ys)]
        if not buttons:
            break
        b = buttons[0]
        done_ys.append(b.y)
        precise = game.find("donate_requested", screen, (b.x - 450, b.y - 110, b.x + 80, b.y - 20), 0.8)
        icons = requested_icons(screen, b) if precise else []
        if not precise and not free_units:
            log("💬 Demande libre ignorée (aucune unité choisie)")
            continue
        game.click_match(b)
        n = fill_window(game, icons, free_units)
        total += n
        log(f"💝 Don : {n} clic(s) ({'demande précise' if precise else 'demande libre'})")
    close = game.find("chat_close_tab")
    if close:
        game.click_match(close)
    game.sleep(0.5)
    return total
