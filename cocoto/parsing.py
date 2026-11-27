"""Lecture des champs texte de l'interface (fonctions pures, testées dans tests/)."""
from __future__ import annotations

import random
import re
from dataclasses import dataclass


def parse_amount(text: str | None) -> int | None:
    """« 400000 », « 400k », « 1.5m », « 1 500 000 », « 1,5M » → entier ; None si illisible / vide."""
    if text is None:
        return None
    t = str(text).strip().lower().replace("_", "").replace(" ", "").replace(" ", "")
    if not t:
        return None
    mult = 1
    if t.endswith("k"):
        mult, t = 1_000, t[:-1]
    elif t.endswith("m"):
        mult, t = 1_000_000, t[:-1]
    elif t.endswith("b"):
        mult, t = 1_000_000_000, t[:-1]
    if mult > 1:
        t = t.replace(",", ".")
        try:
            return int(round(float(t) * mult))
        except ValueError:
            return None
    t = t.replace(",", "").replace(".", "")
    return int(t) if t.isdigit() else None


def digits_to_int(text: str | None) -> int:
    """Résultat OCR → entier (0 si rien de numérique)."""
    d = re.sub(r"\D", "", str(text or ""))
    return int(d) if d else 0


def fmt_number(n: int | float | None) -> str:
    """1234567 → « 1 234 567 »."""
    try:
        return f"{int(n):,}".replace(",", " ")
    except (TypeError, ValueError):
        return "0"


def short_number(n: int | float) -> str:
    for div, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if abs(n) >= div:
            return f"{n / div:.1f}{suffix}"
    return str(int(n))


def parse_range(text: str | None, default: tuple[float, float] | None = None) -> tuple[float, float] | None:
    """« 40-70 » → (40, 70) ; « 30 » → (30, 30) ; illisible → default."""
    t = (text or "").replace(" ", "").replace("–", "-")
    if not t:
        return default
    parts = t.split("-")
    try:
        if len(parts) == 1:
            v = float(parts[0].replace(",", "."))
            return (v, v) if v >= 0 else default
        if len(parts) == 2:
            lo, hi = float(parts[0].replace(",", ".")), float(parts[1].replace(",", "."))
            if lo < 0 or hi < 0:
                return default
            return (min(lo, hi), max(lo, hi))
    except ValueError:
        pass
    return default


def pick_in_range(rng: tuple[float, float] | None) -> float:
    if not rng:
        return 0.0
    return random.uniform(rng[0], rng[1])


def parse_slots(text: str | None, max_slot: int = 12) -> list[int]:
    """« 1 2 3 » / « 1,2,3 » → [1, 2, 3] ; ValueError si un nombre est hors de 1..max_slot."""
    out = []
    for tok in re.split(r"[\s,;]+", (text or "").strip()):
        if not tok:
            continue
        if not tok.isdigit() or not 1 <= int(tok) <= max_slot:
            raise ValueError(f"« {tok} » n'est pas un slot entre 1 et {max_slot}")
        out.append(int(tok))
    return out


def parse_counts(text: str | None) -> list[int]:
    out = []
    for tok in re.split(r"[\s,;]+", (text or "").strip()):
        if not tok:
            continue
        if not tok.isdigit():
            raise ValueError(f"« {tok} » n'est pas un nombre")
        out.append(int(tok))
    return out


def is_auto(text: str | None) -> bool:
    return (text or "").strip().lower() in ("", "auto")


def pick_hero_delay(text: str | None) -> float:
    """« 5 » = 5 s ; « 2+1 » = tiré entre 1 et 3 s (jamais < 0) ; illisible = 0."""
    t = (text or "").replace("±", "+").replace(",", ".").strip()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(?:\+(\d+(?:\.\d+)?))?", t)
    if not m:
        return 0.0
    base = float(m.group(1))
    spread = float(m.group(2)) if m.group(2) else 0.0
    return max(0.0, random.uniform(base - spread, base + spread))


