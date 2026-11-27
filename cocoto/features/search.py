"""Lancement d'un combat : Battle → (Ranked) → Find a Match → My Army (Cake, renforts) → Attack!
puis écran de scout : lecture du loot disponible, Next tant qu'il est sous les seuils."""
from __future__ import annotations

import re
import time

from .. import humanize, layout, ocr, vision
from ..config import LiveConfig
from ..game import Game
from ..logger import log
from ..parsing import parse_amount


class SearchFailed(Exception):
    """Un bouton attendu n'est jamais apparu : le bot s'arrête (avec message à l'utilisateur)."""


def click_battle(game: Game) -> None:
    x, y = humanize.point_in_box(layout.BATTLE_BUTTON)
    log(f"⚔️ Battle ({x}, {y})")
    game.click(x, y, jitter=0)
    game.sleep(0.6)


def click_launch_button(game: Game, key: str, label: str, timeout: float = 12.0, box=None) -> bool:
    """Attend le bouton (vu au même endroit 2 fois) puis clique un point au hasard dedans."""
    m = game.wait(key, timeout, box=box, stable=True)
    if not m:
        log(f"⚠️ Bouton « {label} » introuvable")
        return False
    x1, y1, x2, y2 = m.box
    game.click_box((x1, y1, x2, y2), margin=0.25)
    log(f"🖱️ {label}")
    game.sleep(0.5)
    return True


# ---------------------------------------------------------------- Ranked
def ranked_limit(text: str) -> int | None:
    """Nombre d'attaques Ranked à atteindre au compteur : None = toutes, -1 = champ invalide."""
    t = (text or "").strip().lower()
    if t in ("", "all", "tout", "toutes", "off"):
        return None
    return int(t) if t.isdigit() else -1


RANKED_SIDE = (layout.RANKED_FIND_MATCH_MIN_X, 0, 1920, 1080)
NORMAL_SIDE = (0, 0, layout.RANKED_FIND_MATCH_MIN_X, 1080)


def ranked_find_match(game: Game, screen):
    """« Find a Match » de la carte Ranked Battle : même template, partie gauche masquée."""
    return game.find("find_match", screen, box=RANKED_SIDE)


def read_ranked_attacks(game: Game, screen) -> tuple[int, int] | None:
    """Compteur « 8/18 » de la carte Ranked Battle, sinon None."""
    m = ranked_find_match(game, screen)
    if not m:
        return None
    dx1, dy1, dx2, dy2 = layout.RANKED_COUNTER_DBOX
    box = (m.x + dx1, m.y + dy1, m.x + dx2, m.y + dy2)
    zone, _, _ = vision.crop(screen, box)
    if zone.size == 0:
        return None
    # chiffres jaune pâle (S≈90, V≈225) sur orange (S≈210) : isolés en noir sur blanc avant l'OCR
    img, _n = ocr.prepare_digits(zone, v_min=180, s_max=130, scale=2.0)
    text = "".join(ocr.read_text(img, allowlist="0123456789/"))
    mm = re.search(r"(\d{1,2})\s*/\s*(\d{1,2})", text)
    return (int(mm.group(1)), int(mm.group(2))) if mm else None


def start_ranked_search(game: Game, cfg: LiveConfig) -> bool:
    """Panneau Battle ouvert : Find a Match du Ranked s'il reste des attaques au tournoi."""
    if not cfg.flag("ranked"):
        return False
    screen = game.wait_still(None, timeout=2)
    counter = read_ranked_attacks(game, screen)
    if counter is None:
        log("🏆 Ranked : carte absente ou illisible → combat normal")
        return False
    used, total = counter
    limit = ranked_limit(cfg.text("ranked_max"))
    target = total if limit in (None, -1) else min(limit, total)
    if used >= target:
        log(f"🏆 Ranked : {used}/{total} (objectif {target}) → combat normal")
        return False
    m = ranked_find_match(game, screen)
    if not m:
        return False
    game.click_match(m)
    log(f"🏆 Ranked : attaque {used + 1}/{total}")
    return True


