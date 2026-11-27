"""Multi-comptes : le bot farme plusieurs comptes à tour de rôle via le panneau Supercell ID.

Tous les comptes doivent être liés à Supercell ID. Tous les N combats : portrait → onglet Settings →
flèche bleue (SWITCH ID) → liste des comptes (nom Supercell ID en gras + pseudo du jeu en dessous) →
défilement par glissement jusqu'au compte → chargement → « Welcome Back » → vérification du pseudo
affiché en haut à gauche → chargement du profil du compte. Compte ouvert sur l'autre village → bateau."""
from __future__ import annotations

import re
import time

from .. import layout, ocr, vision
from ..game import Game
from ..logger import log
from ..parsing import closest_name, parse_amount, player_name_score
from .village import travel_to_village


class AccountSet:
    """Carte ACCOUNTS d'un mode : switch, fréquence, comptes (nom du joueur + profil)."""

    def __init__(self, settings, key: str = "accounts"):
        self.settings, self.key = settings, key
        self.battles = 0

    @property
    def data(self) -> dict:
        return self.settings.get(self.key) or {}

    def enabled(self) -> bool:
        d = self.data
        return bool(d.get("enabled")) and len(self.accounts()) >= 2

    def accounts(self) -> list[tuple[str, str]]:
        d = self.data
        names, profiles = d.get("names", []), d.get("profiles", [])
        return [(n.strip(), (profiles[i] if i < len(profiles) else "") or "")
                for i, n in enumerate(names) if n and n.strip()]

    def every(self) -> int:
        return max(1, parse_amount(str(self.data.get("every", "3"))) or 3)

    def rotation_due(self) -> bool:
        if not self.enabled():
            return False
        self.battles += 1
        left = self.every() - self.battles
        if left > 0:
            log(f"👥 Changement de compte dans {left} combat(s)")
            return False
        self.battles = 0
        return True


def read_player_name(game: Game, screen=None) -> str | None:
    screen = game.grab() if screen is None else screen
    zone, _, _ = vision.crop(screen, layout.PLAYER_NAME_BOX)
    lines = ocr.ocr_lines(ocr.read_text(zone, detail=True))
    return lines[0][1] if lines else None


def account_rows(game: Game, screen) -> list[tuple[int, str, str]]:
    """Cases visibles du panneau SWITCH ID : [(y, nom Supercell ID, pseudo du jeu)]."""
    zone, ox, oy = vision.crop(screen, layout.ACCOUNT_LIST_BOX)
    lines = ocr.ocr_lines(ocr.read_text(zone, detail=True), max_gap=30)
    lines = [(y + oy, t) for y, t in lines if not re.search(r"town\s*hall|other\s*ids", t, re.I)]
    rows = []
    i = 0
    while i < len(lines):
        y, bold = lines[i]
        pseudo = lines[i + 1][1] if i + 1 < len(lines) and lines[i + 1][0] - y < 40 else ""
        rows.append((y, bold, pseudo))
        i += 2 if pseudo else 1
    return rows


def open_account_panel(game: Game) -> bool:
    game.click_box(layout.ACCOUNT_PORTRAIT_BOX)
    game.sleep(1.2)
    game.click_box(layout.ACCOUNT_SETTINGS_TAB)
    game.sleep(0.8)
    m = game.wait("account_switch", 5, layout.ACCOUNT_SWITCH_BOX, stable=True)
    if not m:
        log("👥 Bouton Supercell ID introuvable")
        close_windows(game)
        return False
    game.click_match(m)
    if not game.wait("account_switch_id", 8):
        log("👥 Panneau Supercell ID pas ouvert")
        close_windows(game)
        return False
    game.sleep(0.6)
    return True


def close_windows(game: Game) -> None:
    for _ in range(2):
        game.close_window()
    game.wait_village(8)


def find_row(game: Game, name: str, kind: str) -> int | None:
    """Ordonnée de la case du compte, en faisant glisser la liste (bas puis haut)."""
    x = layout.ACCOUNT_ROW_X
    for direction in (-1, 1):
        prev = None
        for _ in range(8):
            screen = game.wait_still(layout.ACCOUNT_LIST_BOX, 2.5)
            best, best_y = 0.0, None
            for y, bold, pseudo in account_rows(game, screen):
                s = player_name_score(name, bold if kind == "scid" else (pseudo or bold))
                if s > best:
                    best, best_y = s, y
            if best >= 0.75:
                return best_y
            zone, _, _ = vision.crop(screen, layout.ACCOUNT_LIST_BOX)
            if prev is not None and vision.same_image(prev, zone):
                break
            prev = zone.copy()
            y1, y2 = (900, 600) if direction == -1 else (600, 900)
            game.drag(x, y1, x, y2, 0.45)
    return None


def wait_account_loaded(game: Game, timeout: float = 60) -> bool:
    end = time.monotonic() + timeout
    hidden_seen = False
    while time.monotonic() < end:
        screen = game.grab()
        visible = game.battle_button_visible(screen)
        if not visible:
            hidden_seen = True
        m = game.find("welcome_okay", screen)
        if m:
            game.click_match(m)
            log("👥 « Welcome Back Chief! » → Okay")
        elif visible and hidden_seen:
            game.sleep(2.0)
            m = game.find("welcome_okay")
            if m:
                game.click_match(m)
            return True
        game.state.sleep(0.8)
    return False


def switch_account(game: Game, name: str, kind: str = "game") -> bool:
    log(f"👥 Changement de compte → {name}")
    if not open_account_panel(game):
        return False
    y = find_row(game, name, kind)
    if y is None:
        log(f"👥 Compte « {name} » introuvable dans la liste")
        close_windows(game)
        return False
    game.click(layout.ACCOUNT_ROW_X, y)
    if not wait_account_loaded(game):
        log("👥 Chargement du compte jamais terminé")
        return False
    shown = read_player_name(game)
    if shown and kind == "game" and player_name_score(shown, name) < 0.5:
        log(f"⚠️ Pseudo lu « {shown} » ≠ « {name} »")
    game.state.current_account = name
    return True


def switch_to_next(game: Game, accset: AccountSet, mode: str, apply_profile) -> bool:
    """Compte suivant de la liste + son profil ; échec = on reste sur le compte actuel."""
    accounts = accset.accounts()
    names = [n for n, _ in accounts]
    current = closest_name(game.state.current_account or read_player_name(game) or "", names)
    idx = names.index(current) if current in names else -1
    name, profile = accounts[(idx + 1) % len(accounts)]
    if not switch_account(game, name, accset.data.get("name_kind", "game")):
        return False
    if profile:
        apply_profile(profile)
    if game.village() not in (None, mode):
        travel_to_village(game, mode)
    return True
