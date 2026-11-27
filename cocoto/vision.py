"""Reconnaissance d'images : templates (OpenCV TM_CCOEFF_NORMED), couleurs, composantes."""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import Iterable

import cv2
import numpy as np

from . import paths

Box = tuple  # (x1, y1, x2, y2)

# seuils par défaut (relevés dans CoCoBot : 0.8 en général, plus pour les boutons de lancement)
DEFAULT_THRESHOLD = 0.8
THRESHOLDS = {
    "find_match": 0.88, "army_attack": 0.75, "bh_find_now": 0.85,
    "army_request": 0.9, "request_title": 0.85, "request_send": 0.85,
    "capital_airship_inner": 0.85, "capital_airship": 0.7, "capital_airship_grey": 0.82,
    "raid_go": 0.9, "raid_attack_red": 0.85, "raid_attack_scout": 0.9, "raid_attack_now": 0.92,
    "raid_map_end": 0.9, "raid_battle_starts": 0.8, "raid_storage_full": 0.85,
    "ranked_confirm_title": 0.9, "ranked_confirm_attack": 0.8,
    "battle_surrender": 0.9, "need_more": 0.85, "wall_word": 0.72, "bh_speed_1x": 0.95,
    "daily_reward": 0.85, "daily_claim": 0.8, "welcome_back": 0.85, "loading_text": 0.85,
    "upgrade_filters": 0.8, "pick_reward": 0.85, "treasure_common": 0.85, "treasure_hammers": 0.85,
    "reco_inactivity": 0.8, "reco_another_device": 0.8, "collect_gold": 0.75,
    "collect_elixir": 0.75, "collect_dark": 0.75, "bh_collect_gold": 0.75, "bh_collect_elixir": 0.75,
    "village_th": 0.75, "village_bh": 0.75, "boat_th": 0.7, "boat_bh": 0.7,
}

# nom logique → fichier du dossier img/ (les fichiers de CoCoBot mélangent .png et .PNG)
ALIASES = {"attack": "attack_button", "end": "end", "wall": "wall", "x": "x", "up": "up"}
# Partie utile de certains templates (y1, y2) : le reste change avec le jeu du joueur.
# wall_more : l'icône montre le mur à SON niveau (mesuré GPG 2026-11 : 0,75 entier → 0,88 texte seul).
# wall_add1 : texte « Add Wall » seul (commun à +10 et +1 → walls.add_one_button prend le plus à droite).
TEMPLATE_CROPS = {"wall_more": (60, None), "wall_add1": (60, None)}


