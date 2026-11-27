"""Widgets de l'interface : sections (cartes), lignes de réglage, champs, interrupteurs avec aide,
boutons, tuiles de statistiques et popups. Tout est dessiné avec les jetons de couleur de theme.C.

Pour la vitesse, les conteneurs de lignes sont des tk.Frame (pas des CTkFrame, qui sont des
canevas redessinés à chaque redimensionnement) ; polices et images sont mises en cache."""
from __future__ import annotations

import os
import tkinter as tk
from typing import Callable

import customtkinter as ctk

from .. import paths
from ..i18n import tr
from .theme import C

FONT = "Segoe UI" if os.name == "nt" else "Helvetica"
PAD = 16                     # marge intérieure des sections
_fonts: dict = {}
_images: dict = {}


def font(size: int = 13, bold: bool = False):
    key = (size, bold)
    if key not in _fonts:
        _fonts[key] = ctk.CTkFont(family=FONT, size=size, weight="bold" if bold else "normal")
    return _fonts[key]


def image(name: str, size: tuple[int, int]):
    """Image de assets/img (proportions gardées, mise en cache), ou None."""
    key = (name, size)
    if key in _images:
        return _images[key]
    out = None
    try:
        from PIL import Image
        p = paths.asset("img", name)
        if os.path.exists(p):
            img = Image.open(p)
            img.thumbnail(size, Image.LANCZOS)
            out = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)
    except Exception:
        out = None
    _images[key] = out
    return out


# ---------------------------------------------------------------- boutons
def button(parent, text, command, color=None, hover=None, text_color=None, **kw):
    kw.setdefault("height", 32)
    kw.setdefault("corner_radius", 8)
    kw.setdefault("font", font(13, True))
    return ctk.CTkButton(parent, text=text, command=command, fg_color=color or C["GOLD"],
                         hover_color=hover or C["GOLD_HOVER"], text_color=text_color or C["ON_ACCENT"], **kw)


def secondary(parent, text, command, **kw):
    kw.setdefault("font", font(13))
    return button(parent, text, command, color=C["CARD_LIGHT"], hover=C["CARD_HOVER"], text_color=C["TEXT"], **kw)


def ghost(parent, text, command, **kw):
    """Bouton discret (barre du haut) : transparent, fond au survol."""
    kw.setdefault("font", font(13))
    return button(parent, text, command, color="transparent", hover=C["CARD_LIGHT"], text_color=C["TEXT"], **kw)


def big_button(parent, text, command, style: str = "green"):
    """Gros bouton START / STOP."""
    color, hover = {"green": ("#2f9e48", "#38b555"), "red": ("#d9443a", "#ee5a4f")}[style]
    return ctk.CTkButton(parent, text=text, command=command, fg_color=color, hover_color=hover,
                         text_color="#ffffff", text_color_disabled="#ffffff", font=font(16, True),
                         height=48, corner_radius=12)


def game_button(parent, text: str, command, style: str = "green"):
    """Ancien nom, gardé pour compatibilité."""
    return big_button(parent, text, command, style)


# ---------------------------------------------------------------- sections et lignes
class Section(ctk.CTkFrame):
    """Carte titrée. Les réglages s'ajoutent avec row() ; body est un tk.Frame libre."""

    def __init__(self, parent, title: str, subtitle: str | None = None, **kw):
        super().__init__(parent, fg_color=C["CARD"], corner_radius=14, border_width=1,
                         border_color=C["BORDER"], **kw)
        head = tk.Frame(self, bg=C["CARD"])
        head.pack(fill="x", padx=PAD, pady=(12, 2))
        self.head = head
        tk.Label(head, text=title.upper(), font=tkfont(12, True), fg=C["GOLD"], bg=C["CARD"]).pack(side="left")
        if subtitle:
            tklabel(self, subtitle, muted=True, size=12, justify="left", anchor="w",
                    wraplength=500).pack(fill="x", padx=PAD, pady=(0, 2))
        self.body = tk.Frame(self, bg=C["CARD"])
        self.body.pack(fill="x", padx=PAD, pady=(2, 12))
        self._rows = 0

    def row(self, text: str = "", help_: tuple[str, str] | None = None, indent: bool = False,
            divider: bool = True, icon=None) -> tk.Frame:
        """Ligne « libellé (i) ........ contrôles » ; renvoie le conteneur de droite (pack side=right)."""
        if self._rows and divider and not indent:
            tk.Frame(self.body, bg=C["DIVIDER"], height=1).pack(fill="x", pady=1)
        self._rows += 1
        line = tk.Frame(self.body, bg=C["CARD"])
        line.pack(fill="x", pady=(0 if indent else 3, 3))
        if icon is not None:
            ctk.CTkLabel(line, text=" " + text, image=icon, compound="left", font=font(13),
                         text_color=C["TEXT"], anchor="w", height=30).pack(side="left")
        elif text:
            tklabel(line, text, muted=indent, size=12 if indent else 13).pack(
                side="left", padx=(22 if indent else 0, 0), pady=4)
        if help_:
            help_button(line, text, *help_).pack(side="left", padx=6)
        right = tk.Frame(line, bg=C["CARD"])
        right.pack(side="right")
        return right


