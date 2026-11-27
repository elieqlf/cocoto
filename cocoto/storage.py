"""Fichiers JSON (écriture atomique + .bak), réglages globaux, profils et codes de partage."""
from __future__ import annotations

import base64
import copy
import json
import os
import re
import threading
import zlib
from typing import Any, Callable

from . import paths

_lock = threading.RLock()


# --------------------------------------------------------------------------- JSON sûr
def write_json_safely(path: str, data: Any, **kwargs) -> None:
    """Fichier temporaire + fsync + remplacement : une coupure laisse l'ancien fichier intact.
    L'ancienne version est gardée en .bak (relue si le fichier principal est abîmé)."""
    kwargs.setdefault("indent", 2)
    kwargs.setdefault("ensure_ascii", False)
    tmp = path + ".tmp"
    with _lock:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, **kwargs)
            f.flush()
            os.fsync(f.fileno())
        if os.path.exists(path):
            try:
                import shutil
                shutil.copy2(path, path + ".bak")
            except OSError:
                pass
        os.replace(tmp, path)


def read_json_safely(path: str, default: Any = None) -> Any:
    for candidate in (path, path + ".bak"):
        if not os.path.exists(candidate):
            continue
        try:
            with open(candidate, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            continue
    return copy.deepcopy(default)


# --------------------------------------------------------------------------- réglages globaux
SETTINGS_FILE = "settings.json"

GLOBAL_DEFAULTS: dict[str, Any] = {
    "language": "fr",
    "theme": "clash_gold",
    "theme_colors": {"background": "#1a1410", "accent": "#F5B83D"},
    "backend": "screen",            # screen | window | adb
    "adb_path": "",
    "adb_device": "",
    "desktop_notify": False,
    "webhook": "",
    "discord_id": "",
    "remote_enabled": False,
    "remote_token": "",
    "remote_user_id": "",
    "accounts": {"enabled": False, "every": "3", "names": [], "profiles": [], "name_kind": "game"},
    "accounts_bh": {"enabled": False, "every": "3", "names": [], "profiles": [], "name_kind": "game"},
    "ingame_names": {},
    "donate_free_units": [],
    "active_profile_th": "",
    "active_profile_bh": "",
    "mode": "TH",
}


class Settings:
    """Réglages hors profil (langue, thème, moteur d'entrée, comptes, Discord…)."""

    def __init__(self, path: str | None = None):
        self.path = path or paths.data_path(SETTINGS_FILE)
        data = read_json_safely(self.path, {}) or {}
        self.data = copy.deepcopy(GLOBAL_DEFAULTS)
        self.data.update(data)
        self._listeners: list[Callable[[str, Any], None]] = []

    def get(self, key: str, default: Any = None) -> Any:
        with _lock:
            return copy.deepcopy(self.data.get(key, default))

    def set(self, key: str, value: Any, save: bool = True) -> None:
        with _lock:
            self.data[key] = value
            if save:
                write_json_safely(self.path, self.data)
        for cb in list(self._listeners):
            try:
                cb(key, value)
            except Exception:
                pass

    def on_change(self, cb: Callable[[str, Any], None]) -> None:
        self._listeners.append(cb)


# --------------------------------------------------------------------------- profils
class ProfileStore:
    """Profils d'un mode (TH = config.json, BH = config_bh.json) : {nom: réglages}."""

    def __init__(self, mode: str, path: str | None = None):
        self.mode = mode
        self.path = path or paths.data_path("config.json" if mode == "TH" else "config_bh.json")

    def all(self) -> dict[str, dict]:
        data = read_json_safely(self.path, {}) or {}
        return data if isinstance(data, dict) else {}

    def names(self) -> list[str]:
        return sorted(self.all().keys(), key=str.lower)

    def load(self, name: str) -> dict | None:
        return copy.deepcopy(self.all().get(name))

    def save(self, name: str, cfg: dict) -> None:
        with _lock:
            data = self.all()
            data[name] = cfg
            write_json_safely(self.path, data)

    def delete(self, name: str) -> bool:
        with _lock:
            data = self.all()
            if name not in data:
                return False
            del data[name]
            write_json_safely(self.path, data)
            return True

    def rename(self, old: str, new: str) -> bool:
        with _lock:
            data = self.all()
            if old not in data or new in data or not new.strip():
                return False
            data[new] = data.pop(old)
            write_json_safely(self.path, data)
            return True


# --------------------------------------------------------------------------- codes de partage
PROFILE_CODE_MAX_BYTES = 100_000
CODE_RE = re.compile(r"COCO-(TH|BH)-([A-Za-z0-9+/]+)")


def _clean_value(value: Any, depth: int = 0) -> Any:
    """Seulement des valeurs simples : un code trafiqué ne peut rien injecter d'autre."""
    if depth > 4:
        return None
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        return value[:300]
    if isinstance(value, dict):
        out = {}
        for k, v in list(value.items())[:500]:
            if isinstance(k, str):
                cv = _clean_value(v, depth + 1)
                if cv is not None or v is None:
                    out[k[:120]] = cv
        return out
    if isinstance(value, list):
        return [_clean_value(v, depth + 1) for v in value[:120]]
    return None


def _without_private(value: Any, private: list[str]) -> Any:
    """Retire les textes privés (égaux, ou contenus s'ils font 4 caractères ou plus)."""
    if isinstance(value, str):
        low = value.lower()
        for p in private:
            pl = p.lower()
            if pl and (low == pl or (len(pl) >= 4 and pl in low)):
                return None
        return value
    if isinstance(value, dict):
        kept = {}
        for k, v in value.items():
            nv = _without_private(v, private)
            if nv is not None or v is None:
                kept[k] = nv
        return kept
    if isinstance(value, list):
        return [x for x in (_without_private(v, private) for v in value) if x is not None]
    return value


def profile_to_code(mode: str, cfg: dict, private: list[str] | None = None) -> str:
    data = _without_private(_clean_value(cfg), [p for p in (private or []) if p])
    raw = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    packed = base64.b64encode(zlib.compress(raw, 9)).decode("ascii").rstrip("=")
    return f"COCO-{mode}-{packed}"


def profile_from_code(text: str) -> tuple[str, dict]:
    match = CODE_RE.search((text or "").replace("\n", "").replace(" ", ""))
    if not match:
        raise ValueError("Ce n'est pas un code de profil (il commence par COCO-TH- ou COCO-BH-).")
    mode, packed = match.group(1), match.group(2)
    try:
        raw_b = base64.b64decode(packed + "=" * (-len(packed) % 4))
        d = zlib.decompressobj()
        raw = d.decompress(raw_b, PROFILE_CODE_MAX_BYTES)
        if d.unconsumed_tail:
            raise ValueError("trop gros")
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ValueError("Ce code est incomplet ou abîmé. Recopie-le en entier.") from exc
    profile = _clean_value(data)
    if not isinstance(profile, dict) or "slots" not in profile:
        raise ValueError("Ce code ne contient pas d'armée.")
    return mode, profile