@dataclass
class Match:
    score: float
    x: int          # centre, coordonnées écran
    y: int
    w: int
    h: int

    @property
    def box(self) -> Box:
        return (self.x - self.w // 2, self.y - self.h // 2, self.x + self.w // 2, self.y + self.h // 2)

    @property
    def center(self) -> tuple[int, int]:
        return self.x, self.y


class Templates:
    """Charge les templates à la demande depuis assets/img (cache, thread-safe)."""

    def __init__(self, folder: str | None = None, user_folder: str | None = None):
        self.folder = folder or paths.img_dir()
        # templates personnels (ex. héros avec skin) : %APPDATA%\Cocoto\img, prioritaires
        if user_folder is None and folder is None:
            user_folder = paths.data_path("img")
        self.user_folder = user_folder
        self._cache: dict[tuple[str, float], np.ndarray | None] = {}
        self._lock = threading.Lock()
        self._index: dict[str, str] | None = None

    def _build_index(self) -> dict[str, str]:
        index = {}
        for folder in (self.folder, self.user_folder):
            if not folder or not os.path.isdir(folder):
                continue
            for root, _dirs, files in os.walk(folder):
                for f in files:
                    stem, ext = os.path.splitext(f)
                    if ext.lower() in (".png", ".jpg"):
                        rel = os.path.relpath(os.path.join(root, stem), folder).replace(os.sep, "/")
                        index[rel.lower()] = os.path.join(root, f)
        return index

    def variants(self, name: str) -> list[str]:
        """name et ses variantes « name_xxx » (ex. hero2, hero2_skin)."""
        if self._index is None:
            self._index = self._build_index()
        name = name.lower()
        return sorted(k for k in self._index if k == name or k.startswith(name + "_"))

    def reload(self) -> None:
        with self._lock:
            self._index = None
            self._cache.clear()

    def path(self, name: str) -> str | None:
        if self._index is None:
            self._index = self._build_index()
        name = ALIASES.get(name, name)
        return self._index.get(name.lower())

    def exists(self, name: str) -> bool:
        return self.path(name) is not None

    def get(self, name: str, scale: float = 1.0) -> np.ndarray | None:
        key = (name, round(scale, 3))
        with self._lock:
            if key in self._cache:
                return self._cache[key]
            p = self.path(name)
            img = cv2.imread(p, cv2.IMREAD_COLOR) if p else None
            crop = TEMPLATE_CROPS.get(name)
            if img is not None and crop and os.path.dirname(p) == self.folder:
                img = img[crop[0]:crop[1]]          # templates perso (dossier utilisateur) : tels quels
            if img is not None and scale != 1.0:
                img = cv2.resize(img, None, fx=scale, fy=scale,
                                 interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
            self._cache[key] = img
            return img

    def threshold(self, name: str) -> float:
        return THRESHOLDS.get(name, DEFAULT_THRESHOLD)


def crop(screen: np.ndarray, box: Box | None) -> tuple[np.ndarray, int, int]:
    if box is None:
        return screen, 0, 0
    h, w = screen.shape[:2]
    x1, y1, x2, y2 = (int(v) for v in box)
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    return screen[y1:y2, x1:x2], x1, y1


def match_image(screen: np.ndarray, tpl: np.ndarray, box: Box | None = None,
                gray: bool = False) -> Match | None:
    """Meilleure position de tpl dans screen (zone box). None si le template ne tient pas."""
    if screen is None or tpl is None:
        return None
    zone, ox, oy = crop(screen, box)
    th, tw = tpl.shape[:2]
    if zone.shape[0] < th or zone.shape[1] < tw:
        return None
    if gray:
        zone = cv2.cvtColor(zone, cv2.COLOR_BGR2GRAY)
        tpl = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY) if tpl.ndim == 3 else tpl
    res = cv2.matchTemplate(zone, tpl, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)
    if not np.isfinite(max_val):
        return None
    return Match(float(max_val), ox + max_loc[0] + tw // 2, oy + max_loc[1] + th // 2, tw, th)


def match_all(screen: np.ndarray, tpl: np.ndarray, threshold: float, box: Box | None = None,
              min_dist: int = 20) -> list[Match]:
    """Toutes les positions au-dessus du seuil (suppression des doublons proches)."""
    if screen is None or tpl is None:
        return []
    zone, ox, oy = crop(screen, box)
    th, tw = tpl.shape[:2]
    if zone.shape[0] < th or zone.shape[1] < tw:
        return []
    res = cv2.matchTemplate(zone, tpl, cv2.TM_CCOEFF_NORMED)
    ys, xs = np.where(res >= threshold)
    found: list[Match] = []
    for score, y, x in sorted(zip(res[ys, xs], ys, xs), reverse=True):
        cx, cy = ox + x + tw // 2, oy + y + th // 2
        if all(abs(cx - m.x) > min_dist or abs(cy - m.y) > min_dist for m in found):
            found.append(Match(float(score), int(cx), int(cy), tw, th))
    return found


# ------------------------------------------------------------------ couleurs
def hsv(screen: np.ndarray, box: Box | None = None) -> np.ndarray:
    zone, _, _ = crop(screen, box)
    return cv2.cvtColor(zone, cv2.COLOR_BGR2HSV)


def mask_ratio(screen: np.ndarray, box: Box, lower: Iterable[int], upper: Iterable[int]) -> float:
    """Part des pixels de la zone dont le HSV est entre lower et upper (OpenCV : H 0-179)."""
    h = hsv(screen, box)
    if h.size == 0:
        return 0.0
    m = cv2.inRange(h, np.array(list(lower), np.uint8), np.array(list(upper), np.uint8))
    return float(np.count_nonzero(m)) / m.size


def yellow_ratio(screen, box) -> float:
    return mask_ratio(screen, box, (18, 120, 150), (35, 255, 255))


def red_ratio(screen, box) -> float:
    a = mask_ratio(screen, box, (0, 150, 150), (8, 255, 255))
    b = mask_ratio(screen, box, (170, 150, 150), (179, 255, 255))
    return a + b


def green_ratio(screen, box) -> float:
    return mask_ratio(screen, box, (40, 120, 100), (80, 255, 255))


def gray_ratio(screen, box, max_sat: int = 40) -> float:
    return mask_ratio(screen, box, (0, 0, 40), (179, max_sat, 255))


def mean_brightness(screen, box) -> float:
    zone, _, _ = crop(screen, box)
    if zone.size == 0:
        return 0.0
    return float(cv2.cvtColor(zone, cv2.COLOR_BGR2GRAY).mean())


def white_text_mask(zone_bgr: np.ndarray, v_min: int = 200, s_max: int = 60) -> np.ndarray:
    h = cv2.cvtColor(zone_bgr, cv2.COLOR_BGR2HSV)
    return cv2.inRange(h, np.array((0, 0, v_min), np.uint8), np.array((179, s_max, 255), np.uint8))


def components(mask: np.ndarray, min_h: int = 8, max_h: int = 80, min_area: int = 12) -> list[tuple]:
    """Composantes connexes (x, y, w, h, aire) de taille chiffre, triées de gauche à droite."""
    n, _labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    out = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if min_h <= h <= max_h and area >= min_area:
            out.append((int(x), int(y), int(w), int(h), int(area)))
    return sorted(out)


def same_image(a: np.ndarray | None, b: np.ndarray | None, tol: float = 2.0) -> bool:
    """Deux captures (ou zones) quasi identiques : sert à attendre la fin d'une animation."""
    if a is None or b is None or a.shape != b.shape:
        return False
    diff = cv2.absdiff(a, b)
    return float(diff.mean()) <= tol


def to_jpeg(screen: np.ndarray, max_w: int = 1280, quality: int = 75) -> bytes:
    h, w = screen.shape[:2]
    if w > max_w:
        screen = cv2.resize(screen, (max_w, int(h * max_w / w)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", screen, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    return buf.tobytes() if ok else b""
