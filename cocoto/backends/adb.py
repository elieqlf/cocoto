"""Mode émulateur (MuMu Player 12, BlueStacks, LDPlayer… ou téléphone) par ADB.

Capture : `adb exec-out screencap` (image brute RGBA). Entrées : `input motionevent` / `input swipe`
dans un shell ADB gardé ouvert ; dézoom : pincement à 2 doigts écrit avec `sendevent` sur l'écran
tactile virtuel (trouvé par `getevent -pl`), comme le faisait CoCoBot.

Écran conseillé : 1920x1080 (16:9) → aucune conversion. En 16:10 (ex. MuMu 1728x1080, le format
exigé par CoCoBot), l'image est recomposée dans le repère 1920x1080 : les coins de l'interface
restent collés à leur bord, le centre (le village) est centré."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
import time

import cv2
import numpy as np

from . import VH, VW, Backend
from ..logger import log

PACKAGE = "com.supercell.clashofclans"
DONE = "__cocoto_done__"
REMOTE_DIR = "/data/local/tmp/cocoto"
MUMU_ADB_PATHS = (
    r"C:\Program Files\Netease\MuMuPlayer\nx_main\adb.exe",
    r"C:\Program Files\Netease\MuMuPlayer-12.0\shell\adb.exe",
    r"C:\Program Files\Netease\MuMu Player 12\shell\adb.exe",
)
MUMU_FIRST_PORT, MUMU_PORT_STEP = 16384, 32
KEYCODES = {"esc": 111, "escape": 111, "enter": 66, "back": 4, "space": 62}

# zones de l'écran virtuel collées à un bord (repère 1920x1080) quand l'écran n'est pas en 16:9
ANCHORED_REGIONS = (
    ((0, 0, 560, 260), "left"), ((0, 260, 200, 660), "left"), ((0, 820, 200, 1080), "left"),
    ((1360, 0, 1920, 200), "right"), ((1740, 200, 1920, 740), "right"),
    ((1710, 740, 1920, 1080), "right"),
)


def find_adb(configured: str = "") -> str | None:
    for p in (configured, *MUMU_ADB_PATHS):
        if p and os.path.exists(p):
            return p
    return shutil.which("adb")


def default_device(instance: int = 1) -> str:
    return f"127.0.0.1:{MUMU_FIRST_PORT + (instance - 1) * MUMU_PORT_STEP}"


class FrameMap:
    """Conversion image Android (W x H) ↔ repère virtuel 1920x1080."""

    def __init__(self, w: int, h: int, regions=ANCHORED_REGIONS):
        self.w, self.h = w, h
        self.s = VH / h
        self.ws = int(round(w * self.s))
        self.identity_ratio = abs(self.ws - VW) <= 2
        self.regions = regions
        self.center_dx = (VW - self.ws) / 2

    def _dx(self, x, y) -> float:
        if self.identity_ratio:
            return 0.0
        for (x1, y1, x2, y2), anchor in self.regions:
            if x1 <= x < x2 and y1 <= y < y2:
                return 0.0 if anchor == "left" else float(VW - self.ws)
        return self.center_dx

    def to_device(self, x: float, y: float) -> tuple[int, int]:
        if self.identity_ratio:
            return int(x * self.w / VW), int(y * self.h / VH)
        dx = self._dx(x, y)
        px = min(self.w - 1, max(0, int((x - dx) / self.s)))
        return px, min(self.h - 1, max(0, int(y / self.s)))

    def compose(self, img: np.ndarray) -> np.ndarray:
        if self.identity_ratio:
            if img.shape[1] == VW and img.shape[0] == VH:
                return img
            return cv2.resize(img, (VW, VH), interpolation=cv2.INTER_AREA)
        scaled = cv2.resize(img, (self.ws, VH), interpolation=cv2.INTER_AREA) if self.s != 1 else img
        out = np.zeros((VH, VW, 3), np.uint8)
        if self.ws <= VW:
            cx = int(self.center_dx)
            out[:, cx:cx + self.ws] = scaled
        else:
            cx = int(-self.center_dx)
            out[:] = scaled[:, cx:cx + VW]
        for (x1, y1, x2, y2), anchor in self.regions:
            dx = 0 if anchor == "left" else VW - self.ws
            sx1, sx2 = x1 - dx, x2 - dx
            if sx1 < 0 or sx2 > self.ws:
                continue
            out[y1:y2, x1:x2] = scaled[y1:y2, sx1:sx2]
        return out


class AdbBackend(Backend):
    name = "adb"
    supports_pinch = True

    def __init__(self, device: str = "", adb_path: str = "", instance: int = 1):
        self.adb = find_adb(adb_path)
        if not self.adb:
            raise RuntimeError("adb introuvable : installe Android platform-tools ou indique adb_path.")
        self.device = device or default_device(instance)
        self.lock = threading.RLock()
        self.shell: subprocess.Popen | None = None
        self.map: FrameMap | None = None
        self.touch_dev: str | None = None
        self.touch_max = (32767, 32767)
        self.pinch_ready = False
        self._connect()

    # ---------------------------------------------------------------- ADB
    def _run(self, *args, timeout: float = 15, binary: bool = False):
        cmd = [self.adb, "-s", self.device, *args]
        out = subprocess.run(cmd, capture_output=True, timeout=timeout,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return out.stdout if binary else out.stdout.decode("utf-8", "replace")

    def _connect(self):
        if ":" in self.device:
            subprocess.run([self.adb, "connect", self.device], capture_output=True, timeout=15,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def _shell(self, cmd: str, attempt: int = 0) -> str:
        """Commande dans un shell ADB gardé ouvert ; attend qu'elle soit finie."""
        with self.lock:
            try:
                if self.shell is None or self.shell.poll() is not None:
                    self.shell = subprocess.Popen(
                        [self.adb, "-s", self.device, "shell"], stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                assert self.shell.stdin and self.shell.stdout
                self.shell.stdin.write(f"{cmd}; echo {DONE}\n".encode())
                self.shell.stdin.flush()
                lines = []
                while True:
                    line = self.shell.stdout.readline()
                    if not line:
                        raise OSError("shell ADB fermé")
                    text = line.decode("utf-8", "replace").rstrip("\r\n")
                    if text.endswith(DONE):
                        return "\n".join(lines)
                    lines.append(text)
            except (OSError, AssertionError) as exc:
                self.shell = None
                if attempt < 1:
                    self._connect()
                    return self._shell(cmd, attempt + 1)
                log(f"⚠️ ADB : commande perdue ({exc})")
                return ""

    def display_format(self) -> tuple[int, int, int] | None:
        """(largeur, hauteur, dpi) de l'écran Android, ou None."""
        import re
        size = self._run("shell", "wm size", timeout=10)
        dens = self._run("shell", "wm density", timeout=10)
        sizes = re.findall(r"(\d+)x(\d+)", size)
        dpis = re.findall(r"(\d+)", dens)
        if not sizes or not dpis:
            return None
        w, h = (int(v) for v in sizes[-1])
        return max(w, h), min(w, h), int(dpis[-1])

    # ---------------------------------------------------------------- capture
    def grab(self):
        try:
            raw = self._run("exec-out", "screencap", timeout=10, binary=True)
        except (subprocess.TimeoutExpired, OSError):
            return None
        if len(raw) < 16:
            return None
        w = int.from_bytes(raw[0:4], "little")
        h = int.from_bytes(raw[4:8], "little")
        if w <= 0 or h <= 0:
            return None
        offset = len(raw) - w * h * 4
        if offset not in (12, 16):
            return None
        img = np.frombuffer(raw, np.uint8, count=w * h * 4, offset=offset).reshape(h, w, 4)
        img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
        if h > w:   # portrait : le jeu tourne en paysage
            img = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
            w, h = h, w
        if self.map is None or (self.map.w, self.map.h) != (w, h):
            self.map = FrameMap(w, h)
        return self.map.compose(img)

    def _pt(self, x, y):
        if self.map is None:
            self.grab()
        return self.map.to_device(x, y) if self.map else (int(x), int(y))

    # ---------------------------------------------------------------- entrées
    def move(self, x, y, duration=0.0):
        self._pos = (x, y)
        if getattr(self, "_down", False):
            x0, y0 = getattr(self, "_last", (x, y))
            steps = max(1, int(duration / 0.03))
            for i in range(1, steps + 1):
                px, py = self._pt(x0 + (x - x0) * i / steps, y0 + (y - y0) * i / steps)
                self._shell(f"input motionevent MOVE {px} {py}")
            self._last = (x, y)

    def mouse_down(self, x, y):
        px, py = self._pt(x, y)
        self._down, self._last = True, (x, y)
        self._shell(f"input motionevent DOWN {px} {py}")

    def mouse_up(self, x, y):
        px, py = self._pt(x, y)
        self._down = False
        self._shell(f"input motionevent UP {px} {py}")

    def click(self, x, y, hold=0.06):
        px, py = self._pt(x, y)
        self._shell(f"input swipe {px} {py} {px} {py} {max(30, int(hold * 1000))}")

    def scroll(self, clicks, x, y):
        """Listes : glissement vertical (≈ 120 px par cran). clicks < 0 = descendre dans la liste."""
        dy = int(-clicks * 120)
        y2 = max(60, min(VH - 60, y - dy))
        self.drag(x, y, x, y2, duration=0.35, hold_end=0.2)

    def key(self, name):
        self._shell(f"input keyevent {KEYCODES.get(name.lower(), 111)}")

    # ---------------------------------------------------------------- pincements (dézoom)
    def _find_touchscreen(self):
        out = self._run("shell", "getevent -pl", timeout=10)
        dev, mx, my, best = None, 32767, 32767, None
        for block in out.split("add device")[1:]:
            path = block.split(":", 1)[1].splitlines()[0].strip() if ":" in block else None
            if "ABS_MT_POSITION_X" not in block:
                continue
            for line in block.splitlines():
                if "ABS_MT_POSITION_X" in line and "max" in line:
                    mx = int(line.split("max")[1].split(",")[0])
                if "ABS_MT_POSITION_Y" in line and "max" in line:
                    my = int(line.split("max")[1].split(",")[0])
            best = (path, mx, my)
            break
        if best:
            dev, mx, my = best
        self.touch_dev, self.touch_max = dev, (mx, my)
        return dev

    def _pinch_script(self, direction: str, cx: int, cy: int, steps: int = 12) -> str:
        """sendevent d'un pincement (protocole multi-touch B). direction 'in' = dézoom."""
        dev = self.touch_dev
        w, h = (self.map.w, self.map.h) if self.map else (1920, 1080)
        mx, my = self.touch_max
        start, end = (400, 60) if direction == "in" else (60, 400)
        lines = []

        def ev(t, c, v):
            lines.append(f"sendevent {dev} {t} {c} {v}")

        for i in range(steps + 1):
            d = start + (end - start) * i / steps
            for finger, sign in ((0, -1), (1, 1)):
                px = int((cx + sign * d) * mx / w)
                py = int(cy * my / h)
                ev(3, 0x2F, finger)                    # ABS_MT_SLOT
                if i == 0:
                    ev(3, 0x39, 100 + finger)          # ABS_MT_TRACKING_ID
                ev(3, 0x35, px)                        # ABS_MT_POSITION_X
                ev(3, 0x36, py)                        # ABS_MT_POSITION_Y
            if i == 0:
                ev(1, 330, 1)                          # BTN_TOUCH
            ev(0, 0, 0)                                # SYN_REPORT
        for finger in (0, 1):
            ev(3, 0x2F, finger)
            ev(3, 0x39, -1)
        ev(1, 330, 0)
        ev(0, 0, 0)
        return "\n".join(lines) + "\n"

    def _push_pinches(self) -> bool:
        if self.pinch_ready:
            return True
        if self.map is None:
            self.grab()
        if not self._find_touchscreen():
            return False
        w, h = (self.map.w, self.map.h) if self.map else (1920, 1080)
        self._run("shell", f"mkdir -p {REMOTE_DIR}")
        for name in ("in", "out"):
            with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as f:
                f.write(self._pinch_script(name, w // 2, h // 2))
                tmp = f.name
            self._run("push", tmp, f"{REMOTE_DIR}/pinch_{name}.sh", timeout=20)
            os.unlink(tmp)
        self.pinch_ready = True
        return True

    def zoom_out(self, x=960, y=540, times=4):
        if not self._push_pinches():
            log("⚠️ ADB : écran tactile introuvable, dézoom impossible")
            return
        for _ in range(max(1, times // 2)):
            self._shell(f"sh {REMOTE_DIR}/pinch_in.sh")
            time.sleep(0.15)

    # ---------------------------------------------------------------- jeu
    def open_game(self):
        self._shell(f"monkey -p {PACKAGE} -c android.intent.category.LAUNCHER 1")

    def close_game(self):
        self._shell(f"am force-stop {PACKAGE}")

    def describe(self):
        fmt = self.map and f"{self.map.w}x{self.map.h}"
        return f"ADB {self.device} {fmt or ''}".strip()
