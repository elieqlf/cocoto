"""Fenêtres secondaires : journal, tableau de bord multi-instances, unités des dons, thème."""
from __future__ import annotations

import os
import time
import tkinter as tk
from tkinter import colorchooser, filedialog

import customtkinter as ctk

from .. import dashboard, logger, notify, paths
from ..i18n import tr
from ..parsing import fmt_number
from . import widgets as W
from .theme import C, THEMES


def open_logs(parent, controller):
    win = ctk.CTkToplevel(parent)
    win.title("Cocoto - Logs")
    win.geometry("900x520")
    win.configure(fg_color=C["BG"])
    box = ctk.CTkTextbox(win, fg_color=C["CARD"], text_color=C["TEXT"], wrap="none", corner_radius=12,
                         border_width=1, border_color=C["BORDER"],
                         font=ctk.CTkFont(family="Consolas" if os.name == "nt" else "Menlo", size=12))
    box.pack(fill="both", expand=True, padx=10, pady=(10, 4))
    state = {"shown": 0}

    def refresh():
        if not win.winfo_exists():
            return
        lines = logger.snapshot()
        if len(lines) < state["shown"]:
            box.delete("1.0", "end")
            state["shown"] = 0
        new = lines[state["shown"]:]
        if new:
            at_bottom = box.yview()[1] > 0.98
            box.insert("end", "\n".join(new) + "\n")
            state["shown"] = len(lines)
            if at_bottom:
                box.see("end")
        win.after(1000, refresh)

    def clear():
        logger.clear()
        box.delete("1.0", "end")
        state["shown"] = 0

    def copy():
        win.clipboard_clear()
        win.clipboard_append("\n".join(logger.snapshot()))

    def save():
        path = filedialog.asksaveasfilename(defaultextension=".txt", initialfile="cocoto_logs.txt")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(logger.snapshot()))

    def support():
        info = {"Moteur": controller.settings.get("backend"), "Langue": controller.settings.get("language")}
        path = notify.export_support_zip(info)
        W.popup_info("Support", tr("Support file created:\n", "Fichier de support créé :\n") + path)

    row = ctk.CTkFrame(win, fg_color="transparent")
    row.pack(fill="x", padx=10, pady=(0, 10))
    for text, cmd in ((tr("Clear", "Effacer"), clear), (tr("Copy", "Copier"), copy),
                      (tr("Save", "Enregistrer"), save), (tr("Support zip", "Zip support"), support)):
        W.secondary(row, text, cmd, width=120).pack(side="left", padx=4)
    refresh()
    return win


