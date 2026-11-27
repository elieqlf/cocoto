"""Village : contrôles au START (village affiché, langue, bon village), bateau TH ↔ BH,
récolte des collecteurs, coffre du Treasure Event, réserves (remplissage, budget de départ)."""
from __future__ import annotations

import difflib
import random
import time

import numpy as np

from .. import layout, ocr, vision
from ..game import Game
from ..logger import log

COLLECT_KEYS = ("collect_gold", "collect_elixir", "collect_dark")
BH_COLLECT_KEYS = ("bh_collect_gold", "bh_collect_elixir")
COLLECT_SCALES = (0.9, 1.0, 1.1, 1.2)
BOAT_DRAG = {"TH": ((800, 450), (1150, 150)), "BH": ((1000, 300), (800, 750))}


class VillageError(Exception):
    def __init__(self, title: str, message: str):
        super().__init__(message)
        self.title = title
        self.message = message


# ---------------------------------------------------------------- contrôles au START
def game_in_english(game: Game, screen) -> bool | None:
    """True = boutons « Battle » / « Build » lus en anglais ; False = autre langue ; None = illisible."""
    words = [ocr.read_box_text(screen, layout.BATTLE_LABEL_BOX).lower(),
             ocr.read_box_text(screen, layout.BUILD_LABEL_BOX).lower()]
    if not any(words):
        return None
    english = ("battle", "build")
    return any(difflib.SequenceMatcher(None, w, e).ratio() > 0.7 for w, e in zip(words, english))


def check_village(game: Game, mode: str, travel_ok: bool = False, timeout: float = 12.0) -> None:
    """Au 1er village après START : village affiché, jeu en anglais, bon village (sinon bateau)."""
    if not game.wait_village(timeout):
        raise VillageError("Village pas affiché",
                           "Le bot ne voit pas ton village : ouvre Clash of Clans sur ton village, "
                           "ferme les menus et popups, garde le jeu au premier plan (ou active le "
                           "mode arrière-plan / ADB), puis relance.")
    screen = game.grab()
    if game.panel_open(screen):
        game.click_box(layout.CLOSE_VILLAGE_CLICK)
    eng = game_in_english(game, screen)
    if eng is False:
        raise VillageError("Mauvaise langue du jeu",
                           "Clash of Clans doit être en anglais (Settings → Language → English).")
    shown = game.village(screen)
    if shown and shown != mode:
        if travel_ok and travel_to_village(game, mode):
            return
        names = {"TH": "village principal", "BH": "base des ouvriers"}
        raise VillageError("Mauvais village",
                           f"Le bot a été lancé en mode {names[mode]} mais le jeu affiche la "
                           f"{names[shown]}. Change de village ou de mode, puis relance.")


def travel_to_village(game: Game, target: str, attempts: int = 3) -> bool:
    """Bateau vers l'autre village si le jeu n'est pas déjà sur target."""
    for attempt in range(attempts):
        screen = game.grab()
        current = game.village(screen)
        if current == target:
            return True
        game.zoom_out()
        (x1, y1), (x2, y2) = BOAT_DRAG[current or "TH"]
        game.drag(x1, y1, x2, y2, 0.5)
        game.sleep(0.6)
        key = "boat_th" if current != "BH" else "boat_bh"
        m = game.find(key, scales=(0.8, 0.9, 1.0, 1.1, 1.2), threshold=0.68)
        if not m:
            log(f"⚠️ Bateau introuvable (essai {attempt + 1})")
            continue
        game.click_match(m)
        log(f"⛵ Bateau vers {target}")
        end = time.monotonic() + 30
        while time.monotonic() < end:
            game.state.sleep(1.5)
            screen = game.grab()
            if game.battle_button_visible(screen) and game.village(screen) == target:
                log(f"⛵ Arrivé : {target}")
                return True
    return False


