"""OCR : EasyOCR (comme CoCoBot) chargé à la demande, avec le modèle embarqué si présent.

Les montants (loot, prix) sont d'abord isolés (chiffres clairs → noir sur blanc, agrandis x2),
puis lus avec la liste de caractères « 0123456789 »."""
from __future__ import annotations

import os
import re
import threading

import cv2
import numpy as np

from . import paths, vision
from .logger import log

_reader = None
_lock = threading.Lock()
_failed = False


def reader():
    """Lecteur EasyOCR partagé (None si EasyOCR n'est pas installé)."""
    global _reader, _failed
    if _reader is not None or _failed:
        return _reader
    with _lock:
        if _reader is not None:
            return _reader
        try:
            import easyocr  # type: ignore
        except ImportError:
            _failed = True
            log("⚠️ EasyOCR n'est pas installé (pip install easyocr) : lectures OCR désactivées.")
            return None
        model_dir = paths.asset("EasyOCR", "model")
        try:
            if os.path.exists(os.path.join(model_dir, "english_g2.pth")):
                _reader = easyocr.Reader(["en"], gpu=False, model_storage_directory=model_dir,
                                         download_enabled=False, verbose=False)
                log("🔤 Modèle EasyOCR embarqué chargé")
            else:
                _reader = easyocr.Reader(["en"], gpu=False, verbose=False)
                log("🔤 Modèle EasyOCR chargé (~/.EasyOCR)")
        except Exception as exc:  # modèle abîmé, torch absent…
            _failed = True
            log(f"⚠️ EasyOCR inutilisable : {exc}")
        return _reader


def read_text(img: np.ndarray, allowlist: str | None = None, detail: bool = False,
              paragraph: bool = False):
    """Textes lus : [(box, texte, confiance)] si detail, sinon [texte]."""
    r = reader()
    if r is None or img is None or img.size == 0:
        return []
    try:
        res = r.readtext(img, allowlist=allowlist, detail=1, paragraph=paragraph)
    except Exception as exc:
        log(f"⚠️ OCR : {exc}")
        return []
    if detail:
        return res
    return [t for _b, t, *_ in res]


def read_box_text(screen: np.ndarray, box, allowlist: str | None = None) -> str:
    zone, _, _ = vision.crop(screen, box)
    return " ".join(read_text(zone, allowlist=allowlist)).strip()


def ocr_lines(results, max_gap: int = 60) -> list[tuple[int, str]]:
    """Résultats EasyOCR (detail) regroupés en lignes [(y centre, texte)]."""
    items = []
    for box, text, *_ in results:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        items.append((min(xs), max(xs), (min(ys) + max(ys)) / 2, text))
    items.sort(key=lambda r: (r[2], r[0]))
    lines: list[list] = []
    for x1, x2, yc, text in items:
        for line in lines:
            if abs(line[0] - yc) < 14 and x1 - line[2] <= max_gap:
                line[1] += " " + text
                line[2] = max(line[2], x2)
                break
        else:
            lines.append([yc, text, x2])
    return [(int(l[0]), l[1].strip()) for l in sorted(lines)]