def card(parent, title: str) -> Section:
    return Section(parent, title)


def entry(parent, var, width=110, **kw):
    return ctk.CTkEntry(parent, textvariable=var, width=width, height=30, fg_color=C["ENTRY_BG"],
                        border_color=C["BORDER"], border_width=1, text_color=C["TEXT"], font=font(13),
                        corner_radius=8, **kw)


def label(parent, text, muted=False, size=13, bold=False, **kw):
    return ctk.CTkLabel(parent, text=text, text_color=C["MUTED"] if muted else C["TEXT"],
                        font=font(size, bold), **kw)


def switch(parent, text, var, command=None):
    return ctk.CTkSwitch(parent, text=text, variable=var, onvalue=True, offvalue=False, width=44,
                         switch_width=40, switch_height=20, progress_color=C["GOLD"], fg_color=C["SWITCH_OFF"],
                         button_color="#FFFFFF", button_hover_color="#FFFFFF", text_color=C["TEXT"],
                         font=font(13), command=command)


def segmented(parent, values, variable, command=None, **kw):
    kw.setdefault("font", font(13, True))
    kw.setdefault("height", 32)
    return ctk.CTkSegmentedButton(parent, values=values, variable=variable, command=command,
                                  fg_color=C["ENTRY_BG"], unselected_color=C["ENTRY_BG"],
                                  unselected_hover_color=C["CARD_LIGHT"], selected_color=C["GOLD"],
                                  selected_hover_color=C["GOLD_HOVER"], text_color=C["TEXT"],
                                  corner_radius=8, **kw)


def option_menu(parent, values, variable, width=150):
    return ctk.CTkOptionMenu(parent, values=values, variable=variable, width=width, height=30,
                             fg_color=C["ENTRY_BG"], button_color=C["CARD_LIGHT"],
                             button_hover_color=C["CARD_HOVER"], text_color=C["TEXT"], font=font(13),
                             dropdown_fg_color=C["CARD_LIGHT"], dropdown_text_color=C["TEXT"],
                             dropdown_hover_color=C["CARD_HOVER"], corner_radius=8)


def tkfont(size: int = 13, bold: bool = False):
    """Police pour les widgets tk simples (taille en pixels CTk → points)."""
    return (FONT, max(7, round(size * 0.75)), "bold") if bold else (FONT, max(7, round(size * 0.75)))


def tklabel(parent, text="", muted=False, size=13, bold=False, bg=None, **kw):
    """Libellé tk léger (bien plus rapide à créer qu'un CTkLabel)."""
    return tk.Label(parent, text=text, bg=bg or C["CARD"], fg=C["MUTED"] if muted else C["TEXT"],
                    font=tkfont(size, bold), **kw)


def help_button(parent, title: str, en: str, fr: str):
    """Petit « ⓘ » cliquable qui ouvre l'aide (libellé tk : pas de canevas à dessiner)."""
    try:
        bg = parent.cget("bg")
    except Exception:
        bg = C["CARD"]
    lb = tk.Label(parent, text="ⓘ", bg=bg, fg=C["MUTED"], font=tkfont(15), cursor="hand2")
    lb.bind("<Button-1>", lambda _e: popup_info(title, tr(en, fr)))
    lb.bind("<Enter>", lambda _e: lb.configure(fg=C["GOLD"]))
    lb.bind("<Leave>", lambda _e: lb.configure(fg=C["MUTED"]))
    return lb


# ---------------------------------------------------------------- défilement léger
_scrollers: list = []


