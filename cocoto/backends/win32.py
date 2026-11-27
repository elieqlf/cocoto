"""Mode arrière-plan (Windows) : la fenêtre de Clash of Clans (Google Play Games) est capturée avec
PrintWindow et reçoit des messages souris (PostMessage), sans toucher à ta souris ni à ton écran.

Observé dans CoCoBot : la fenêtre titrée « Clash of Clans » est de classe CROSVM_1 et prend les clics ;
chez certains joueurs le titre est porté par une fenêtre WPF et c'est un enfant qui reçoit les clics.
Un jeu lancé en administrateur ignore les messages d'un programme non administrateur."""
from __future__ import annotations

import ctypes
import time

import cv2
import numpy as np

from . import VH, VW, Backend

WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP, WM_MOUSEWHEEL = 0x200, 0x201, 0x202, 0x20A
WM_KEYDOWN, WM_KEYUP, WM_ACTIVATE = 0x100, 0x101, 0x006
MK_LBUTTON = 0x0001
PW_RENDERFULLCONTENT = 0x2
VK = {"esc": 0x1B, "escape": 0x1B, "enter": 0x0D, "space": 0x20, "tab": 0x09}
GAME_TITLE = "Clash of Clans"
GAME_URI = "googleplaygames://launch/?id=com.supercell.clashofclans&lid=1&pid=1"


def _api():
    if not hasattr(ctypes, "windll"):
        raise RuntimeError("Le mode arrière-plan n'existe que sous Windows.")
    from ctypes import wintypes
    return ctypes.windll.user32, ctypes.windll.gdi32, ctypes.windll.kernel32, wintypes


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32), ("biHeight", ctypes.c_int32),
                ("biPlanes", ctypes.c_uint16), ("biBitCount", ctypes.c_uint16),
                ("biCompression", ctypes.c_uint32), ("biSizeImage", ctypes.c_uint32),
                ("biXPelsPerMeter", ctypes.c_int32), ("biYPelsPerMeter", ctypes.c_int32),
                ("biClrUsed", ctypes.c_uint32), ("biClrImportant", ctypes.c_uint32)]


def find_game_window() -> int | None:
    user32, _g, _k, wintypes = _api()
    found = []
    proto = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        if buf.value.startswith(GAME_TITLE) and user32.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True

    user32.EnumWindows(proto(cb), 0)
    return found[0] if found else None


def window_class(hwnd: int) -> str:
    user32, *_ = _api()
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def client_size(hwnd: int) -> tuple[int, int]:
    user32, _g, _k, wintypes = _api()
    r = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    return r.right - r.left, r.bottom - r.top


def process_elevated(hwnd: int) -> bool | None:
    """True si le programme de la fenêtre tourne en administrateur, None si inconnu."""
    user32, _g, k32, wintypes = _api()
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = k32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return True
    try:
        tok = wintypes.HANDLE()
        if not ctypes.windll.advapi32.OpenProcessToken(h, 0x0008, ctypes.byref(tok)):
            return True
        elev, size = wintypes.DWORD(), wintypes.DWORD()
        ok = ctypes.windll.advapi32.GetTokenInformation(tok, 20, ctypes.byref(elev), 4, ctypes.byref(size))
        k32.CloseHandle(tok)
        return bool(elev.value) if ok else None
    finally:
        k32.CloseHandle(h)


def self_elevated() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def find_input_window(hwnd: int) -> int:
    """Fenêtre qui reçoit les clics : la CROSVM_1 si c'est elle, sinon un enfant de cette classe."""
    if window_class(hwnd).startswith("CROSVM"):
        return hwnd
    user32, _g, _k, wintypes = _api()
    found = []
    proto = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def child(h, _):
        if window_class(h).startswith("CROSVM"):
            found.append(h)
        return True

    user32.EnumChildWindows(hwnd, proto(child), 0)
    return found[0] if found else hwnd


