"""Déconnexions : popup « Disconnected due to inactivity » / « Another device connected… ».

Un thread de surveillance (AFK checker) regarde la zone de la popup pendant que le bot tourne :
popup vue → alerte Discord → clic RELOAD (re-cliqué si la popup revient) → attente du village →
le bot reprend dans le même mode. « Another device » : pause plus longue (quelqu'un joue)."""
from __future__ import annotations

import threading
import time

from .. import layout, vision
from ..game import Game
from ..logger import log

RECO_MESSAGES = {"reco_inactivity": "déconnecté pour inactivité",
                 "reco_another_device": "un autre appareil s'est connecté à ce village",
                 "afk": "popup de déconnexion (motif illisible)"}
# Popup Android : la taille du texte ne suit pas celle de la fenêtre (mesuré GPG 2026-11, fenêtre
# 1765x993 : texte à l'échelle 1,04, RELOAD GAME à 0,98) → pas fin sur une large plage.
RECO_SCALES = tuple(round(0.80 + 0.02 * i, 2) for i in range(31))
ANOTHER_DEVICE_PAUSE = (300, 420)   # secondes


def popup_visible(screen) -> bool:
    """Cadre sombre de la popup au centre + village caché."""
    zone, _, _ = vision.crop(screen, layout.RECO_BOX)
    if zone.size == 0:
        return False
    dark = (zone.max(axis=2) < 90).mean()
    return dark > 0.55


def reload_button(game: Game, screen):
    """Bouton « RELOAD GAME » de la popup (template afk), sinon None."""
    return game.find("afk", screen, layout.RECO_SEARCH_BOX, 0.8, RECO_SCALES)


def reason(game: Game, screen) -> str | None:
    """Motif de la popup ; « afk » si seul le bouton RELOAD GAME est reconnu."""
    for key in ("reco_inactivity", "reco_another_device"):
        if game.find(key, screen, layout.RECO_SEARCH_BOX, 0.78, RECO_SCALES):
            return key
    return "afk" if reload_button(game, screen) else None


def reload_game(game: Game, timeout: float = 90) -> bool:
    """RELOAD puis attente du village ; si la popup revient (réseau coupé), on reclique."""
    last_click = 0.0
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        screen = game.grab()
        if game.battle_button_visible(screen) and not popup_visible(screen):
            return True
        if popup_visible(screen) and time.monotonic() - last_click > 8:
            m = reload_button(game, screen)
            if m:
                game.click_match(m)
            else:
                game.click(*layout.RECO_RELOAD, jitter=12)
            last_click = time.monotonic()
            log("🔌 RELOAD")
        game.dismiss_common_popups(screen)
        game.state.sleep(1.5)
    return False


def handle_popup_if_any(game: Game, screen) -> bool:
    if popup_visible(screen) and reason(game, screen):
        return reload_game(game)
    return False


def reload_if_disconnected(game: Game) -> None:
    screen = game.grab()
    if popup_visible(screen):
        reload_game(game)


class AfkChecker:
    """Surveille les popups de déconnexion pendant que le bot tourne et met le bot en reconnexion."""

    def __init__(self, game: Game, on_disconnect):
        self.game = game
        self.on_disconnect = on_disconnect      # callback(reason_key)
        self.thread = threading.Thread(target=self._loop, daemon=True, name="afk")

    def start(self) -> None:
        self.thread.start()

    def _loop(self) -> None:
        st = self.game.state
        while not st.stop_event.is_set():
            time.sleep(3)
            if st.reconnecting or st.status != "farming":
                continue
            screen = self.game.grab_now()
            if screen is None or not popup_visible(screen):
                continue
            key = reason(self.game, screen)
            if key:
                log(f"🔌 Déconnexion : {RECO_MESSAGES[key]}")
                st.reconnecting = True
                try:
                    self.on_disconnect(key)
                except Exception as exc:
                    log(f"⚠️ Reconnexion : {exc}")
