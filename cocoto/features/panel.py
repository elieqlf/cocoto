"""Panneau Build (liste des améliorations) : ouverture / fermeture, lignes lues par OCR, prix,
ressource du prix, ouvriers libres, défilement avec attente de fin d'inertie."""
from __future__ import annotations

import difflib
import re

import numpy as np

from .. import layout, ocr, vision
from ..game import Game
from ..logger import log


def normalize(text: str) -> str:
    return re.sub(r"[^a-z]+", " ", (text or "").lower()).strip()


def match_name(text: str, names: list[str], cutoff: float = 0.78) -> str | None:
    """Nom anglais de names correspondant au texte OCR d'une ligne (« Archer Tower 3 »), ou None."""
    norm = normalize(re.sub(r"\d+", "", text))
    best, best_ratio = None, 0.0
    for name in names:
        n = normalize(name)
        ratio = difflib.SequenceMatcher(None, norm[:len(n) + 2], n).ratio()
        if n in norm:
            ratio = 1.0
        if ratio > best_ratio:
            best, best_ratio = name, ratio
    return best if best_ratio >= cutoff else None


class BuildPanel:
    def __init__(self, game: Game, builders_box=None):
        self.game = game
        self.builders_box = builders_box or layout.FREE_BUILDERS_BOX

    def is_open(self, screen=None) -> bool:
        return self.game.panel_open(screen)

    def open(self) -> bool:
        if self.is_open():
            return True
        self.game.click_box(layout.BUILD_BUTTON)
        for _ in range(8):
            self.game.sleep(0.35)
            if self.is_open():
                return True
        log("⚠️ Panneau Build pas ouvert")
        return False

    def close(self) -> bool:
        for _ in range(3):
            screen = self.game.grab()
            for key in ("need_more", "bh_builders_busy"):
                if self.game.find(key, screen):
                    m = self.game.find("close_x", screen)
                    if m:
                        self.game.click_match(m)
                        self.game.sleep(0.4)
            if not self.is_open():
                return True
            # croix du panneau d'abord : un clic « dans le vide » du village peut tomber sur un
            # bâtiment et le sélectionner (vu GPG 2026-11 : un mur niveau 1 sélectionné)
            self.game.click(*layout.PANEL_CLOSE_X, jitter=4)
            self.game.sleep(0.6)
            if not self.is_open():
                return True
            self.game.click_box(layout.CLOSE_VILLAGE_CLICK)
            self.game.sleep(0.6)
        ok = not self.is_open()
        if not ok:
            log("⚠️ Panneau des améliorations toujours ouvert")
        return ok

    # ---------------------------------------------------------------- lecture
    def rows(self, screen, box=None) -> list[tuple[int, str]]:
        """[(y du nom, texte)] de la colonne des noms, en coordonnées écran."""
        box = box or layout.WALL_LIST_BOX
        zone, ox, oy = vision.crop(screen, box)
        lines = ocr.ocr_lines(ocr.read_text(zone, detail=True), max_gap=40)
        return [(y + oy, t) for y, t in lines if t.strip()]

    def cost_box(self, row_y: int) -> tuple[int, int, int, int]:
        x1 = layout.WALL_LIST_BOX[0]
        cy = row_y + layout.WALL_COST_DY
        return (x1, cy - 16, layout.PANEL_COST_X2, cy + 16)

    def read_cost(self, screen, row_y: int) -> int | None:
        """Prix sous le nom : chiffres blancs, ou rouges si les ressources manquent (canal rouge)."""
        zone, _, _ = vision.crop(screen, self.cost_box(row_y))
        if zone.size == 0:
            return None
        red = zone[:, :, 2]
        mask = ((red > 170)).astype(np.uint8) * 255
        comps = vision.components(mask, min_h=12, max_h=30)
        if not comps:
            return None
        digits = ocr.read_digits_mask(mask, comps)
        return int(digits) if digits else None

    def cost_is_red(self, screen, row_y: int) -> bool:
        return vision.red_ratio(screen, self.cost_box(row_y)) > 0.04

    def cost_resource(self, screen, row_y: int) -> str | None:
        """Ressource du prix d'après l'icône à droite des chiffres. Mesuré GPG 2026-11 : or H≈21,
        élixir H≈140, élixir noir = icône sombre peu saturée (le fond brun du panneau a H≈12).
        None (gemmes…) = ligne ignorée."""
        cy = row_y + layout.WALL_COST_DY
        ix1, ix2 = layout.PANEL_COST_ICON_X
        h = vision.hsv(screen, (ix1, cy - 12, ix2, cy + 12))
        if h.size == 0:
            return None
        hue, sat, val = h[:, :, 0], h[:, :, 1], h[:, :, 2]
        n = hue.size
        scores = {
            "gold": np.count_nonzero((hue >= 17) & (hue <= 35) & (sat > 90) & (val > 110)) / n,
            "elixir": np.count_nonzero((hue >= 130) & (hue <= 165) & (sat > 90) & (val > 100)) / n,
            "dark": np.count_nonzero(val < 70) / n,
        }
        best = max(scores, key=scores.get)
        return best if scores[best] > 0.2 else None

    def in_progress(self, screen, row_y: int) -> bool:
        """Amélioration en cours (barre verte à gauche, pas de prix)."""
        x1 = layout.WALL_LIST_BOX[0]
        return vision.green_ratio(screen, (x1 - 60, row_y - 20, x1 - 10, row_y + 20)) > 0.3

    def free_builders(self, screen=None) -> int | None:
        screen = self.game.grab() if screen is None else screen
        frac = ocr.read_fraction(screen, self.builders_box)
        return frac[0] if frac else None

    # ---------------------------------------------------------------- défilement
    def scroll(self, direction: int, notches: int = 2) -> np.ndarray:
        """direction -1 = descendre, +1 = remonter (~2 lignes, ≈175 px par cran). Capture une fois immobile."""
        x, y = layout.WALL_SCROLL_POS
        self.game.scroll(direction * notches, x, y)
        return self.game.wait_still(layout.WALL_LIST_BOX, timeout=2.5)

    def to_top(self) -> None:
        prev = None
        for _ in range(12):
            screen = self.scroll(+1, 5)
            zone, _, _ = vision.crop(screen, layout.WALL_LIST_BOX)
            if prev is not None and vision.same_image(prev, zone):
                return
            prev = zone.copy()

    def click_row(self, row_y: int) -> None:
        x1, _, x2, _ = layout.WALL_LIST_BOX
        self.game.click((x1 + x2) // 2, row_y, jitter=5)
        self.game.sleep(0.7)

    def find_button(self, key: str, screen=None, threshold: float = 0.8):
        return self.game.find(key, screen, layout.UPGRADE_WINDOW_BUTTONS, threshold)
