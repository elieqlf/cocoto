"""Raids de la Capitale de clan : pendant le Raid Weekend (vendredi 7 h UTC → lundi 7 h UTC), au START,
le bot fait toutes les attaques de raid du compte (5, +1 bonus quand un district tombe), district
le plus bas d'abord, puis farme dans le mode choisi. Il ne lance jamais le raid du clan."""
from __future__ import annotations

import datetime as dt
import random
import re
import time

import cv2
import numpy as np

from .. import layout, ocr, vision
from ..game import Game
from ..logger import log
from .attack import card_alive, find_cards, is_spell_card

AIRSHIP_KEYS = ("capital_airship_inner", "capital_airship", "capital_airship_grey")


def raid_weekend_id(now: dt.datetime | None = None) -> str | None:
    now = now or dt.datetime.now(dt.timezone.utc)
    friday = (now - dt.timedelta(days=(now.weekday() - 4) % 7)).replace(hour=7, minute=0, second=0, microsecond=0)
    if now < friday:
        friday -= dt.timedelta(days=7)
    if now < friday + dt.timedelta(days=3):
        return friday.date().isoformat()
    return None


def capital_view(screen) -> str | None:
    text = ocr.read_box_text(screen, layout.CAPITAL_TITLE_BOX).lower()
    if "capital" in text:
        return "capital"
    if "raid" in text or "map" in text:
        return "raid_map"
    return None


def raid_button_state(screen) -> str | None:
    text = ocr.read_box_text(screen, layout.RAID_BUTTON_BOX).lower()
    if "start" in text:
        return "not_started"
    if "raid" in text or "map" in text or "info" in text:
        return "active"
    return None


def attacks_left(screen) -> int:
    x, y = layout.RAID_ATTACKS_BADGE
    text = ocr.read_box_text(screen, (x - 25, y - 25, x + 25, y + 25), allowlist="0123456789")
    return int(text) if text.isdigit() else 0


def open_capital(game: Game) -> bool:
    """Du village : dirigeable (en bas du village) → Capitale."""
    game.zoom_out()
    cx, cy = layout.SCREEN_CENTER
    game.drag(cx, cy + 200, cx, cy - 200, 0.5)
    game.sleep(0.5)
    screen = game.grab()
    for key in AIRSHIP_KEYS:
        m = game.find(key, screen, scales=(0.8, 0.9, 1.0, 1.1, 1.2))
        if m:
            game.click_match(m)
            end = time.monotonic() + 25
            while time.monotonic() < end:
                game.state.sleep(1.0)
                if capital_view(game.grab()) == "capital":
                    return True
            return False
    log("⚔️ Raids : dirigeable introuvable")
    return False


def leave_capital(game: Game) -> None:
    for word in ("map", "return home"):
        screen = game.grab()
        for y, text in ocr.ocr_lines(ocr.read_text(screen[900:1080, 0:400], detail=True)):
            if word in text.lower():
                game.click(150, 900 + y)
                game.sleep(1.5)
                break
    game.wait_village(30)


def read_districts(screen) -> list[dict]:
    """Districts de la carte du raid : [{name, x, y, pct}]."""
    res = ocr.read_text(screen, detail=True)
    out = []
    for box, text, *_ in res:
        name = next((d for d in layout.RAID_DISTRICTS if d.lower()[:6] in text.lower()), None)
        if not name:
            continue
        xs, ys = [p[0] for p in box], [p[1] for p in box]
        x, y = int(sum(xs) / 4), int(sum(ys) / 4)
        pct = None
        for b2, t2, *_ in res:
            m = re.search(r"(\d{1,3})\s*%", t2)
            if m and abs(sum(p[0] for p in b2) / 4 - x) < 120 and 0 < sum(p[1] for p in b2) / 4 - y < 90:
                pct = int(m.group(1))
        out.append({"name": name, "x": x, "y": y, "pct": pct})
    return out


def deploy_zone_points(screen, n: int) -> list[tuple[int, int]]:
    """Points dans la zone de pose (herbe éclaircie par le voile blanc pendant « Battle starts in »)."""
    h = cv2.cvtColor(screen, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(h, np.array((30, 20, 170), np.uint8), np.array((85, 120, 255), np.uint8))
    mask[layout.ARMY_BAR_Y[0] - 20:, :] = 0
    mask[:150, :] = 0
    ys, xs = np.nonzero(mask)
    if len(xs) < 100:
        return [(random.randint(600, 1300), random.randint(650, 850)) for _ in range(n)]
    idx = np.argsort(ys)[: max(n * 20, 200)]          # vers le haut de la zone = vers le district
    picks = np.random.choice(idx, size=min(n, len(idx)), replace=len(idx) < n)
    return [(int(xs[i]), int(ys[i])) for i in picks]


def attack_once(game: Game, district: dict) -> int | None:
    """Une attaque depuis la carte du raid. Joyaux gagnés, ou None si impossible."""
    game.click(district["x"], district["y"])
    btn = game.wait_any(("raid_attack_now", "raid_attack_scout", "raid_go"), timeout=6)
    if not btn:
        return None
    game.click_match(btn[1])
    if btn[0] == "raid_attack_scout":
        go = game.wait("raid_attack_now", 6, stable=True)
        if not go:
            return None
        game.click_match(go)
    if not game.wait("raid_battle_starts", 30):
        return None
    screen = game.grab()
    for left, right in find_cards(screen):
        x = (left + right) // 2
        spell = is_spell_card(screen, left, right)
        game.click(x, layout.ARMY_CARD_Y)
        for _ in range(15):
            pts = [(random.randint(600, 1300), random.randint(250, 500))] if spell else deploy_zone_points(screen, 3)
            for px, py in pts:
                game.click(px, py, jitter=3, delay=(0.15, 0.3))
            if not card_alive(game.grab(), x):
                break
    end = game.wait("raid_map_end", 240)
    if not end:
        return None
    screen = game.grab()
    gained = ocr.read_amount(screen, (760, 470, 1160, 560)) or 0
    game.click_match(end)
    game.sleep(2.0)
    return gained


def run_capital_raids(game: Game, state_store: dict) -> int:
    """Toutes les attaques de raid du compte, depuis le village ; retour au village à la fin."""
    weekend = raid_weekend_id()
    if not weekend or state_store.get("done") == weekend:
        return 0
    if not open_capital(game):
        return 0
    gained_total = 0
    try:
        screen = game.grab()
        if raid_button_state(screen) == "not_started":
            log("⚔️ Raids : raid pas lancé par le clan → rien à faire")
            return 0
        left = attacks_left(screen)
        game.click_box(layout.RAID_BUTTON_BOX)
        game.sleep(2.0)
        skipped: set[str] = set()
        for _ in range(max(left, 1) + 1):
            game.state.check()
            districts = [d for d in read_districts(game.grab())
                         if d["name"] not in skipped and (d["pct"] is None or d["pct"] < 100)]
            if not districts:
                break
            order = list(layout.RAID_DISTRICTS)
            d = sorted(districts, key=lambda d: (d["y"] * -1, order.index(d["name"])))[0]
            log(f"⚔️ Raid sur {d['name']} ({d['pct']}%)")
            gained = attack_once(game, d)
            if gained is None:
                skipped.add(d["name"])
                continue
            gained_total += gained
            game.state.add("raids", 1)
            game.state.add("capital", gained)
        state_store["done"] = weekend
    finally:
        leave_capital(game)
    log(f"⚔️ Raids terminés : +{gained_total} or de capitale")
    return gained_total