def ranked_confirm_and_wait(game: Game) -> bool:
    m = game.wait("ranked_confirm_attack", 8, stable=True)
    if m:
        game.click_match(m)
    return game.wait("battle_surrender", 40) is not None


# ---------------------------------------------------------------- My Army
def use_cake(game: Game) -> None:
    m = game.find("cake")
    if not m:
        log("🎂 Cake non détecté")
        return
    game.click_match(m)
    conf = game.wait("confcake", 4, stable=True)
    if conf:
        game.click_match(conf)
        log("🎂 Cake utilisé (château de clan rempli)")


def request_reinforcements(game: Game) -> bool:
    """Request → Send si le bouton est disponible (pas en attente, château pas plein)."""
    m = game.find("army_request")
    if not m:
        log("🏰 Renforts : bouton Request pas disponible")
        return False
    game.click_match(m)
    if not game.wait("request_title", 4):
        game.close_window()
        return False
    send = game.wait("request_send", 4, stable=True)
    if send:
        game.click_match(send)
        log("🏰 Renforts demandés")
        game.sleep(0.8)
        return True
    game.close_window()
    return False


def launch_attack(game: Game, cfg: LiveConfig) -> bool:
    """Du village jusqu'à la base ennemie. True = combat Ranked (pas de scout)."""
    click_battle(game)
    ranked = start_ranked_search(game, cfg)
    # combat normal : uniquement le bouton de la carte Battle (jamais celui du Ranked)
    if not ranked and not click_launch_button(game, "find_match", "Find a Match", box=NORMAL_SIDE):
        raise SearchFailed("le bouton « Find a Match » n'est pas apparu")
    if not game.wait("army_attack", 12, stable=True):
        raise SearchFailed("le bouton « Attack! » de My Army n'est pas apparu")
    if cfg.flag("cake_enabled"):
        use_cake(game)
    if cfg.flag("request_cc"):
        request_reinforcements(game)
    if not click_launch_button(game, "army_attack", "Attack!"):
        raise SearchFailed("le bouton « Attack! » de My Army n'est pas apparu")
    if ranked:
        if not ranked_confirm_and_wait(game):
            raise SearchFailed("le combat Ranked n'a pas démarré")
    return ranked


# ---------------------------------------------------------------- scout
def read_available_loot(game: Game, screen=None) -> list[int | None]:
    screen = screen if screen is not None else game.grab()
    x1, x2 = layout.AVAILABLE_LOOT_X
    return [ocr.read_amount(screen, (x1, y1, x2, y2)) for (y1, y2) in layout.AVAILABLE_LOOT_ROWS.values()]


def scout_loot(game: Game) -> list[int]:
    """Loot disponible (haut à gauche), relu jusqu'à 3 fois si un montant est illisible."""
    vals: list[int | None] = [None, None, None]
    for _ in range(3):
        vals = read_available_loot(game)
        if vals[0] is not None and vals[1] is not None:
            break
        game.sleep(0.6)
    return [v or 0 for v in vals]


def thresholds(cfg: LiveConfig) -> list[int]:
    return [parse_amount(cfg.text(k)) or 0 for k in ("gold", "elixir", "dark")]


def find_target(game: Game, cfg: LiveConfig, max_next: int = 300) -> list[int]:
    """Attend une base (bouton Next), Next tant que le loot est sous les seuils. Retourne le loot."""
    for n in range(max_next):
        game.state.check()
        if not game.wait("end", 60, threshold=0.8):
            raise SearchFailed("aucune base trouvée après la recherche (réseau, popup ?)")
        game.sleep(0.4)
        loot = scout_loot(game)
        g, e, d = thresholds(cfg)
        ok = loot[0] >= g and loot[1] >= e and loot[2] >= d
        log(f"🔎 Base {n + 1} : or {loot[0]:,} élixir {loot[1]:,} noir {loot[2]:,} | seuils {g:,}/{e:,}/{d:,}"
            .replace(",", " "))
        if ok:
            return loot
        game.click_box(layout.NEXT_BUTTON)
        game.sleep(1.2)
    raise SearchFailed("trop de bases passées sans loot suffisant")