def _on_wheel(event):
    """Molette : fait défiler la zone défilante sous la souris (une seule liaison globale)."""
    try:
        target = event.widget.winfo_containing(event.x_root, event.y_root)
    except Exception:
        target = None
    path = str(target) if target is not None else str(event.widget)
    best = None
    for canvas in _scrollers:
        try:
            if path.startswith(str(canvas)) and canvas.winfo_ismapped():
                if best is None or len(str(canvas)) > len(str(best)):
                    best = canvas
        except Exception:
            continue
    if best is not None and best.yview() != (0.0, 1.0):
        best.yview_scroll(-1 if event.delta > 0 else 1, "units")


class ThinScrollbar(tk.Canvas):
    """Barre de défilement fine dessinée à la main (CTkScrollbar force update_idletasks : lent)."""

    def __init__(self, parent, command, bg=None):
        super().__init__(parent, width=10, bg=bg or C["BG"], highlightthickness=0, bd=0)
        self.command = command
        self._first, self._last = 0.0, 1.0
        self._thumb = self.create_line(5, 0, 5, 0, width=6, capstyle="round", fill=C["CARD_LIGHT"])
        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<Button-1>", self._press)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<Enter>", lambda _e: self.itemconfigure(self._thumb, fill=C["BORDER"]))
        self.bind("<Leave>", lambda _e: self.itemconfigure(self._thumb, fill=C["CARD_LIGHT"]))
        self._grab = None

    def set(self, first, last):
        self._first, self._last = float(first), float(last)
        self._draw()

    def _draw(self):
        h = self.winfo_height()
        if self._last - self._first >= 0.999 or h <= 1:
            self.coords(self._thumb, -10, -10, -10, -10)
            return
        self.coords(self._thumb, 5, 5 + self._first * (h - 10), 5, 5 + self._last * (h - 10))

    def _press(self, e):
        h = max(1, self.winfo_height() - 10)
        pos = (e.y - 5) / h
        if not (self._first <= pos <= self._last):
            self.command("moveto", pos - (self._last - self._first) / 2)
        self._grab = (e.y, self._first)

    def _drag(self, e):
        if self._grab:
            h = max(1, self.winfo_height() - 10)
            self.command("moveto", self._grab[1] + (e.y - self._grab[0]) / h)


class ScrollPage(tk.Frame):
    """Page défilante légère : canevas + cadre intérieur (`inner`) + barre fine."""

    def __init__(self, parent, bg=None):
        bg = bg or C["BG"]
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0, yscrollincrement=24)
        self.bar = ThinScrollbar(self, self.canvas.yview, bg=bg)
        self.inner = tk.Frame(self.canvas, bg=bg)
        win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(win, width=e.width))
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.bar.pack(side="right", fill="y", padx=(4, 0))
        self.canvas.pack(side="left", fill="both", expand=True)
        if not _scrollers:
            self.canvas.bind_all("<MouseWheel>", _on_wheel, add="+")
        _scrollers.append(self.canvas)


class StatTile(ctk.CTkFrame):
    """Tuile de statistique : icône + libellé, grande valeur. set() ne redessine que si ça change."""

    def __init__(self, parent, icon: str | None, text: str, color: str | None = None, big: int = 18):
        super().__init__(parent, fg_color=C["CARD_LIGHT"], corner_radius=12)
        self._value = None
        top = tk.Frame(self, bg=C["CARD_LIGHT"])
        top.pack(fill="x", padx=12, pady=(9, 0))
        self.caption = ctk.CTkLabel(top, text=(" " + text) if icon else text, image=image(icon, (18, 18)) if icon else None,
                                    compound="left", font=font(12), text_color=C["MUTED"], height=20, anchor="w")
        self.caption.pack(side="left")
        self.value = ctk.CTkLabel(self, text="0", font=font(big, True), text_color=color or C["TEXT"],
                                  anchor="w", height=big + 12)
        self.value.pack(fill="x", padx=12, pady=(0, 8))

    def set(self, text: str) -> None:
        if text != self._value:
            self._value = text
            self.value.configure(text=text)

    def relabel(self, icon: str | None, text: str, color: str | None = None) -> None:
        self.caption.configure(text=(" " + text) if icon else text, image=image(icon, (18, 18)) if icon else None)
        self.value.configure(text_color=color or C["TEXT"])


