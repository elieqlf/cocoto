"""Moteurs d'entrée/capture. Le bot voit toujours un écran virtuel 1920x1080 (repère de layout.py).

- screen : capture de l'écran + vraie souris (jeu en plein écran, Google Play Games) ;
- window : fenêtre du jeu capturée et cliquée en arrière-plan (Windows : PrintWindow + PostMessage) ;
- adb    : émulateur Android (MuMu, BlueStacks, LDPlayer…) par ADB : screencap + input.
"""
from __future__ import annotations

import time

import numpy as np

VW, VH = 1920, 1080


class Backend:
    name = "base"
    supports_pinch = False

    # -- capture
    def grab(self) -> np.ndarray | None:
        """Image BGR 1920x1080, ou None (jeu fermé / réduit)."""
        raise NotImplementedError

    # -- entrées (coordonnées virtuelles 1920x1080)
    def mouse_down(self, x: int, y: int) -> None:
        raise NotImplementedError

    def mouse_up(self, x: int, y: int) -> None:
        raise NotImplementedError

    def move(self, x: int, y: int, duration: float = 0.0) -> None:
        raise NotImplementedError

    def click(self, x: int, y: int, hold: float = 0.06) -> None:
        self.move(x, y)
        self.mouse_down(x, y)
        time.sleep(hold)
        self.mouse_up(x, y)

    def drag(self, x1: int, y1: int, x2: int, y2: int, duration: float = 0.4,
             hold_end: float = 0.15) -> None:
        """Glissement ; la souris s'arrête avant le relâché (pas d'inertie)."""
        self.move(x1, y1)
        self.mouse_down(x1, y1)
        self.move(x2, y2, duration)
        time.sleep(hold_end)
        self.mouse_up(x2, y2)

    def scroll(self, clicks: int, x: int, y: int) -> None:
        """Molette : négatif = vers le bas (dézoom sur la carte)."""
        raise NotImplementedError

    def zoom_out(self, x: int = 960, y: int = 540, times: int = 4) -> None:
        for _ in range(times):
            self.scroll(-5, x, y)
            time.sleep(0.12)

    def key(self, name: str) -> None:
        raise NotImplementedError

    # -- cycle de vie du jeu
    def is_ready(self) -> bool:
        return self.grab() is not None

    def open_game(self) -> None:
        pass

    def close_game(self) -> None:
        pass

    def wake(self) -> None:
        pass

    def describe(self) -> str:
        return self.name


def make_backend(kind: str, settings) -> Backend:
    if kind == "window":
        from .win32 import WindowBackend
        return WindowBackend.find()
    if kind == "adb":
        from ..paths import INSTANCE
        from .adb import AdbBackend
        return AdbBackend(settings.get("adb_device") or "", settings.get("adb_path") or "", INSTANCE)
    from .screen import ScreenBackend
    return ScreenBackend()
