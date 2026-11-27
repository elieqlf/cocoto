"""Façade utilisée par toutes les fonctionnalités : capture, templates, attentes, clics humanisés."""
from __future__ import annotations

import random
import threading
import time

import numpy as np

from . import humanize, layout, vision
from .backends import Backend
from .logger import log
from .state import BotState, BotStopped
from .vision import Match, Templates


class Game:
    def __init__(self, backend: Backend, state: BotState, templates: Templates | None = None):
        self.backend = backend
        self.state = state
        self.tpl = templates or Templates()
        self.click_lock = threading.Lock()
        self.last_screen: np.ndarray | None = None
        self._missing_since: float | None = None

    # ---------------------------------------------------------------- capture
    def grab(self, wait: bool = True) -> np.ndarray:
        """Capture du jeu. Jeu fermé / réduit : attend qu'il revienne tant que le bot tourne."""
        while True:
            img = self.backend.grab()
            if img is not None:
                self.last_screen = img
                self._missing_since = None
                return img
            if not wait:
                raise RuntimeError("capture du jeu impossible")
            if self._missing_since is None:
                self._missing_since = time.monotonic()
                log("⚠️ Jeu introuvable ou réduit : le bot attend qu'il revienne.")
            self.state.sleep(1.0)

    def grab_now(self) -> np.ndarray | None:
        try:
            return self.backend.grab()
        except Exception:
            return None

    # ---------------------------------------------------------------- templates
    def find(self, name: str, screen: np.ndarray | None = None, box=None,
             threshold: float | None = None, scales=None, gray: bool = False) -> Match | None:
        screen = self.grab() if screen is None else screen
        thr = self.tpl.threshold(name) if threshold is None else threshold
        best = self.best(name, screen, box, scales, gray)
        return best if best and best.score >= thr else None

    def best(self, name: str, screen: np.ndarray | None = None, box=None, scales=None,
             gray: bool = False) -> Match | None:
        screen = self.grab() if screen is None else screen
        best = None
        for s in (scales or (1.0,)):
            tpl = self.tpl.get(name, s)
            m = vision.match_image(screen, tpl, box, gray=gray)
            if m and (best is None or m.score > best.score):
                best = m
        return best

    def score(self, name: str, screen=None, box=None, scales=None) -> float:
        m = self.best(name, screen, box, scales)
        return m.score if m else 0.0

    def wait(self, name: str, timeout: float = 10.0, box=None, threshold: float | None = None,
             scales=None, stable: bool = False, interval: float = 0.25, on_screen=None) -> Match | None:
        """Attend le template. stable=True : vu au même endroit sur 2 captures de suite
        (un panneau qui glisse en s'ouvrant matche déjà, le clic tomberait à côté)."""
        end = time.monotonic() + timeout
        last: Match | None = None
        while True:
            self.state.check()
            screen = self.grab()
            if on_screen:
                on_screen(screen)
            m = self.find(name, screen, box, threshold, scales)
            if m:
                if not stable or (last and abs(last.x - m.x) <= 3 and abs(last.y - m.y) <= 3):
                    return m
                last = m
            else:
                last = None
            if time.monotonic() >= end:
                return None
            self.state.sleep(interval)

    def wait_any(self, names, timeout: float = 10.0, threshold: float | None = None,
                 interval: float = 0.3, on_screen=None, boxes=None) -> tuple[str, Match] | None:
        end = time.monotonic() + timeout
        while True:
            self.state.check()
            screen = self.grab()
            if on_screen:
                r = on_screen(screen)
                if r == "stop_wait":
                    return None
            for name in names:
                box = (boxes or {}).get(name)
                m = self.find(name, screen, box, threshold)
                if m:
                    return name, m
            if time.monotonic() >= end:
                return None
            self.state.sleep(interval)

    def wait_gone(self, name: str, timeout: float = 5.0, box=None, threshold: float | None = None) -> bool:
        """Template absent sur 2 captures de suite (une capture ratée ne suffit pas)."""
        end = time.monotonic() + timeout
        misses = 0
        while time.monotonic() < end:
            if self.find(name, None, box, threshold):
                misses = 0
            else:
                misses += 1
                if misses >= 2:
                    return True
            self.state.sleep(0.25)
        return False

    def wait_still(self, box, timeout: float = 3.0, tol: float = 1.5) -> np.ndarray:
        """Capture une fois la zone immobile (listes qui glissent encore après un scroll)."""
        prev = None
        end = time.monotonic() + timeout
        while True:
            screen = self.grab()
            zone, _, _ = vision.crop(screen, box)
            if prev is not None and vision.same_image(prev, zone, tol):
                return screen
            if time.monotonic() >= end:
                return screen
            prev = zone.copy()
            self.state.sleep(0.2)

    # ---------------------------------------------------------------- entrées
    def click(self, x: int, y: int, jitter: int = 6, delay: tuple[float, float] = (0.08, 0.2)) -> None:
        self.state.check()
        x2 = max(0, min(layout.W - 1, x + humanize.offset(jitter)))
        y2 = max(0, min(layout.H - 1, y + humanize.offset(jitter)))
        with self.click_lock:
            self.backend.move(x2, y2, duration=random.uniform(0.03, 0.12))
            self.backend.click(x2, y2, hold=random.uniform(0.04, 0.09))
        time.sleep(random.uniform(*delay))

    def click_box(self, box, margin: float = 0.2) -> None:
        x, y = humanize.point_in_box(box, margin)
        self.click(x, y, jitter=0)

    def click_match(self, m: Match, jitter: int = 4) -> None:
        self.click(m.x, m.y, jitter=min(jitter, m.w // 4, m.h // 4))

    def tap(self, name: str, timeout: float = 5.0, box=None, threshold: float | None = None,
            stable: bool = True) -> bool:
        m = self.wait(name, timeout, box, threshold, stable=stable)
        if m:
            self.click_match(m)
            return True
        return False

    def drag(self, x1, y1, x2, y2, duration: float = 0.4) -> None:
        self.state.check()
        with self.click_lock:
            self.backend.drag(x1, y1, x2, y2, duration=humanize.duration(duration))

    def scroll(self, clicks: int, x: int, y: int) -> None:
        self.state.check()
        with self.click_lock:
            # le jeu ignore la molette tant qu'il n'a pas vu la souris BOUGER au-dessus du panneau
            self.backend.move(x + random.randint(-30, 30), y + random.randint(-30, 30), 0.1)
            self.backend.move(x, y, 0.05)
            self.backend.scroll(clicks, x, y)

    def zoom_out(self, times: int | None = None) -> None:
        cx, cy = layout.SCREEN_CENTER
        with self.click_lock:
            self.backend.move(cx + random.randint(-30, 30), cy + random.randint(-30, 30), 0.1)
            self.backend.zoom_out(cx, cy, times or random.randint(3, 5))
        self.sleep(0.4)

    def key(self, name: str) -> None:
        with self.click_lock:
            self.backend.key(name)

    def sleep(self, seconds: float) -> None:
        self.state.sleep(seconds * random.uniform(1.0, 1.25))

    def close_window(self) -> None:
        """Ferme une fenêtre du jeu par la touche Échap (ou un clic dans le vide)."""
        self.key("esc")
        self.sleep(0.4)

    # ---------------------------------------------------------------- états de l'écran
    def battle_button_visible(self, screen=None) -> bool:
        screen = self.grab() if screen is None else screen
        return vision.yellow_ratio(screen, layout.BATTLE_BUTTON_BOX) > 0.25

    def village(self, screen=None) -> str | None:
        """'TH' / 'BH' d'après l'icône du bouton Battle (épée / haches)."""
        screen = self.grab() if screen is None else screen
        th = self.score("village_th", screen, layout.VILLAGE_ICON_BOX, (0.9, 1.0, 1.1))
        bh = self.score("village_bh", screen, layout.VILLAGE_ICON_BOX, (0.9, 1.0, 1.1))
        if max(th, bh) < 0.6:
            return None
        return "TH" if th >= bh else "BH"

    def panel_open(self, screen=None) -> bool:
        """Panneau Build ouvert = son bord gauche noir (x≈1402) sur toute la hauteur."""
        screen = self.grab() if screen is None else screen
        x1, x2 = layout.UPGRADE_PANEL_EDGE_X
        y1, y2 = layout.UPGRADE_PANEL_Y
        band = screen[y1:y2, x1:x2]
        return band.size > 0 and float(band.max(axis=2).mean()) < 25

    def wait_village(self, timeout: float = 30.0) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.state.check()
            screen = self.grab()
            if self.battle_button_visible(screen):
                return True
            self.dismiss_common_popups(screen)
            self.state.sleep(0.5)
        return False

    def dismiss_common_popups(self, screen) -> bool:
        """Popups qui cachent le village : récompense du jour, Welcome Back, Star Bonus…"""
        for key in ("welcome_okay", "bh_okay", "star_bonus"):
            m = self.find(key, screen)
            if m:
                log(f"🪟 Popup fermée ({key})")
                self.click_match(m)
                return True
        m = self.find("daily_claim", screen)
        if m:
            self.click_match(m)
            self.sleep(1.0)
            self.click(*layout.DAILY_CLOSE)
            return True
        m = self.find("close_x", screen)
        if m and not self.battle_button_visible(screen):
            self.click_match(m)
            return True
        return False


__all__ = ["Game", "BotStopped"]
