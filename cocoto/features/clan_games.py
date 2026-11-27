"""Jeux de clan : ouvre la maison des Jeux (en haut à gauche du village) et lance un défi du village
principal faisable avec n'importe quelle armée (« Multiplayer » : détruire, gagner, étoiles, loot…).
Aucun défi faisable → en lance un puis le jette (Trash) pour qu'un autre le remplace (10 min)."""
from __future__ import annotations

import re
import time

import cv2
import numpy as np

from .. import layout, ocr, vision
from ..game import Game
from ..logger import log

HOUSE_SCALES = (0.7, 0.78, 0.85, 0.92, 1.0, 1.1)
WINDOW_BOX = (330, 160, 1590, 1000)
REJECT_WORDS = ("using", "builder battle", "spell", "hero", "abilit", "equipment", "pet", "siege",
                "least one", "clan castle", "without", "only", "war", "capital", "donat", "train",
                "brew", "perfect")
CHECK_EVERY = 5   # combats entre deux vérifications


def is_th_challenge(text: str) -> bool:
    """Défi du village principal : « Multiplayer », souvent mal lu (« Mulbiplayer »)."""
    t = text.lower()
    return bool(re.search(r"mul.{0,3}i.?pla", t)) or "multiplayer" in t


def challenge_ok(text: str) -> bool:
    t = text.lower()
    return is_th_challenge(t) and not any(w in t for w in REJECT_WORDS)


def find_house(game: Game, screen):
    best = None
    for s in HOUSE_SCALES:
        m = vision.match_image(screen, game.tpl.get("clangames_house", s), (0, 0, 900, 600))
        if m and (best is None or m.score > best.score):
            best = m
    return best if best and best.score >= 0.72 else None


def cards(screen) -> list[dict]:
    """Cartes visibles : [{center, state}] ; state = available | active | locked."""
    h = vision.hsv(screen, WINDOW_BOX)
    beige = cv2.inRange(h, np.array((10, 25, 170), np.uint8), np.array((32, 140, 255), np.uint8))
    mask = cv2.morphologyEx(255 - beige, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8))
    n, _l, stats, cents = cv2.connectedComponentsWithStats(mask, 8)
    ox, oy = WINDOW_BOX[0], WINDOW_BOX[1]
    out = []
    for i in range(1, n):
        x, y, w, hh, area = stats[i]
        if not (150 <= w <= 330 and 200 <= hh <= 330):
            continue
        cx, cy = int(ox + x + w / 2), int(oy + y + hh / 2)
        pill = (ox + x + 20, oy + y + hh - 45, ox + x + w - 20, oy + y + hh - 10)
        if vision.green_ratio(screen, pill) > 0.25:
            state = "active"
        elif vision.gray_ratio(screen, (ox + x, oy + y, ox + x + w, oy + y + hh), 30) > 0.6:
            state = "locked"
        else:
            state = "available"
        out.append({"center": (cx, cy), "state": state})
    return sorted(out, key=lambda c: (c["center"][1] // 50, c["center"][0]))


class ClanGames:
    def __init__(self, game: Game):
        self.game = game
        self.battles = CHECK_EVERY
        self.cooldown_until = 0.0
        self.status = "none"

    def due(self) -> bool:
        self.battles += 1
        if time.time() < self.cooldown_until:
            return False
        if self.status == "active" and self.battles < CHECK_EVERY:
            return False
        return True

    def run(self) -> str:
        """« active » (défi en cours ou lancé), « cooldown » (attente après un Trash) ou « none »."""
        g = self.game
        self.battles = 0
        g.zoom_out()
        house = find_house(g, g.grab())
        if not house:
            log("🎯 Jeux de clan : maison introuvable (pas de Jeux en cours ?)")
            self.status = "none"
            return self.status
        g.click_match(house)
        if not g.wait("clangames_tab", 6):
            log("🎯 Jeux de clan : fenêtre pas ouverte")
            g.close_window()
            return "none"
        try:
            return self._choose()
        finally:
            g.close_window()
            g.wait_village(10)

    def _choose(self) -> str:
        g = self.game
        screen = g.wait_still(WINDOW_BOX, 3)
        if g.find("clangames_cooldown", screen):
            self.cooldown_until = time.time() + 600
            log("🎯 Jeux de clan : attente après un défi jeté")
            self.status = "cooldown"
            return self.status
        visible = cards(screen)
        if any(c["state"] == "active" for c in visible):
            log("🎯 Jeux de clan : défi déjà en cours")
            self.status = "active"
            return self.status
        first_th = None
        for card in visible:
            if card["state"] != "available":
                continue
            g.click(*card["center"])
            start = g.wait("clangames_start", 3, stable=True)
            text = ocr.read_box_text(g.grab(), WINDOW_BOX)
            if start and challenge_ok(text):
                g.click_match(start)
                log(f"🎯 Défi lancé : {text[:80]}")
                self.status = "active"
                return self.status
            if start and is_th_challenge(text) and first_th is None:
                first_th = card["center"]
            g.close_window()
            g.sleep(0.4)
        if first_th:   # rien de faisable : lancer puis jeter un défi pour en avoir un nouveau
            g.click(*first_th)
            start = g.wait("clangames_start", 3, stable=True)
            if start:
                g.click_match(start)
                g.sleep(1.0)
                trash = g.wait("clangames_trash", 4, stable=True)
                if trash:
                    g.click_match(trash)
                    g.sleep(0.6)
                    ok = g.find("bh_okay") or g.find("welcome_okay")
                    if ok:
                        g.click_match(ok)
                    self.cooldown_until = time.time() + 600
                    log("🗑️ Jeux de clan : défi infaisable jeté (nouveau dans 10 min)")
                    self.status = "cooldown"
                    return self.status
        self.status = "none"
        return self.status