# ----------------------------------------------------------------- plages horaires
def parse_schedule(text: str | None) -> list[tuple[int, int]] | None:
    """'9-12 14:30-23' → [(540, 720), (870, 1380)] en minutes depuis minuit ; illisible → None.
    Une plage qui passe minuit (22-2) est découpée en deux."""
    ranges: list[tuple[int, int]] = []
    tokens = re.split(r"[\s,;]+", (text or "").strip())
    for token in tokens:
        if not token:
            continue
        m = re.fullmatch(r"(\d{1,2})(?:[:h](\d{2}))?-(\d{1,2})(?:[:h](\d{2}))?", token)
        if not m:
            return None
        h1, m1, h2, m2 = int(m.group(1)), int(m.group(2) or 0), int(m.group(3)), int(m.group(4) or 0)
        if h1 > 24 or h2 > 24 or m1 > 59 or m2 > 59:
            return None
        start, end = h1 * 60 + m1, h2 * 60 + m2
        if start == end:
            return None
        if end < start:
            ranges.append((start, 24 * 60))
            ranges.append((0, end))
        else:
            ranges.append((start, end))
    return ranges or None


def in_schedule(ranges: list[tuple[int, int]], minute_of_day: int) -> bool:
    return any(start <= minute_of_day < end for start, end in ranges)


def minutes_until_next_start(ranges: list[tuple[int, int]], minute_of_day: int) -> int:
    starts = sorted(s for s, _ in ranges)
    for s in starts:
        if s > minute_of_day:
            return s - minute_of_day
    return 24 * 60 - minute_of_day + starts[0]


# ----------------------------------------------------------------- fin anticipée
@dataclass
class EarlyEndRule:
    seconds: float | None = None   # « 120s » : abandon 120 s après la pose complète
    percent: float | None = None   # « 50% » : abandon quand 50 % du loot disponible est pris
    damage: float | None = None    # « 60d » : abandon à 60 % de destruction
    stale: float | None = None     # « 20f » : abandon si le loot restant est figé depuis 20 s

    @property
    def active(self) -> bool:
        return any(v is not None for v in (self.seconds, self.percent, self.damage, self.stale))


EARLY_TOKEN = re.compile(r"(\d+(?:[.,]\d+)?)\s*(s|%|d|f)", re.I)


def early_end_token_ok(token: str) -> bool:
    return bool(EARLY_TOKEN.fullmatch(token.strip()))


def parse_early_end(text: str | None) -> EarlyEndRule:
    """« 120s 50% 60d 20f » → règle. ValueError si un morceau est invalide."""
    rule = EarlyEndRule()
    t = (text or "").strip().lower()
    if t in ("", "off", "0", "-", "non", "no"):
        return rule
    for tok in re.split(r"[\s,;]+", t):
        if not tok:
            continue
        m = EARLY_TOKEN.fullmatch(tok)
        if not m:
            raise ValueError(f"« {tok} » n'est pas valide (exemples : 120s 50% 60d 20f)")
        value, unit = float(m.group(1).replace(",", ".")), m.group(2).lower()
        if unit == "s":
            rule.seconds = value
        elif unit == "%":
            rule.percent = min(100.0, value)
        elif unit == "d":
            rule.damage = min(100.0, value)
        else:
            rule.stale = value
    return rule


# ----------------------------------------------------------------- Discord / à distance
TRUE_WORDS = {"y", "true", "enable", "oui", "enabled", "1", "o", "on", "yes"}
FALSE_WORDS = {"n", "off", "disable", "0", "no", "disabled", "false", "-", "non", "none"}


def parse_bool_word(text: str) -> bool | None:
    t = (text or "").strip().lower()
    if t in TRUE_WORDS:
        return True
    if t in FALSE_WORDS:
        return False
    return None


def player_name_score(a: str, b: str) -> float:
    """Ressemblance 0-1 de deux noms de joueur, sans espaces / ponctuation / casse."""
    from difflib import SequenceMatcher
    small = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉", "01234567890123456789")

    def norm(s: str) -> str:
        return re.sub(r"[\W_]+", "", (s or "").translate(small).lower())

    ta, tb = norm(a), norm(b)
    if not ta or not tb:
        return 0.0
    return SequenceMatcher(None, ta, tb).ratio()


def closest_name(text: str, names: list[str], minimum: float = 0.6) -> str | None:
    scored = sorted(((player_name_score(text, n), n) for n in names), reverse=True)
    if scored and scored[0][0] >= minimum:
        return scored[0][1]
    return None
