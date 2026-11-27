"""Mode normal : capture de l'écran principal et vraie souris (pyautogui).

Le jeu doit être en plein écran sur un écran 16:9 ; l'image est ramenée en 1920x1080 et les clics
sont remis à l'échelle de l'écran réel."""
from __future__ import annotations

import time

import cv2
import numpy as np

from . import VH, VW, Backend


class ScreenBackend(Backend):
    name = "screen"

    def __init__(self):
        import mss  # type: ignore
        self._mss = mss.mss()
        mon = self._mss.monitors[1]
        self.left, self.top = mon["left"], mon["top"]
        self.width, self.height = mon["width"], mon["height"]
        self.sx, self.sy = self.width / VW, self.height / VH
        self._pg = None

    @property
    def pg(self):
        if self._pg is None:
            import pyautogui  # type: ignore
            pyautogui.FAILSAFE = True   # souris dans un coin = arrêt d'urgence
            pyautogui.PAUSE = 0
            self._pg = pyautogui
        return self._pg

    def ratio_ok(self) -> bool:
        return abs(self.width / self.height - 16 / 9) < 0.02

    def _to_screen(self, x, y):
        return int(self.left + x * self.sx), int(self.top + y * self.sy)

    def grab(self):
        shot = self._mss.grab(self._mss.monitors[1])
        img = np.asarray(shot)[:, :, :3]
        if img.shape[1] != VW or img.shape[0] != VH:
            img = cv2.resize(img, (VW, VH), interpolation=cv2.INTER_AREA)
        return np.ascontiguousarray(img)

    def move(self, x, y, duration=0.0):
        sx, sy = self._to_screen(x, y)
        self.pg.moveTo(sx, sy, duration=duration)

    def mouse_down(self, x, y):
        sx, sy = self._to_screen(x, y)
        self.pg.mouseDown(sx, sy)

    def mouse_up(self, x, y):
        sx, sy = self._to_screen(x, y)
        self.pg.mouseUp(sx, sy)

    def scroll(self, clicks, x, y):
        self.move(x, y)
        self.pg.scroll(int(clicks * 120))

    def key(self, name):
        self.pg.keyDown(name)
        time.sleep(0.06)
        self.pg.keyUp(name)

    def describe(self):
        return f"écran {self.width}x{self.height}"
