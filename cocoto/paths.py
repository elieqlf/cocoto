"""Emplacements des fichiers : ressources (templates), données utilisateur, instance."""
from __future__ import annotations

import os
import sys

APP_NAME = "Cocoto"
VERSION = "1.0.0"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def parse_instance(argv=None) -> int:
    """Numéro d'instance (--instance N), 1 par défaut. Une instance = un émulateur / un compte."""
    argv = sys.argv if argv is None else argv
    if "--instance" in argv:
        try:
            return max(1, int(argv[argv.index("--instance") + 1]))
        except (IndexError, ValueError):
            return 1
    return 1


INSTANCE = parse_instance()


def assets_dir() -> str:
    env = os.environ.get("COCOTO_ASSETS")
    if env:
        return env
    base = getattr(sys, "_MEIPASS", ROOT)
    return os.path.join(base, "assets")


def asset(*parts: str) -> str:
    return os.path.join(assets_dir(), *parts)


def img_dir() -> str:
    return asset("img")


def user_dir() -> str:
    """Profils, réglages, journaux. %APPDATA%\\Cocoto sous Windows, ~/.cocoto ailleurs.
    Chaque instance > 1 a son sous-dossier (réglages et profils séparés)."""
    env = os.environ.get("COCOTO_DATA")
    if env:
        base = env
    elif os.name == "nt" and os.environ.get("APPDATA"):
        base = os.path.join(os.environ["APPDATA"], APP_NAME)
    else:
        base = os.path.join(os.path.expanduser("~"), ".cocoto")
    if INSTANCE > 1:
        base = os.path.join(base, f"instance_{INSTANCE}")
    os.makedirs(base, exist_ok=True)
    return base


def data_path(name: str) -> str:
    return os.path.join(user_dir(), name)


def shared_dir(name: str) -> str:
    """Dossier commun à toutes les instances (tableau de bord)."""
    base = os.environ.get("COCOTO_DATA")
    if not base:
        if os.name == "nt" and os.environ.get("APPDATA"):
            base = os.path.join(os.environ["APPDATA"], APP_NAME)
        else:
            base = os.path.join(os.path.expanduser("~"), ".cocoto")
    path = os.path.join(base, name)
    os.makedirs(path, exist_ok=True)
    return path
