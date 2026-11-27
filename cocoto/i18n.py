"""Textes en anglais ou en français (choisis au moment de l'affichage)."""
from __future__ import annotations

LANG = "fr"
LANGUAGES = {"en": "English", "fr": "Français"}


def set_language(lang: str) -> None:
    global LANG
    LANG = lang if lang in LANGUAGES else "en"


def tr(en: str, fr: str | None = None) -> str:
    return fr if (LANG == "fr" and fr) else en