# ---------------------------------------------------------------- popups
def _popup(title: str, message: str, buttons: list[tuple[str, object]], entry_initial: str | None = None,
           symbol: str = "i", color: str | None = None):
    root = tk._default_root
    win = ctk.CTkToplevel(root)
    win.title(title)
    win.configure(fg_color=C["BG"])
    win.resizable(False, False)
    win.attributes("-topmost", True)
    result = {"value": buttons[-1][1] if buttons else None}
    box = ctk.CTkFrame(win, fg_color=C["CARD"], corner_radius=14, border_width=1, border_color=C["BORDER"])
    box.pack(fill="both", expand=True, padx=12, pady=12)
    head = ctk.CTkFrame(box, fg_color="transparent")
    head.pack(fill="x", padx=18, pady=(16, 6))
    ctk.CTkLabel(head, text=symbol, width=30, height=30, corner_radius=15, fg_color=color or C["GOLD"],
                 text_color="#ffffff" if color else C["ON_ACCENT"], font=font(15, True)).pack(side="left")
    ctk.CTkLabel(head, text=title, font=font(16, True), text_color=C["TEXT"]).pack(side="left", padx=10)
    ctk.CTkLabel(box, text=message, justify="left", anchor="w", wraplength=440, font=font(13),
                 text_color=C["TEXT"]).pack(fill="x", padx=20, pady=6)
    var = tk.StringVar(value=entry_initial or "")
    if entry_initial is not None:
        e = entry(box, var, 440)
        e.pack(padx=20, pady=6)
        e.focus_set()
    row = ctk.CTkFrame(box, fg_color="transparent")
    row.pack(fill="x", padx=20, pady=(10, 16))

    def close(value):
        result["value"] = var.get() if (entry_initial is not None and value is True) else value
        win.destroy()

    for i, (text, value) in reversed(list(enumerate(buttons))):
        (button if i == 0 else secondary)(row, text, lambda v=value: close(v), width=110).pack(side="right", padx=(8, 0))
    win.bind("<Return>", lambda _e: close(buttons[0][1]))
    win.bind("<Escape>", lambda _e: close(buttons[-1][1]))
    win.after(50, lambda: (win.lift(), win.focus_force(), win.grab_set()))
    win.wait_window()
    return result["value"]


def popup_info(title, message):
    return _popup(title, message, [("OK", True)])


def popup_error(title, message):
    return _popup(title, message, [("OK", True)], symbol="!", color="#d9443a")


def popup_yesno(title, message) -> bool:
    return bool(_popup(title, message, [(tr("Yes", "Oui"), True), (tr("No", "Non"), False)], symbol="?"))


def popup_ask(title, message, initial="") -> str | None:
    v = _popup(title, message, [("OK", True), (tr("Cancel", "Annuler"), None)], entry_initial=initial)
    return v.strip() if isinstance(v, str) and v.strip() else None


class Binder:
    """Relie des variables Tk aux clés d'une LiveConfig (dans les deux sens)."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.items: list[tuple[str, tk.Variable, Callable, Callable]] = []
        self._loading = False

    def var(self, key: str, kind: str = "str") -> tk.Variable:
        if kind == "bool":
            v = tk.BooleanVar(value=self.cfg.flag(key))
            get, put = (lambda vv=v: bool(vv.get())), (lambda val, vv=v: vv.set(bool(val)))
        else:
            v = tk.StringVar(value=self.cfg.text(key))
            get, put = (lambda vv=v: vv.get()), (lambda val, vv=v: vv.set("" if val is None else str(val)))
        v.trace_add("write", lambda *_a, k=key, g=get: (not self._loading) and self.cfg.set(k, g()))
        self.items.append((key, v, get, put))
        return v

    def nested(self, key: str, sub: str, field: str, kind: str = "str", default=""):
        """Variable liée à cfg[key][sub][field] (héros, améliorations…)."""
        def read():
            return (self.cfg.get(key) or {}).get(sub, {}).get(field, default)
        v = tk.BooleanVar(value=bool(read())) if kind == "bool" else tk.StringVar(value=str(read() or ""))

        def write(*_a):
            if self._loading:
                return
            data = self.cfg.get(key) or {}
            row = data.setdefault(sub, {})
            row[field] = bool(v.get()) if kind == "bool" else v.get()
            self.cfg.set(key, data)

        v.trace_add("write", write)
        put = (lambda val, vv=v: vv.set(bool(val))) if kind == "bool" else (lambda val, vv=v: vv.set(str(val or "")))
        self.items.append((f"{key}.{sub}.{field}", v, lambda vv=v: vv.get(), lambda _val, r=read, p=put: p(r())))
        return v

    def refresh(self) -> None:
        self._loading = True
        try:
            for key, _v, _get, put in self.items:
                put(self.cfg.get(key) if "." not in key else None)
        finally:
            self._loading = False
