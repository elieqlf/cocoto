"""Thèmes de l'interface : 3 palettes prêtes + thème perso calculé à partir de 2 couleurs.

`C` contient les 12 couleurs de base d'un thème (KEYS) et des couleurs dérivées calculées par
`_derive` (survol des cartes, séparateurs, texte sur l'accent…), pour que tout le code de l'UI
n'utilise que ces jetons."""
from __future__ import annotations

import re

KEYS = ("BG", "CARD", "CARD_LIGHT", "BORDER", "ENTRY_BG", "GOLD", "GOLD_HOVER", "GOLD_DARK",
        "TEXT", "MUTED", "SWITCH_OFF", "PLACEHOLDER")
THEMES = {
    "clash_gold": ("Clash Gold", ("#14110e", "#1f1a15", "#2b241c", "#3d3226", "#110e0b", "#F5B83D",
                                  "#FFC95E", "#C8912B", "#F4ECDD", "#A8987F", "#3a3027", "#6b5d4b")),
    "builder_night": ("Builder Night", ("#0d1220", "#151d31", "#1e2942", "#2d3b5e", "#0a0e19", "#5AB4FF",
                                        "#80C6FF", "#2E78C8", "#E6ECFA", "#8f9dbd", "#283350", "#56648a")),
    "dark_elixir": ("Dark Elixir", ("#100c14", "#1b1421", "#271d31", "#3c2b4e", "#0c080f", "#B57CFF",
                                    "#C899FF", "#7C4CC4", "#EEE6F7", "#a394b5", "#32263e", "#62537a")),
}
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
GREEN, GREEN_HOVER, RED, RED_HOVER = "#2f9e48", "#38b555", "#d9443a", "#ee5a4f"
AMBER, BLUE = "#d08f1f", "#3d8bd9"
ELIXIR_COLOR, DARK_COLOR, CAPITAL_COLOR = "#e36bff", "#9b8cff", "#ffb347"

C: dict[str, str] = {}


def _rgb(c: str) -> tuple[int, int, int]:
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]


def mix(c1: str, c2: str, t: float) -> str:
    a, b = _rgb(c1), _rgb(c2)
    return "#%02x%02x%02x" % tuple(int(x + (y - x) * t) for x, y in zip(a, b))


def luminance(c: str) -> float:
    r, g, b = _rgb(c)
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


def _derive() -> None:
    """Couleurs secondaires calculées à partir du thème courant."""
    C["ON_ACCENT"] = "#1a1410" if luminance(C["GOLD"]) > 0.5 else "#ffffff"
    C["CARD_HOVER"] = mix(C["CARD_LIGHT"], C["BORDER"], 0.6)
    C["DIVIDER"] = mix(C["CARD"], C["BORDER"], 0.55)
    C["ACCENT_SOFT"] = mix(C["CARD"], C["GOLD"], 0.16)
    C["NAV_BG"] = mix(C["BG"], C["CARD"], 0.6)


def build_custom(background: str, accent: str) -> dict[str, str]:
    """Palette complète à partir du fond et de l'accent (fond clair accepté : cartes plus sombres)."""
    light = luminance(background) > 0.55
    far, near = ("#000000", "#ffffff") if light else ("#ffffff", "#000000")
    text = "#151515" if light else "#f3f3f3"
    return {
        "BG": background, "CARD": mix(background, far, 0.05), "CARD_LIGHT": mix(background, far, 0.10),
        "BORDER": mix(mix(background, far, 0.16), accent, 0.15), "ENTRY_BG": mix(background, near, 0.25),
        "GOLD": accent, "GOLD_HOVER": mix(accent, "#ffffff", 0.2), "GOLD_DARK": mix(accent, "#000000", 0.25),
        "TEXT": text, "MUTED": mix(text, background, 0.38), "SWITCH_OFF": mix(background, far, 0.2),
        "PLACEHOLDER": mix(text, background, 0.6),
    }


def apply(name: str, custom: dict | None = None) -> None:
    if name == "custom" and custom and HEX_RE.match(custom.get("background", "")) \
            and HEX_RE.match(custom.get("accent", "")):
        C.update(build_custom(custom["background"], custom["accent"]))
    else:
        C.update(dict(zip(KEYS, THEMES.get(name, THEMES["clash_gold"])[1])))
    _derive()


apply("clash_gold")
