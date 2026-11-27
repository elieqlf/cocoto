"""Variations « humaines » : pauses irrégulières, décalages de clic, durées de geste."""
from __future__ import annotations

import random
import time


def pause(seconds: float) -> None:
    """Pause rendue irrégulière : de 0 à +25 %, jamais plus courte."""
    if seconds > 0:
        time.sleep(seconds * random.uniform(1.0, 1.25))


def offset(spread: int) -> int:
    """Décalage en pixels, plus souvent proche de 0, sans dépasser ±spread."""
    if spread <= 0:
        return 0
    return int(round(max(-spread, min(spread, random.gauss(0, spread / 2.5)))))


def duration(seconds: float) -> float:
    """Durée d'un geste (glissement…) : -15 % à +20 %."""
    return seconds * random.uniform(0.85, 1.2)


def point_in_box(box: tuple[int, int, int, int], margin: float = 0.2) -> tuple[int, int]:
    """Point au hasard dans une zone (x1, y1, x2, y2), loin des bords."""
    x1, y1, x2, y2 = box
    mx, my = (x2 - x1) * margin, (y2 - y1) * margin
    return int(random.uniform(x1 + mx, x2 - mx)), int(random.uniform(y1 + my, y2 - my))