def open_dashboard(parent, controller):
    win = ctk.CTkToplevel(parent)
    win.title("Cocoto - Dashboard")
    win.geometry("1180x380")
    win.configure(fg_color=C["BG"])
    cols = (("#", 34), ("Mode", 60), ("Account", 120), ("State", 140), ("Uptime", 76), ("Gold", 100),
            ("Elixir", 100), ("Dark", 80), ("Battles", 64), ("", 90), ("Last log", 290))
    table = ctk.CTkScrollableFrame(win, fg_color=C["CARD"], corner_radius=12, border_width=1,
                                   border_color=C["BORDER"])
    table.pack(fill="both", expand=True, padx=10, pady=10)
    for c, (title, width) in enumerate(cols):
        W.label(table, title, muted=True, bold=True, width=width, anchor="w").grid(row=0, column=c, padx=3)
    rows: dict[int, list] = {}

    def action(n, data):
        dashboard.send(n, "stop" if data.get("state") not in ("stopped", None) else "start", data.get("mode"))

    def refresh():
        if not win.winfo_exists():
            return
        for n, d in dashboard.read_all().items():
            if n not in rows:
                widgets = [W.label(table, "", width=w, anchor="w") for _t, w in cols]
                for c, w in enumerate(widgets):
                    w.grid(row=n, column=c, padx=3, pady=2)
                btn = W.secondary(table, "Start", None, width=80)
                btn.grid(row=n, column=9, padx=3)
                widgets[9] = btn
                rows[n] = widgets
            w = rows[n]
            st = d.get("stats", {})
            h, rem = divmod(int(d.get("uptime", 0)), 3600)
            state = d.get("state", "?") if d.get("online") else "offline"
            vals = (n, d.get("mode", ""), d.get("account") or "Main", state, f"{h:02d}:{rem // 60:02d}",
                    fmt_number(st.get("gold", 0)), fmt_number(st.get("elixir", 0)), fmt_number(st.get("dark", 0)),
                    d.get("battles", 0), None, (d.get("last_log") or "")[:48])
            for c, v in enumerate(vals):
                if c != 9:
                    w[c].configure(text=str(v))
            w[9].configure(text="Stop" if state not in ("stopped", "offline") else "Start",
                           command=lambda nn=n, dd=d: action(nn, dd))
        win.after(2000, refresh)

    row = ctk.CTkFrame(win, fg_color="transparent")
    row.pack(fill="x", padx=10, pady=(0, 10))
    W.button(row, "  Start all", lambda: [dashboard.send(n, "start", d.get("mode"))
                                         for n, d in dashboard.read_all().items()], width=110).pack(side="left", padx=4)
    W.button(row, "  Stop all", lambda: [dashboard.send(n, "stop") for n in dashboard.read_all()],
             color="#d9443a", hover="#ee5a4f", text_color="#FFFFFF", width=110).pack(side="left", padx=4)

    def new_instance():
        n = max(list(dashboard.read_all().keys()) + [paths.INSTANCE]) + 1
        dashboard.launch_instance(n)
        W.popup_info("Multi-instance", tr(f"Cocoto #{n} is starting (ADB port {16384 + 32 * (n - 1)}).",
                                          f"Cocoto n°{n} se lance (port ADB {16384 + 32 * (n - 1)})."))

    W.secondary(row, tr(" New instance", " Nouvelle instance"), new_instance, width=140).pack(side="right", padx=4)
    refresh()
    return win


