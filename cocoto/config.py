"""Réglages d'un profil (TH = village principal, BH = base des ouvriers) et accès thread-safe.

L'interface écrit dans LiveConfig ; le bot y relit chaque valeur au moment de l'action
(un changement pendant que le bot tourne est donc pris en compte tout de suite)."""
from __future__ import annotations

import copy
import threading
from typing import Any, Callable

HERO_KEYS = ("hero1", "hero2", "hero3", "hero4", "hero5", "hero6")
HERO_NAMES = ("Barbarian King", "Archer Queen", "Grand Warden", "Royal Champion",
              "Minion Prince", "Dragon Duke")
BH_HERO_KEYS = ("machine", "copter")
BH_HERO_NAMES = {"machine": "Battle Machine", "copter": "Battle Copter"}

TH_DEFAULTS: dict[str, Any] = {
    # armée
    "slots": "auto",           # "auto" ou numéros de cartes « 1 2 3 4 »
    "number": "",              # nombre de clics par slot « 10 10 5 5 »
    "spell": "",               # slots de sorts « 9 10 »
    "deploy_spread": "0",      # espacement des troupes en %
    # loot minimum au scout
    "gold": "300000", "elixir": "300000", "dark": "0",
    "early_end": "",           # « 120s 50% 60d 20f »
    # village
    "click_wall_enabled": False, "wall_cost": "", "wall_fill": "",
    "collect_enabled": True, "treasure_enabled": False, "cake_enabled": False,
    "request_cc": False, "clan_games": False, "donate": False,
    "stop_when_full": False, "stop_full_kinds": "gold elixir", "bh_when_full": False,
    "suggested_upgrades": False, "suggested_heroes": False, "keep_builder_walls": False,
    "ranked": False, "ranked_max": "", "raids": False,
    # temps
    "breaks_enabled": False, "break_play": "40-70", "break_pause": "10-25", "break_closed": "",
    "schedule_enabled": False, "schedule_hours": "9-12 14-23",
    "battle_delay": "",        # « 5-20 » secondes entre deux combats
    # héros : {hero1: {enabled, delay}}
    "heroes": {k: {"enabled": False, "delay": "0"} for k in HERO_KEYS},
    "upgrades": {},            # {"Defense|Cannon": {"enabled": bool, "count": "1", "price": "", "resource": "gold"}}
    "lab": {},                 # {"Lab|Barbarian": {...}}
}

BH_DEFAULTS: dict[str, Any] = {
    "slots": "auto", "number": "", "click_start": False,
    "click_wall_enabled": False, "wall_cost": "",
    "collect_enabled": True,
    "breaks_enabled": False, "break_play": "40-70", "break_pause": "10-25", "break_closed": "",
    "schedule_enabled": False, "schedule_hours": "9-12 14-23",
    "battle_delay": "",
    "heroes": {"machine": {"enabled": True, "level": "1"}, "copter": {"enabled": True, "level": "1"}},
    "upgrades": {}, "lab": {},
}

# clés partagées dans un code de profil (jamais pseudo, webhook, ID ou clé)
PROFILE_CODE_KEYS = {
    "TH": tuple(k for k in TH_DEFAULTS),
    "BH": tuple(k for k in BH_DEFAULTS),
}


def defaults(mode: str) -> dict[str, Any]:
    return copy.deepcopy(TH_DEFAULTS if mode == "TH" else BH_DEFAULTS)


def merged(mode: str, cfg: dict | None) -> dict[str, Any]:
    """Profil complété avec les valeurs par défaut (anciens profils, codes partiels)."""
    out = defaults(mode)
    for k, v in (cfg or {}).items():
        if k == "heroes" and isinstance(v, dict):
            for hk, hv in v.items():
                if isinstance(hv, dict):
                    out["heroes"].setdefault(hk, {}).update(hv)
        else:
            out[k] = v
    return out


class LiveConfig:
    """Valeurs courantes d'un mode, lues par le bot et modifiées par l'UI / le contrôle à distance."""

    def __init__(self, mode: str, values: dict | None = None):
        self.mode = mode
        self._lock = threading.RLock()
        self._v = merged(mode, values)
        self._listeners: list[Callable[[str, Any], None]] = []

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return copy.deepcopy(self._v.get(key, default))

    def __getitem__(self, key: str) -> Any:
        return self.get(key)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._v[key] = value
        for cb in list(self._listeners):
            try:
                cb(key, value)
            except Exception:
                pass

    def update(self, values: dict) -> None:
        for k, v in values.items():
            self.set(k, v)

    def replace(self, values: dict) -> None:
        with self._lock:
            self._v = merged(self.mode, values)
        for cb in list(self._listeners):
            try:
                cb("*", None)
            except Exception:
                pass

    def snapshot(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._v)

    def on_change(self, cb: Callable[[str, Any], None]) -> None:
        self._listeners.append(cb)

    # aides de lecture
    def flag(self, key: str) -> bool:
        v = self.get(key)
        if isinstance(v, str):
            return v.strip().lower() in ("1", "true", "on", "yes", "oui")
        return bool(v)

    def text(self, key: str) -> str:
        v = self.get(key)
        return "" if v is None else str(v).strip()

    def number(self, key: str, default: int = 0) -> int:
        from .parsing import parse_amount
        v = parse_amount(self.text(key))
        return default if v is None else v

    def hero(self, key: str) -> dict:
        return dict(self.get("heroes", {}).get(key, {}))