class WindowBackend(Backend):
    name = "window"

    def __init__(self, hwnd: int):
        self.hwnd = hwnd
        self.input_hwnd = find_input_window(hwnd)
        self.pos = (VW // 2, VH // 2)
        self.button_down = False

    @classmethod
    def find(cls) -> "WindowBackend":
        hwnd = find_game_window()
        if not hwnd:
            raise RuntimeError("Fenêtre « Clash of Clans » introuvable (Google Play Games ouvert ?).")
        return cls(hwnd)

    def ratio_ok(self) -> bool:
        w, h = client_size(self.hwnd)
        return h > 0 and abs(w / h - 16 / 9) < 0.02

    # ---------------------------------------------------------------- capture
    def grab(self):
        user32, gdi32, _k, _w = _api()
        if not user32.IsWindow(self.hwnd):
            hwnd = find_game_window()
            if not hwnd:
                return None
            self.hwnd, self.input_hwnd = hwnd, find_input_window(hwnd)
        if user32.IsIconic(self.hwnd):
            return None
        w, h = client_size(self.hwnd)
        if w <= 0 or h <= 0:
            return None
        hdc = user32.GetDC(self.hwnd)
        mem = gdi32.CreateCompatibleDC(hdc)
        bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
        old = gdi32.SelectObject(mem, bmp)
        try:
            user32.PrintWindow(self.hwnd, mem, PW_RENDERFULLCONTENT | 0x1)  # | PW_CLIENTONLY
            bmi = BITMAPINFOHEADER()
            bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.biWidth, bmi.biHeight, bmi.biPlanes, bmi.biBitCount = w, -h, 1, 32
            buf = ctypes.create_string_buffer(w * h * 4)
            lines = gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bmi), 0)
            if lines != h:
                return None
            img = np.frombuffer(buf, np.uint8).reshape(h, w, 4)[:, :, :3]
        finally:
            gdi32.SelectObject(mem, old)
            gdi32.DeleteObject(bmp)
            gdi32.DeleteDC(mem)
            user32.ReleaseDC(self.hwnd, hdc)
        if img.max() == 0:      # fenêtre noire (en cours de chargement / masquée par le GPU)
            return None
        if (w, h) != (VW, VH):
            img = cv2.resize(img, (VW, VH), interpolation=cv2.INTER_AREA)
        return np.ascontiguousarray(img)

    # ---------------------------------------------------------------- entrées
    def _client_point(self, x, y):
        w, h = client_size(self.input_hwnd)
        return int(x * w / VW), int(y * h / VH)

    def _post(self, msg, wparam, x, y):
        user32, *_ = _api()
        px, py = self._client_point(x, y)
        lparam = (py & 0xFFFF) << 16 | (px & 0xFFFF)
        user32.PostMessageW(self.input_hwnd, msg, wparam, lparam)

    def move(self, x, y, duration=0.0):
        x0, y0 = self.pos
        steps = max(1, int(duration / 0.016))
        for i in range(1, steps + 1):
            xi, yi = int(x0 + (x - x0) * i / steps), int(y0 + (y - y0) * i / steps)
            self._post(WM_MOUSEMOVE, MK_LBUTTON if self.button_down else 0, xi, yi)
            if steps > 1:
                time.sleep(duration / steps)
        self.pos = (x, y)

    def mouse_down(self, x, y):
        self.move(x, y)
        self.button_down = True
        self._post(WM_LBUTTONDOWN, MK_LBUTTON, x, y)

    def mouse_up(self, x, y):
        self.button_down = False
        self._post(WM_LBUTTONUP, 0, x, y)

    def scroll(self, clicks, x, y):
        user32, _g, _k, wintypes = _api()
        self.move(x, y)
        px, py = self._client_point(x, y)
        pt = wintypes.POINT(px, py)
        user32.ClientToScreen(self.input_hwnd, ctypes.byref(pt))   # WM_MOUSEWHEEL : coordonnées écran
        # Un message par cran : le jeu traite un WM_MOUSEWHEEL comme UN cran quel que soit son delta
        # (mesuré GPG 2026-11 : 5, 10 ou 15 crans d'un coup → toujours ~175 px).
        delta = (120 if clicks > 0 else -120) & 0xFFFF
        lparam = (pt.y & 0xFFFF) << 16 | (pt.x & 0xFFFF)
        for i in range(abs(int(clicks))):
            if i:
                time.sleep(0.05)
            user32.PostMessageW(self.input_hwnd, WM_MOUSEWHEEL, delta << 16, lparam)

    def key(self, name):
        user32, *_ = _api()
        vk = VK.get(name.lower(), ord(name.upper()[0]) if name else 0)
        user32.PostMessageW(self.input_hwnd, WM_KEYDOWN, vk, 0)
        time.sleep(0.06)
        user32.PostMessageW(self.input_hwnd, WM_KEYUP, vk, 0xC0000001)

    def wake(self):
        """Jeu rouvert sans le focus : il ignore les clics tant qu'il n'a pas reçu WM_ACTIVATE."""
        user32, *_ = _api()
        user32.PostMessageW(self.input_hwnd, WM_ACTIVATE, 1, 0)

    # ---------------------------------------------------------------- jeu
    def open_game(self):
        import os
        os.startfile(GAME_URI)  # type: ignore[attr-defined]

    def close_game(self):
        user32, *_ = _api()
        user32.PostMessageW(self.hwnd, 0x0010, 0, 0)  # WM_CLOSE

    def describe(self):
        w, h = client_size(self.hwnd)
        return f"fenêtre {w}x{h} ({window_class(self.input_hwnd)})"