def open_donate_units(parent, controller, on_change=None):
    """Grille des cartes pour les demandes libres : un clic ajoute (numéro = priorité), un autre retire."""
    from PIL import Image
    win = ctk.CTkToplevel(parent)
    win.title(tr("Free requests", "Demandes libres"))
    win.configure(fg_color=C["BG"])
    chosen: list[str] = list(controller.settings.get("donate_free_units") or [])
    folder = paths.asset("img", "donate")
    units = sorted(os.path.splitext(f)[0] for f in os.listdir(folder)) if os.path.isdir(folder) else []
    grid = ctk.CTkScrollableFrame(win, fg_color=C["CARD"], width=760, height=420)
    grid.pack(padx=10, pady=10)
    buttons = {}

    def refresh():
        for u, b in buttons.items():
            n = chosen.index(u) + 1 if u in chosen else None
            b.configure(text=str(n) if n else "", fg_color=C["GOLD"] if n else C["CARD_LIGHT"])

    def toggle(u):
        if u in chosen:
            chosen.remove(u)
        else:
            chosen.append(u)
        controller.settings.set("donate_free_units", chosen)
        refresh()
        if on_change:
            on_change()

    for i, u in enumerate(units):
        img = Image.open(os.path.join(folder, u + ".png"))
        img.thumbnail((70, 90))
        cimg = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)
        b = ctk.CTkButton(grid, image=cimg, text="", compound="top", width=80, height=100,
                          text_color="#1a1410", command=lambda uu=u: toggle(uu))
        b.grid(row=i // 9, column=i % 9, padx=3, pady=3)
        buttons[u] = b
    W.label(win, tr("t = troops, s = spells. The number is the priority.",
                    "t = troupes, s = sorts. Le numéro est la priorité."), muted=True).pack(pady=(0, 10))
    refresh()
    return win


def theme_dialog(parent, settings) -> str | None:
    """Choix du thème (appliqué au prochain démarrage) : une carte par thème avec ses couleurs.
    Retourne le nom choisi."""
    from .theme import build_custom
    names = list(THEMES) + ["custom"]
    labels = [THEMES[n][0] for n in THEMES] + [tr("Custom", "Perso")]
    win = ctk.CTkToplevel(parent)
    win.title(tr("Theme", "Thème"))
    win.configure(fg_color=C["BG"])
    win.resizable(False, False)
    win.attributes("-topmost", True)
    current = settings.get("theme", "clash_gold")
    var = tk.StringVar(value=current if current in names else names[0])
    colors = dict(settings.get("theme_colors") or {"background": "#1a1410", "accent": "#F5B83D"})
    W.label(win, tr("Theme", "Thème"), size=16, bold=True).pack(anchor="w", padx=18, pady=(14, 2))
    W.label(win, tr("Applied at the next start.", "Appliqué au prochain lancement."), muted=True,
            size=12).pack(anchor="w", padx=18)
    cards, swatches = {}, {}

    def palette(name):
        if name == "custom":
            p = build_custom(colors["background"], colors["accent"])
            return p["BG"], p["CARD_LIGHT"], p["GOLD"], p["TEXT"]
        v = dict(zip(("BG", "CARD", "CARD_LIGHT", "BORDER", "ENTRY_BG", "GOLD"), THEMES[name][1]))
        return v["BG"], v["CARD_LIGHT"], v["GOLD"], THEMES[name][1][8]

    def paint():
        for n, card in cards.items():
            on = var.get() == n
            card.configure(border_color=C["GOLD"] if on else C["BORDER"], border_width=2 if on else 1)
            for sw, col in zip(swatches[n], palette(n)):
                sw.configure(fg_color=col)

    for n, text in zip(names, labels):
        card = ctk.CTkFrame(win, fg_color=C["CARD"], corner_radius=12, border_width=1, border_color=C["BORDER"])
        card.pack(fill="x", padx=16, pady=(10, 0))
        row = tk.Frame(card, bg=C["CARD"])
        row.pack(fill="x", padx=14, pady=10)
        name_lbl = W.label(row, text, bold=True)
        name_lbl.pack(side="left")
        swatches[n] = []
        for _ in range(4):
            sw = ctk.CTkFrame(row, width=22, height=22, corner_radius=11, border_width=1, border_color="#000000")
            sw.pack(side="right", padx=2)
            swatches[n].insert(0, sw)
        for w in [card, row, name_lbl] + swatches[n]:
            w.bind("<Button-1>", lambda _e, nn=n: (var.set(nn), paint()))
        cards[n] = card
    row = tk.Frame(win, bg=C["BG"])
    row.pack(fill="x", padx=16, pady=(8, 0))

    def pick(key):
        c = colorchooser.askcolor(colors[key], parent=win)[1]
        if c:
            colors[key] = c
            btns[key].configure(fg_color=c, hover_color=c,
                                text_color="#151515" if theme_luminance(c) > 0.55 else "#f3f3f3")
            var.set("custom")
            paint()

    from .theme import luminance as theme_luminance
    btns = {}
    for key, text in (("background", tr("Custom background", "Fond perso")), ("accent", tr("Custom accent", "Accent perso"))):
        btns[key] = ctk.CTkButton(row, text=text, fg_color=colors[key], hover_color=colors[key], width=150,
                                  height=30, corner_radius=8, font=W.font(12, True), border_width=1,
                                  border_color=C["BORDER"],
                                  text_color="#151515" if theme_luminance(colors[key]) > 0.55 else "#f3f3f3",
                                  command=lambda k=key: pick(k))
        btns[key].pack(side="left", padx=(0, 8))
    out = {"v": None}

    def ok():
        settings.set("theme", var.get())
        settings.set("theme_colors", colors)
        out["v"] = var.get()
        win.destroy()

    foot = tk.Frame(win, bg=C["BG"])
    foot.pack(fill="x", padx=16, pady=14)
    W.button(foot, "OK", ok, width=110).pack(side="right")
    W.secondary(foot, tr("Cancel", "Annuler"), win.destroy, width=110).pack(side="right", padx=8)
    paint()
    win.grab_set()
    win.wait_window()
    return out["v"]