# ---------------------------------------------------------------- récolte
def collect_resources(game: Game, keys=COLLECT_KEYS, threshold: float = 0.75) -> int:
    """Un clic sur une bulle de chaque ressource : le jeu récolte tous les collecteurs de ce type."""
    screen = game.grab()
    excluded = [(0, 0, 400, 300), (1500, 0, 1920, 300), (0, 850, 1920, 1080)]
    done = 0
    for key in keys:
        best = None
        for s in COLLECT_SCALES:
            tpl = game.tpl.get(key, s)
            for m in vision.match_all(screen, tpl, threshold):
                if any(x1 <= m.x <= x2 and y1 <= m.y <= y2 for x1, y1, x2, y2 in excluded):
                    continue
                if best is None or m.score > best.score:
                    best = m
        if best:
            game.click_match(best)
            done += 1
            log(f"💰 Récolte : {key.split('_')[-1]} ({best.score:.2f})")
            game.sleep(0.5)
            screen = game.grab()
    return done


# ---------------------------------------------------------------- coffre / bonus
def treasure_visible(game: Game, screen=None) -> bool:
    screen = game.grab() if screen is None else screen
    return any(game.find(k, screen) for k in ("treasure_common", "treasure_hammers"))


def open_treasure_chest(game: Game, timeout: float = 25.0) -> bool:
    """Tape le coffre jusqu'à l'écran de récompense, puis Continue."""
    end = time.monotonic() + timeout
    taps = 0
    while time.monotonic() < end:
        screen = game.grab()
        m = game.find("treasure_continue", screen)
        if m:
            game.click_match(m)
            log(f"🎁 Coffre ouvert ({taps} taps)")
            return True
        game.click(960 + random.randint(-60, 60), 520 + random.randint(-40, 40), jitter=0)
        taps += 1
        game.state.sleep(random.uniform(0.35, 0.6))
    return False


def star_bonus(game: Game) -> bool:
    m = game.find("star_bonus")
    if m:
        game.click_match(m)
        log("⭐ Star bonus récupéré")
        return True
    return False


# ---------------------------------------------------------------- réserves
# Mesuré (GPG 2026-11) : or plein H≈25 S≈240, élixir H≈150 S≈200, noir H≈140 S≈190 V≈45 ;
# la partie vide est translucide et laisse voir la forêt (H≈31-41) : ne pas l'accepter.
STORAGE_HUES = {"gold": ((15, 30), 90), "elixir": ((135, 165), 70), "dark": ((120, 165), 100)}


def storage_fill(screen: np.ndarray) -> dict[str, float]:
    """Part remplie de chaque barre de réserve (haut à droite), 0 si absente / cachée."""
    out = {}
    for kind, box in layout.STORAGE_BARS.items():
        y1, y2 = box[:2]
        x1, x2 = box[2:4] if len(box) >= 4 else layout.STORAGE_BAR_X
        band = vision.hsv(screen, (x1, y1, x2, y2))
        if band.size == 0:
            out[kind] = 0.0
            continue
        (h_lo, h_hi), s_min = STORAGE_HUES[kind]
        filled = (band[:, :, 0] >= h_lo) & (band[:, :, 0] <= h_hi) & (band[:, :, 1] > s_min)
        if kind == "dark":   # élixir noir : violet très sombre, mais pas noir (bord de la barre)
            filled &= band[:, :, 2] > 25
        cols = filled.mean(axis=0) > 0.5
        run = 0
        for c in cols[::-1]:          # la barre se remplit de droite à gauche
            if c:
                run += 1
            elif run:
                break
        out[kind] = min(0.97, run / max(1, len(cols)))
    return out


def read_village_resources(screen) -> dict[str, int | None]:
    x1, x2 = layout.VILLAGE_RES_X
    return {k: ocr.read_amount(screen, (x1, y1, x2, y2)) for k, (y1, y2) in layout.VILLAGE_RES_ROWS.items()}


def load_village_resources(game: Game) -> None:
    """Au 1er village après START : les réserves deviennent le budget des murs / améliorations."""
    for _ in range(3):
        vals = read_village_resources(game.grab())
        if vals.get("gold") is not None and vals.get("elixir") is not None:
            with game.state._lock:
                for k, v in vals.items():
                    if v is not None:
                        game.state.accum[k] = v
            log(f"🏦 Budget de départ : or {vals['gold']:,} élixir {vals['elixir']:,}".replace(",", " "))
            return
        game.sleep(0.5)
    log("🏦 Réserves illisibles : budget de départ à 0")