# ------------------------------------------------------------------ montants
def prepare_digits(crop_bgr: np.ndarray, v_min: int = 190, s_max: int = 80,
                   scale: float = 2.0) -> tuple[np.ndarray, int]:
    """Isole les chiffres clairs d'un montant. Retourne (image noir sur blanc, nombre de chiffres)."""
    mask = vision.white_text_mask(crop_bgr, v_min=v_min, s_max=s_max)
    min_h, max_h = max(6, crop_bgr.shape[0] // 4), crop_bgr.shape[0]
    keep = np.zeros_like(mask)
    n_digits = 0
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    cand = [i for i in range(1, n) if min_h <= stats[i][3] <= max_h and stats[i][4] >= 12]
    # Les chiffres d'un montant ont tous la même hauteur. Derrière les barres translucides du
    # village, des taches claires du décor passent le masque (vu GPG 2026-11 : un « 4 » parasite).
    top = max((stats[i][3] for i in cand), default=0)
    for i in cand:
        _x, _y, w, h, _area = stats[i]
        if h >= 0.7 * top and w <= 1.2 * h:
            keep[labels == i] = 255
            n_digits += 1
    img = 255 - keep
    img = cv2.copyMakeBorder(img, 8, 8, 8, 8, cv2.BORDER_CONSTANT, value=255)
    if scale != 1.0:
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    return img, n_digits


def read_amount(screen: np.ndarray, box, v_min: int = 190, s_max: int = 80) -> int | None:
    """Montant écrit en chiffres clairs dans box. None si illisible.
    Contrôle croisé : le nombre de chiffres lus doit égaler le nombre de composantes."""
    zone, _, _ = vision.crop(screen, box)
    if zone.size == 0:
        return None
    img, n_digits = prepare_digits(zone, v_min=v_min, s_max=s_max)
    if n_digits == 0:
        return None
    text = "".join(read_text(img, allowlist="0123456789"))
    digits = re.sub(r"\D", "", text)
    if not digits:
        return None
    if abs(len(digits) - n_digits) > 1:   # un « 1 » fin peut se coller / se perdre
        return None
    return int(digits)


def read_amount_stable(grab, box, tries: int = 3, **kw) -> int | None:
    """Lit un montant jusqu'à obtenir deux lectures identiques (montants qui défilent)."""
    last = None
    for _ in range(tries):
        screen = grab()
        v = read_amount(screen, box, **kw)
        if v is not None and v == last:
            return v
        last = v
    return last


# ------------------------------------------------------------------ chiffres contrôlés
def _ocr_mask(mask: np.ndarray) -> str:
    img = cv2.copyMakeBorder(255 - mask, 8, 8, 8, 8, cv2.BORDER_CONSTANT, value=255)
    img = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    return re.sub(r"\D", "", "".join(read_text(img, allowlist="0123456789")))


def read_digits_mask(mask: np.ndarray, comps: list[tuple] | None = None) -> str:
    """Chiffres d'un masque (texte blanc sur noir). Contrôle : autant de chiffres que de composantes ;
    sinon lecture composante par composante (EasyOCR perd souvent le « 1 » fin : étroite = 1).
    "" si illisible."""
    comps = sorted(comps if comps is not None else vision.components(mask, min_h=8, max_h=60))
    if not comps:
        return ""
    keep = np.zeros_like(mask)
    for x, y, w, h, _a in comps:
        keep[y:y + h, x:x + w] = mask[y:y + h, x:x + w]
    text = _ocr_mask(keep)
    if len(text) == len(comps):
        return text
    out = ""
    for x, y, w, h, _a in comps:
        if w <= h * 0.5:
            out += "1"
            continue
        d = _ocr_mask(keep[y:y + h, x:x + w])
        if len(d) != 1:
            return ""
        out += d
    return out


def is_slash(comp: tuple) -> bool:
    """« / » : composante penchée, peu remplie (≈0,4) et pas aussi étroite qu'un « 1 »."""
    _x, _y, w, h, area = comp
    return w > h * 0.5 and area / max(1, w * h) < 0.5


def read_fraction(screen: np.ndarray, box, v_min: int = 170, s_max: int = 60) -> tuple[int, int] | None:
    """« 1/6 » (ouvriers, labo…) → (1, 6). EasyOCR perd le « / » : on coupe sur sa composante."""
    zone, _, _ = vision.crop(screen, box)
    if zone.size == 0:
        return None
    mask = vision.white_text_mask(zone, v_min=v_min, s_max=s_max)
    comps = sorted(vision.components(mask, min_h=8, max_h=60))
    slash = [i for i, c in enumerate(comps) if 0 < i < len(comps) - 1 and is_slash(c)]
    if len(slash) != 1:
        return None
    i = slash[0]
    a, b = read_digits_mask(mask, comps[:i]), read_digits_mask(mask, comps[i + 1:])
    return (int(a), int(b)) if a and b else None
