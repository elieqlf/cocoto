"""Fenêtre principale.

Haut : barre (logo, langue, thème, tableau de bord, journal) puis le panneau de contrôle (statut,
mode TH/BH, START / STOP, statistiques clés). Dessous : une barre d'onglets et la page choisie
(Réglages, Héros, Améliorations, Stats, Profils, Système).

Vitesse : chaque page est construite à son premier affichage (la page visible d'abord, les autres
pendant les temps morts juste après l'ouverture) ; _tick et _refresh_status ne font que modifier le
texte des widgets existants, et seulement quand la valeur change."""
from __future__ import annotations

import queue
import threading
import time
import tkinter as tk

import customtkinter as ctk

from .. import dashboard, i18n, paths, remote
from ..config import BH_HERO_KEYS, BH_HERO_NAMES, HERO_KEYS, HERO_NAMES
from ..i18n import tr
from ..logger import log
from ..parsing import fmt_number
from ..storage import profile_from_code, profile_to_code
from . import theme
from . import widgets as W
from . import windows
from .theme import C

STATUS_TEXT = {"stopped": ("Stopped", "Arrêté"), "farming": ("Running", "En marche"),
               "break": ("Break", "Pause"), "off_hours": ("Off hours", "Hors horaires"),
               "full": ("Storages full", "Réserves pleines"), "reconnecting": ("Reconnecting", "Reconnexion"),
               "stopping": ("Stopping…", "Arrêt en cours…")}
STATUS_COLOR = {"farming": "#43c463", "stopped": "#e5584d", "reconnecting": "#4d9be6"}   # autres : ambre
PAGES = ("config", "heroes", "upgrade", "stats", "profile", "system")
PAGE_TEXT = {"config": ("Settings", "Réglages"), "heroes": ("Heroes", "Héros"),
             "upgrade": ("Upgrades", "Améliorations"), "stats": ("Stats", "Stats"),
             "profile": ("Profiles", "Profils"), "system": ("System", "Système")}
# tuiles du panneau de contrôle : (clé de stat, icône, en, fr, couleur)
KPIS = {"TH": (("gold", "gold.png", "Gold", "Or", None), ("elixir", "elixir.png", "Elixir", "Élixir", theme.ELIXIR_COLOR),
               ("dark", "dark.png", "Dark", "Noir", theme.DARK_COLOR), ("uptime", "uptime.png", "Uptime", "Durée", None)),
        "BH": (("gold", "gold.png", "Gold", "Or", None), ("elixir", "elixir.png", "Elixir", "Élixir", theme.ELIXIR_COLOR),
               ("stars", "stars.png", "Stars", "Étoiles", None), ("uptime", "uptime.png", "Uptime", "Durée", None))}


def _fmt_uptime(seconds: float) -> str:
    t = int(seconds)
    return f"{t // 3600:02d}:{t % 3600 // 60:02d}:{t % 60:02d}"


class App(ctk.CTk):
    def __init__(self, controller, autostart: str | None = None):
        theme.apply(controller.settings.get("theme", "clash_gold"), controller.settings.get("theme_colors"))
        ctk.set_appearance_mode("dark")
        super().__init__(fg_color=C["BG"])
        self.c = controller
        self._ui_queue: queue.Queue = queue.Queue()
        title = f"Cocoto {paths.VERSION}" + (f" — instance {paths.INSTANCE}" if paths.INSTANCE > 1 else "")
        self.title(title)
        self.geometry(f"600x880+{10 + 40 * (paths.INSTANCE - 1)}+10")
        self.minsize(560, 620)
        self.binders = {m: W.Binder(self.c.cfg[m]) for m in ("TH", "BH")}
        self.frames: dict[str, dict[str, tk.Widget]] = {"TH": {}, "BH": {}}   # pages construites
        self.stat_tiles: dict[str, dict[str, W.StatTile]] = {"TH": {}, "BH": {}}
        self.profile_lists: dict[str, tk.Listbox] = {}
        self.page = "config"
        self._shown = None
        self._status_sig = None
        self._kpi_mode = None
        self._system_page = None
        self._build_topbar()
        self._build_control()
        self._build_nav()
        self.content = tk.Frame(self, bg=C["BG"])
        self.content.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        self.switch_mode(self.c.state.mode)
        controller.on_message = lambda t, m: self.run_in_ui(lambda: W.popup_info(t, m), wait=False)
        controller.on_profile_loaded = lambda mode, name: self.run_in_ui(lambda: self._profile_loaded(mode, name), wait=False)
        controller.state.on_change(lambda: self.run_in_ui(self._refresh_status, wait=False))
        self.after(100, self._pump)
        self.after(1000, self._tick)
        self.after(400, self._prebuild)
        self._hotkey()
        dashboard.start_loop(controller, lambda f: self.run_in_ui(f))
        remote.start_remote(controller, lambda f: self.run_in_ui(f))
        controller.start_autosave()
        if autostart:   # --start TH|BH : lancé sans clic (ni popup de restauration / d'avertissement)
            self.after(1500, lambda: self._autostart(autostart))
        else:
            self.after(600, self._offer_restore)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ================================================================ thread UI
    def run_in_ui(self, func, wait: bool = True, timeout: float = 15):
        """Exécute func dans le thread Tk et renvoie son résultat (None si rien avant timeout)."""
        if threading.current_thread() is threading.main_thread():
            return func()
        done, out = threading.Event(), {}

        def call():
            try:
                out["v"] = func()
            finally:
                done.set()

        self._ui_queue.put(call)
        if wait:
            done.wait(timeout)
            return out.get("v")
        return None

    def _pump(self):
        try:
            while True:
                self._ui_queue.get_nowait()()
        except queue.Empty:
            pass
        except Exception as exc:
            log(f"⚠️ UI : {exc}")
        self.after(100, self._pump)

    # ================================================================ barre du haut
    def _build_topbar(self):
        bar = tk.Frame(self, bg=C["BG"])
        bar.pack(fill="x", padx=14, pady=(12, 8))
        ctk.CTkLabel(bar, text="C", width=34, height=34, corner_radius=10, fg_color=C["GOLD"],
                     text_color=C["ON_ACCENT"], font=W.font(18, True)).pack(side="left")
        ctk.CTkLabel(bar, text="Cocoto", font=W.font(20, True), text_color=C["TEXT"]).pack(side="left", padx=(10, 6))
        sub = f"v{paths.VERSION}" + (f" · #{paths.INSTANCE}" if paths.INSTANCE > 1 else "")
        ctk.CTkLabel(bar, text=sub, font=W.font(12), text_color=C["MUTED"]).pack(side="left", pady=(5, 0))
        W.ghost(bar, tr("Logs", "Journal"), lambda: windows.open_logs(self, self.c), width=70).pack(side="right")
        W.ghost(bar, tr("Dashboard", "Tableau"), lambda: windows.open_dashboard(self, self.c), width=70).pack(side="right")
        W.ghost(bar, "🎨", self._choose_theme, width=34).pack(side="right", padx=2)
        self.lang_var = tk.StringVar(value=self.c.settings.get("language", "fr").upper())
        W.segmented(bar, ["FR", "EN"], self.lang_var, self._set_language, width=76, height=28,
                    font=W.font(12, True)).pack(side="right", padx=6)

    # ================================================================ panneau de contrôle
    def _build_control(self):
        box = ctk.CTkFrame(self, fg_color=C["CARD"], corner_radius=16, border_width=1, border_color=C["BORDER"])
        box.pack(fill="x", padx=14, pady=(0, 10))
        inner = tk.Frame(box, bg=C["CARD"])
        inner.pack(fill="x", padx=W.PAD, pady=14)

        top = tk.Frame(inner, bg=C["CARD"])
        top.pack(fill="x")
        self.status_pill = ctk.CTkLabel(top, text="", height=28, corner_radius=14, font=W.font(13, True))
        self.status_pill.pack(side="left")
        self.status_detail = ctk.CTkLabel(top, text="", font=W.font(12), text_color=C["MUTED"])
        self.status_detail.pack(side="left", padx=10)
        ctk.CTkLabel(top, text=tr("F1: start / stop", "F1 : marche / arrêt"), font=W.font(12),
                     text_color=C["PLACEHOLDER"]).pack(side="right")

        self.mode_var = tk.StringVar(value=self._mode_label(self.c.state.mode))
        W.segmented(inner, [self._mode_label("TH"), self._mode_label("BH")], self.mode_var,
                    lambda v: self.switch_mode("TH" if v == self._mode_label("TH") else "BH"),
                    height=36).pack(fill="x", pady=(12, 10))

        btns = tk.Frame(inner, bg=C["CARD"])
        btns.pack(fill="x")
        btns.grid_columnconfigure((0, 1), weight=1, uniform="b")
        self.start_btn = W.big_button(btns, "▶  START", lambda: self.start(self.c.state.mode), "green")
        self.start_btn.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        self.stop_btn = W.big_button(btns, "■  STOP", self.c.stop, "red")
        self.stop_btn.grid(row=0, column=1, sticky="ew", padx=(5, 0))

        tiles = tk.Frame(inner, bg=C["CARD"])
        tiles.pack(fill="x", pady=(12, 0))
        tiles.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="k")
        self.kpis: list[W.StatTile] = []
        for i in range(4):
            t = W.StatTile(tiles, None, "", big=16)
            t.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 4, 0 if i == 3 else 4))
            self.kpis.append(t)

    @staticmethod
    def _mode_label(mode):
        return tr("🏰  Home Village", "🏰  Village principal") if mode == "TH" else tr("🔨  Builder Base", "🔨  Base des ouvriers")

    def _refresh_status(self):
        """Statut, boutons START/STOP et ligne de détail : ne touche aux widgets que si ça a changé."""
        st = self.c.state
        alive = st.thread is not None and st.thread.is_alive()
        key = st.status if st.running else ("stopping" if alive else "stopped")
        mode = st.running_mode or st.mode
        sig = (key, mode, bool(st.running), alive, self.c.active_profile(mode), st.battles,
               st.current_account)
        if sig == self._status_sig:
            return
        old = self._status_sig
        self._status_sig = sig
        en, fr = STATUS_TEXT.get(key, (key, key))
        color = STATUS_COLOR.get(key, "#e0a030")
        self.status_pill.configure(text=f"  ●  {tr(en, fr)}  ", text_color=color, fg_color=theme.mix(C["CARD"], color, 0.18))
        parts = [tr(f"{st.battles} battle(s)", f"{st.battles} combat(s)")]
        if sig[4]:
            parts.append(tr(f"profile « {sig[4]} »", f"profil « {sig[4]} »"))
        if st.current_account:
            parts.append(st.current_account)
        self.status_detail.configure(text="  ·  ".join(parts))
        if old is None or old[2:4] != sig[2:4]:
            busy = bool(st.running) or alive
            self.start_btn.configure(state="disabled" if busy else "normal",
                                     fg_color=C["CARD_LIGHT"] if busy else "#2f9e48",
                                     text_color_disabled=C["MUTED"])
            self.stop_btn.configure(state="normal" if alive else "disabled",
                                    fg_color="#d9443a" if alive else C["CARD_LIGHT"],
                                    text_color_disabled=C["MUTED"])

    def _set_language(self, value):
        self.c.settings.set("language", value.lower())
        i18n.set_language(value.lower())
        W.popup_info("Language / Langue", tr("Restart Cocoto to translate every text.",
                                             "Relance Cocoto pour traduire tous les textes."))

    def _choose_theme(self):
        if windows.theme_dialog(self, self.c.settings):
            W.popup_info(tr("Theme", "Thème"), tr("Theme saved: applied at the next start.",
                                                 "Thème enregistré : appliqué au prochain lancement."))

    # ================================================================ onglets
    def _build_nav(self):
        nav = ctk.CTkFrame(self, fg_color=C["NAV_BG"], corner_radius=12, border_width=1, border_color=C["BORDER"])
        nav.pack(fill="x", padx=14, pady=(0, 10))
        row = tk.Frame(nav, bg=C["NAV_BG"])
        row.pack(fill="x", padx=4, pady=4)
        self.nav_buttons = {}
        for i, page in enumerate(PAGES):
            row.grid_columnconfigure(i, weight=1)
            b = ctk.CTkButton(row, text=tr(*PAGE_TEXT[page]), width=20, height=32, corner_radius=8, font=W.font(13, True),
                              fg_color="transparent", hover_color=C["CARD_LIGHT"], text_color=C["MUTED"],
                              command=lambda p=page: self.show_page(p))
            b.grid(row=0, column=i, sticky="ew", padx=1)
            self.nav_buttons[page] = b

    def show_page(self, page: str):
        self.page = page
        for p, b in self.nav_buttons.items():
            on = p == page
            b.configure(fg_color=C["ACCENT_SOFT"] if on else "transparent", text_color=C["GOLD"] if on else C["MUTED"])
        self._show()

    def _page_frame(self, mode: str, page: str):
        """La page (construite si besoin). « system » est commune aux deux modes."""
        if page == "system":
            if self._system_page is None:
                self._system_page = W.ScrollPage(self.content)
                self._page_system(self._system_page.inner)
            return self._system_page
        if page not in self.frames[mode]:
            builder = {"config": self._page_config, "heroes": self._page_heroes, "upgrade": self._page_upgrade,
                       "stats": self._page_stats, "profile": self._page_profile}[page]
            if page == "upgrade":
                f = tk.Frame(self.content, bg=C["BG"])
                builder(f, mode, self.binders[mode])
            else:
                f = W.ScrollPage(self.content)
                builder(f.inner, mode, self.binders[mode])
            self.frames[mode][page] = f
        return self.frames[mode][page]

    def _show(self):
        f = self._page_frame(self.c.state.mode, self.page)
        if f is self._shown:
            return
        if self._shown is not None:
            self._shown.pack_forget()
        f.pack(fill="both", expand=True)
        self._shown = f

    def _prebuild(self):
        """Construit une page manquante par temps mort, pour que les onglets s'ouvrent sans attendre."""
        cur = self.c.state.mode
        for mode in (cur, "BH" if cur == "TH" else "TH"):
            for page in PAGES:
                if (page == "system" and self._system_page is None) or (page != "system" and page not in self.frames[mode]):
                    self._page_frame(mode, page)
                    self.after(60, self._prebuild)
                    return

    def switch_mode(self, mode):
        if self.c.state.running and mode != (self.c.state.running_mode or mode):
            W.popup_info(tr("Bot running", "Bot en marche"), tr("Stop the bot before changing mode.",
                                                               "Arrête le bot avant de changer de mode."))
            self.mode_var.set(self._mode_label(self.c.state.running_mode))
            return
        self.c.state.mode = mode
        self.c.settings.set("mode", mode)
        self.mode_var.set(self._mode_label(mode))
        if self._kpi_mode != mode:
            self._kpi_mode = mode
            for tile, (_key, icon, en, fr, color) in zip(self.kpis, KPIS[mode]):
                tile.relabel(icon, tr(en, fr), color)
        self.show_page(self.page)
        self._refresh_status()
        self._update_numbers()

    # ================================================================ page Réglages
    def _field(self, sec: W.Section, text, var, width=120, help_=None, indent=False, suffix=None):
        right = sec.row(text, help_, indent=indent)
        if suffix:
            W.tklabel(right, suffix, muted=True).pack(side="right", padx=(6, 0))
        W.entry(right, var, width).pack(side="right")
        return right

    def _toggle(self, sec: W.Section, text, var, help_=None):
        right = sec.row(text, help_)
        W.switch(right, "", var).pack(side="right")
        return right

    def _page_config(self, page, mode, b):
        army = W.Section(page, tr("Army", "Armée"))
        army.pack(fill="x", pady=(0, 10))
        right = army.row("Slots" + (" (1-12)" if mode == "TH" else " (1-10)"), (
            "auto (recommended): the bot reads your army bar at each battle and deploys every card. "
            "Or card numbers from the left, e.g. 1 2 3 4.",
            "auto (conseillé) : le bot lit ta barre d'armée à chaque combat et pose toutes les cartes. "
            "Sinon les numéros des cartes depuis la gauche, ex. 1 2 3 4."))
        W.entry(right, b.var("slots"), 140).pack(side="right")
        W.secondary(right, tr("Read from game", "Lire du jeu"), lambda: self._set_army_from_game(mode),
                    width=100, height=30).pack(side="right", padx=(0, 8))
        self._field(army, tr("Count per slot", "Nombre par slot"), b.var("number"), 140, (
            "Number of clicks for each slot, e.g. 10 10 5 5 (ignored in auto).",
            "Nombre de clics pour chaque slot, ex. 10 10 5 5 (ignoré en auto)."))
        if mode == "TH":
            self._field(army, tr("Spell slots", "Slots de sorts"), b.var("spell"), 140)
            self._field(army, tr("Troop spacing", "Écartement des troupes"), b.var("deploy_spread"), 70, (
                "0 = troops grouped in the middle of the side, 100 = spread along the whole side.",
                "0 = troupes groupées au milieu du côté, 100 = étalées sur tout le côté."), suffix="%")

            loot = W.Section(page, tr("Minimum loot", "Butin minimum"),
                             tr("A base is attacked only if it has at least this much.",
                                "Une base n'est attaquée que si elle a au moins ce butin."))
            loot.pack(fill="x", pady=(0, 10))
            grid = tk.Frame(loot.body, bg=C["CARD"])
            grid.pack(fill="x", pady=(4, 6))
            grid.grid_columnconfigure((0, 1, 2), weight=1, uniform="l")
            for i, (key, icon, en, fr) in enumerate((("gold", "gold.png", "Gold", "Or"),
                                                     ("elixir", "elixir.png", "Elixir", "Élixir"),
                                                     ("dark", "dark.png", "Dark", "Noir"))):
                cell = tk.Frame(grid, bg=C["CARD"])
                cell.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 5, 0 if i == 2 else 5))
                ctk.CTkLabel(cell, text=" " + tr(en, fr), image=W.image(icon, (18, 18)), compound="left",
                             font=W.font(12), text_color=C["MUTED"], height=22).pack(anchor="w")
                W.entry(cell, b.var(key), 100).pack(fill="x")
            self._field(loot, tr("Early end", "Fin anticipée"), b.var("early_end"), 140, (
                "Ends the battle early (Surrender). 120s: 120 s after everything is deployed. 50%: when 50 % of "
                "the available loot is taken. 60d: at 60 % destruction. 20f: when the remaining loot has not "
                "moved for 20 s. Combine them: 120s 50%.",
                "Termine le combat plus tôt (Surrender). 120s : 120 s après la pose complète. 50% : quand 50 % "
                "du loot disponible est pris. 60d : à 60 % de destruction. 20f : quand le loot restant ne bouge "
                "plus depuis 20 s. Combinables : 120s 50%."))
            self._section_battle(page, b)
        self._section_village(page, mode, b)
        self._section_timing(page, b)

    def _section_battle(self, page, b):
        sec = W.Section(page, tr("Battle", "Combat"))
        sec.pack(fill="x", pady=(0, 10))
        self._toggle(sec, tr("Request troops", "Demander des renforts"), b.var("request_cc", "bool"), (
            "Before each battle, asks your clan for reinforcements (Request → Send) when available.",
            "Avant chaque combat, demande des renforts à ton clan (Request → Send) quand c'est possible."))
        self._toggle(sec, tr("Cake", "Gâteau"), b.var("cake_enabled", "bool"), (
            "Before each battle, uses the Cake in My Army to refill your Clan Castle.",
            "Avant chaque combat, utilise le gâteau dans My Army pour remplir ton château de clan."))
        self._toggle(sec, tr("Donate", "Dons"), b.var("donate", "bool"), (
            "At START and when the chat shows a red badge, fills your clan mates' requests.",
            "Au START et quand le chat affiche une pastille rouge, remplit les demandes de ton clan."))
        right = sec.row(tr("Free requests", "Demandes libres"), indent=True)
        self.free_count = tk.StringVar()
        W.secondary(right, tr("Choose…", "Choisir…"),
                    lambda: windows.open_donate_units(self, self.c, self._refresh_free), width=90, height=28
                    ).pack(side="right")
        W.tklabel(right, "", textvariable=self.free_count, muted=True, size=12).pack(side="right", padx=8)
        self._refresh_free()
        self._toggle(sec, tr("Clan Games", "Jeux de clan"), b.var("clan_games", "bool"), (
            "Starts a Home Village challenge doable with any army; trashes impossible ones.",
            "Lance un défi du village principal faisable avec n'importe quelle armée ; jette les impossibles."))
        self._toggle(sec, tr("Treasure event", "Événement Trésor"), b.var("treasure_enabled", "bool"), (
            "During the Treasure event: after each battle the bot opens the treasure chest.",
            "Pendant l'événement Trésor : après chaque combat le bot ouvre le coffre."))
        self._toggle(sec, tr("Ranked battles", "Combats classés (Ranked)"), b.var("ranked", "bool"), (
            "Uses the Ranked attacks left in the tournament first, then farms normally.",
            "Utilise d'abord les attaques Ranked restantes du tournoi, puis farme normalement."))
        self._field(sec, tr("Stop at", "S'arrêter à"), b.var("ranked_max"), 60, indent=True)
        self._toggle(sec, tr("Clan Capital raids", "Raids de la capitale"), b.var("raids", "bool"), (
            "During the Raid Weekend, does all your raid attacks at START (lowest districts first).",
            "Pendant le Raid Weekend, fait toutes tes attaques de raid au START (districts les plus bas d'abord)."))

    def _refresh_free(self):
        n = len(self.c.settings.get("donate_free_units") or [])
        if hasattr(self, "free_count"):
            self.free_count.set(tr(f"{n} selected", f"{n} choisie(s)") if n else tr("nothing given", "rien donné"))

    def _section_village(self, page, mode, b):
        sec = W.Section(page, "Village")
        sec.pack(fill="x", pady=(0, 10))
        self._toggle(sec, tr("Upgrade walls", "Améliorer les murs"), b.var("click_wall_enabled", "bool"), (
            "When the loot farmed since START reaches the Wall cost, the bot upgrades a wall at that price. "
            "The budget includes your storages at START.",
            "Quand le loot farmé depuis START atteint le prix d'un mur, le bot améliore un mur à ce prix. "
            "Le budget compte aussi tes réserves au START."))
        self._field(sec, tr("Wall cost", "Prix d'un mur"), b.var("wall_cost"), 110, indent=True)
        if mode == "TH":
            self._field(sec, tr("Walls when storage ≥", "Murs quand réserve ≥"), b.var("wall_fill"), 60,
                        indent=True, suffix="%")
        self._toggle(sec, tr("Collect resources", "Récolter les ressources"), b.var("collect_enabled", "bool"), (
            "Collects your mines and collectors every few battles (one click per resource).",
            "Récolte tes mines et collecteurs tous les quelques combats (un clic par ressource)."))
        if mode != "TH":
            return
        self._toggle(sec, tr("Stop when full", "Arrêter si plein"), b.var("stop_when_full", "bool"), (
            "Stops attacking when the watched storages are full (kinds: gold elixir dark).",
            "Arrête d'attaquer quand les réserves surveillées sont pleines (types : gold elixir dark)."))
        self._field(sec, tr("Watch", "Surveiller"), b.var("stop_full_kinds"), 150, indent=True)
        self._toggle(sec, tr("Builder Base when full", "Base des ouvriers si plein"), b.var("bh_when_full", "bool"))
        self._toggle(sec, tr("Suggested upgrades", "Améliorations suggérées"), b.var("suggested_upgrades", "bool"), (
            "Upgrades the buildings the game suggests, keeping 1 builder free for walls.",
            "Améliore les bâtiments suggérés par le jeu en gardant 1 ouvrier libre pour les murs."))
        right = sec.row(tr("Include heroes", "Inclure les héros"), indent=True)
        W.switch(right, "", b.var("suggested_heroes", "bool")).pack(side="right")
        self._toggle(sec, tr("Keep a builder for walls", "Garder un ouvrier pour les murs"),
                     b.var("keep_builder_walls", "bool"))

    def _section_timing(self, page, b):
        sec = W.Section(page, tr("Timing", "Horaires et pauses"))
        sec.pack(fill="x", pady=(0, 10))
        self._toggle(sec, tr("Random breaks", "Pauses au hasard"), b.var("breaks_enabled", "bool"), (
            "Play: farms for a random time in this range (minutes). Break: then pauses in the village. "
            "Closed (background / ADB only): closes the game during each break for a random time in this "
            "range, and outside your schedule.",
            "Jeu : farme pendant une durée au hasard dans cette plage (minutes). Pause : puis pause au village. "
            "Fermé (arrière-plan / ADB seulement) : ferme le jeu pendant chaque pause pour une durée de cette "
            "plage, et hors de tes horaires."))
        right = sec.row(tr("Minutes", "Minutes"), indent=True)
        for text, key in reversed(((tr("Play", "Jeu"), "break_play"), (tr("Break", "Pause"), "break_pause"),
                                   (tr("Closed", "Fermé"), "break_closed"))):
            W.entry(right, b.var(key), 64).pack(side="right")
            W.tklabel(right, text, muted=True, size=12).pack(side="right", padx=(10, 4))
        self._toggle(sec, tr("Schedule", "Horaires"), b.var("schedule_enabled", "bool"), (
            "The bot only farms in these time ranges, e.g. 9-12 14:30-23.",
            "Le bot ne farme que dans ces plages, ex. 9-12 14:30-23."))
        self._field(sec, tr("Time ranges", "Plages"), b.var("schedule_hours"), 160, indent=True)
        self._field(sec, tr("Delay between battles", "Délai entre combats"), b.var("battle_delay"), 70, suffix="s")

    # ================================================================ page Héros
    def _page_heroes(self, page, mode, b):
        if mode == "TH":
            sec = W.Section(page, tr("Hero abilities", "Capacités des héros"),
                            tr("Delay: seconds after everything is deployed. 2+1 = between 1 and 3 s, drawn "
                               "again at each battle.", "Délai : secondes après la pose complète. 2+1 = entre 1 "
                               "et 3 s, tiré à chaque combat."))
            sec.pack(fill="x", pady=(0, 10))
            for i, (key, name) in enumerate(zip(HERO_KEYS, HERO_NAMES), start=1):
                right = sec.row(name, icon=W.image(f"hero_{i}.png", (28, 28)))
                W.switch(right, "", b.nested("heroes", key, "enabled", "bool")).pack(side="right")
                W.entry(right, b.nested("heroes", key, "delay", default="0"), 64).pack(side="right", padx=(0, 4))
                W.tklabel(right, tr("delay (s)", "délai (s)"), muted=True, size=12).pack(side="right", padx=6)
        else:
            sec = W.Section(page, tr("Builder Base heroes", "Héros de la base des ouvriers"),
                            tr("Gauge: level of the ability gauge to wait for.",
                               "Jauge : niveau de la jauge de capacité à attendre."))
            sec.pack(fill="x", pady=(0, 10))
            for key in BH_HERO_KEYS:
                right = sec.row(BH_HERO_NAMES[key], icon=W.image(f"bh_hero_{key}_icon.png", (28, 28)))
                W.switch(right, "", b.nested("heroes", key, "enabled", "bool")).pack(side="right")
                W.segmented(right, ["1", "2", "3"], b.nested("heroes", key, "level", default="1"),
                            width=110, height=28).pack(side="right", padx=(0, 10))
                W.tklabel(right, tr("gauge", "jauge"), muted=True, size=12).pack(side="right", padx=6)

    # ================================================================ page Améliorations
    def _page_upgrade(self, page, mode, b):
        """Un sous-onglet par catégorie, construit au premier affichage (des centaines de lignes :
        widgets Tk légers, pas CustomTkinter)."""
        from ..features.upgrades import BH_BUILDINGS, BH_LAB_TROOPS, TH_BUILDINGS, TH_LAB
        cats = dict(TH_BUILDINGS if mode == "TH" else BH_BUILDINGS)
        cats["Lab"] = TH_LAB["Lab"] if mode == "TH" else BH_LAB_TROOPS
        head = W.Section(page, tr("Upgrades", "Améliorations"),
                         tr("Like walls, ticked buildings are paid with the loot the bot farmed (TH) or the "
                            "Builder Base storages (BH). Qty = how many upgrades; price and resource optional.",
                            "Comme les murs, les bâtiments cochés sont payés avec le loot farmé (TH) ou les "
                            "réserves de la BH. Qté = nombre d'améliorations ; prix et ressource facultatifs."))
        head.pack(fill="x", pady=(0, 10))
        cat_var = tk.StringVar(value=next(iter(cats)))
        W.segmented(head.body, list(cats), cat_var, lambda v: show(v)).pack(fill="x", pady=(4, 0))
        holder = ctk.CTkFrame(page, fg_color=C["CARD"], corner_radius=14, border_width=1, border_color=C["BORDER"])
        holder.pack(fill="both", expand=True)
        lists: dict[str, tk.Frame] = {}
        current = {"f": None}

        def show(cat):
            if cat not in lists:
                lists[cat] = self._upgrade_list(holder, cats[cat], cat, "lab" if cat == "Lab" else "upgrades", b)
            if current["f"] is not None:
                current["f"].pack_forget()
            lists[cat].pack(fill="both", expand=True, padx=8, pady=8)
            current["f"] = lists[cat]

        self.after(10, lambda: show(cat_var.get()))

    def _upgrade_list(self, holder, names, cat, key, b):
        bg, bg2 = C["CARD"], theme.mix(C["CARD"], C["CARD_LIGHT"], 0.55)
        outer = W.ScrollPage(holder, bg=bg)
        inner = outer.inner
        inner.grid_columnconfigure(1, weight=1)
        hdr = dict(bg=bg, fg=C["MUTED"], font=(W.FONT, 10, "bold"), anchor="w")
        for col, text in enumerate(("", tr("Name", "Nom"), tr("Qty", "Qté"), tr("Price", "Prix"), tr("Res.", "Ress."))):
            tk.Label(inner, text=text.upper(), **hdr).grid(row=0, column=col, sticky="w", padx=6, pady=(4, 6))
        for r, name in enumerate(names, start=1):
            item = f"{cat}|{name}"
            rb = bg2 if r % 2 else bg
            var = b.nested(key, item, "enabled", "bool")
            box = tk.Label(inner, bg=rb, font=(W.FONT, 14), cursor="hand2", width=2)

            def paint(*_a, v=var, lb=box):
                on = bool(v.get())
                lb.configure(text="☑" if on else "☐", fg=C["GOLD"] if on else C["MUTED"])
            var.trace_add("write", paint)
            paint()
            box.bind("<Button-1>", lambda _e, v=var: v.set(not bool(v.get())))
            box.grid(row=r, column=0, sticky="nsew")
            tk.Label(inner, text=name, anchor="w", bg=rb, fg=C["TEXT"], font=(W.FONT, 11)).grid(
                row=r, column=1, sticky="nsew", ipadx=6)
            for col, (field, width, default) in enumerate((("count", 4, "1"), ("price", 11, "")), start=2):
                cell = tk.Frame(inner, bg=rb)
                cell.grid(row=r, column=col, sticky="nsew")
                tk.Entry(cell, textvariable=b.nested(key, item, field, default=default), width=width,
                         bg=C["ENTRY_BG"], fg=C["TEXT"], insertbackground=C["TEXT"], relief="flat",
                         font=(W.FONT, 11), highlightthickness=1, highlightbackground=C["BORDER"],
                         highlightcolor=C["GOLD"]).pack(padx=4, pady=3)
            cell = tk.Frame(inner, bg=rb)
            cell.grid(row=r, column=4, sticky="nsew")
            om = tk.OptionMenu(cell, b.nested(key, item, "resource", default="gold"), "gold", "elixir", "dark")
            om.configure(bg=C["CARD_LIGHT"], fg=C["TEXT"], activebackground=C["CARD_HOVER"],
                         activeforeground=C["TEXT"], highlightthickness=0, relief="flat", bd=0, width=7,
                         indicatoron=False, cursor="hand2",
                         font=(W.FONT, 10))
            om["menu"].configure(bg=C["CARD_LIGHT"], fg=C["TEXT"], activebackground=C["GOLD"],
                                 activeforeground=C["ON_ACCENT"])
            om.pack(padx=(4, 6), pady=3)
        return outer

    # ================================================================ page Stats
    def _page_stats(self, page, mode, _b):
        tiles = self.stat_tiles[mode]

        def grid(sec, rows):
            g = tk.Frame(sec.body, bg=C["CARD"])
            g.pack(fill="x", pady=(4, 0))
            g.grid_columnconfigure((0, 1), weight=1, uniform="s")
            for i, (key, icon, en, fr, color) in enumerate(rows):
                t = W.StatTile(g, icon, tr(en, fr), color, big=20)
                t.grid(row=i // 2, column=i % 2, sticky="ew", padx=(0, 5) if i % 2 == 0 else (5, 0), pady=5)
                tiles[key] = t

        loot = W.Section(page, tr("Loot this session", "Butin de la session"))
        loot.pack(fill="x", pady=(0, 10))
        rows = [("gold", "gold.png", "Gold", "Or", C["GOLD"]), ("elixir", "elixir.png", "Elixir", "Élixir", theme.ELIXIR_COLOR)]
        if mode == "TH":
            rows += [("dark", "dark.png", "Dark", "Noir", theme.DARK_COLOR),
                     ("capital", "capital_gold.png", "Capital gold", "Or de capitale", theme.CAPITAL_COLOR)]
        rows += [("walls", "wall_Icon.png", "Walls", "Murs", "#FFA500")]
        grid(loot, rows)
        battles = W.Section(page, tr("Battles", "Combats"))
        battles.pack(fill="x", pady=(0, 10))
        rows = [("attacks", None, "Attacks", "Attaques", None), ("uptime", "uptime.png", "Uptime", "Durée", None),
                ("wins", "win.png", "Wins", "Victoires", "#43c463"), ("losses", "losse.png", "Losses", "Défaites", "#e5584d"),
                ("stars", "stars.png", "Stars", "Étoiles", "#f5c84a")]
        if mode == "TH":
            rows.append(("raids", "raid_swords.png", "Raids", "Raids", None))
        grid(battles, rows)
        W.secondary(page, tr("Reset stats", "Remettre les stats à zéro"), self.c.state.reset_stats,
                    width=220).pack(pady=(0, 10))
        self._update_numbers()

    def _update_numbers(self):
        """Tuiles du panneau de contrôle et de la page Stats (texte changé seulement si différent)."""
        st = self.c.state
        up = _fmt_uptime(st.uptime())
        mode = self.c.state.mode
        for tile, (key, *_r) in zip(self.kpis, KPIS[mode]):
            tile.set(up if key == "uptime" else fmt_number(st.stats[mode].get(key, 0)))
        for m, tiles in self.stat_tiles.items():
            for key, tile in tiles.items():
                tile.set(up if key == "uptime" else fmt_number(st.stats[m].get(key, 0)))

    # ================================================================ page Profils
    def _page_profile(self, page, mode, _b):
        sec = W.Section(page, tr("Profiles", "Profils"),
                        tr("▶ = active profile. Settings are saved in it with « Save changes ».",
                           "▶ = profil actif. Les réglages y sont enregistrés avec « Enregistrer »."))
        sec.pack(fill="x", pady=(0, 10))
        wrap = tk.Frame(sec.body, bg=C["CARD"])
        wrap.pack(fill="x", pady=(6, 0))
        lb = tk.Listbox(wrap, height=8, exportselection=False, bg=C["ENTRY_BG"], fg=C["TEXT"],
                        selectbackground=C["GOLD"], selectforeground=C["ON_ACCENT"], highlightthickness=1,
                        highlightbackground=C["BORDER"], highlightcolor=C["BORDER"], borderwidth=0,
                        activestyle="none", font=(W.FONT, 12))
        lb.pack(side="left", fill="both", expand=True)
        self.profile_lists[mode] = lb
        col = tk.Frame(wrap, bg=C["CARD"])
        col.pack(side="right", fill="y", padx=(12, 0))
        W.button(col, tr("Load", "Charger"), lambda: self._p_load(mode), width=150).pack(pady=(0, 6))
        W.button(col, tr("Save changes", "Enregistrer"), lambda: self._p_save(mode), width=150,
                 color=C["CARD_LIGHT"], hover=C["CARD_HOVER"], text_color=C["GOLD"]).pack(pady=(0, 6))
        for text, fn in ((tr("New", "Créer"), self._p_create), (tr("Rename", "Renommer"), self._p_rename),
                         (tr("Delete", "Supprimer"), self._p_delete)):
            W.secondary(col, text, lambda f=fn: f(mode), width=150).pack(pady=(0, 6))
        share = tk.Frame(sec.body, bg=C["CARD"])
        share.pack(fill="x", pady=(10, 0))
        share.grid_columnconfigure((0, 1), weight=1, uniform="p")
        W.secondary(share, tr("Copy share code", "Copier le code de partage"), lambda: self._p_share(mode)).grid(
            row=0, column=0, sticky="ew", padx=(0, 5))
        W.secondary(share, tr("Import a code", "Importer un code"), lambda: self._p_import(mode)).grid(
            row=0, column=1, sticky="ew", padx=(5, 0))
        self._refresh_profiles(mode)
        self._accounts_card(page, mode)

    def _selected(self, mode):
        lb = self.profile_lists.get(mode)
        sel = lb.curselection() if lb is not None else ()
        return lb.get(sel[0]).lstrip("▶ ").strip() if sel else None

    def _refresh_profiles(self, mode):
        lb = self.profile_lists.get(mode)
        if lb is None:
            return
        lb.delete(0, "end")
        active = self.c.active_profile(mode)
        for name in self.c.profiles[mode].names():
            lb.insert("end", ("  ▶ " if name == active else "     ") + name)

    def _p_create(self, mode):
        name = W.popup_ask(tr("Create profile", "Créer un profil"), tr("Name of the new profile:", "Nom du nouveau profil :"))
        if not name:
            return
        if name in self.c.profiles[mode].names():
            W.popup_error("Profil", tr("This profile already exists!", "Ce profil existe déjà !"))
            return
        self.c.save_profile(mode, name)
        self._refresh_profiles(mode)

    def _p_rename(self, mode):
        old = self._selected(mode)
        if not old:
            return
        new = W.popup_ask(tr("Rename profile", "Renommer le profil"), f"« {old} » →", old)
        if new and self.c.profiles[mode].rename(old, new):
            if self.c.active_profile(mode) == old:
                self.c.settings.set(f"active_profile_{mode.lower()}", new)
            self._refresh_profiles(mode)

    def _p_delete(self, mode):
        name = self._selected(mode)
        if name and W.popup_yesno(tr("Delete profile", "Supprimer le profil"),
                                  tr(f"Delete '{name}'? This cannot be undone.", f"Supprimer « {name} » ? C'est définitif.")):
            self.c.profiles[mode].delete(name)
            self._refresh_profiles(mode)

    def _p_load(self, mode):
        name = self._selected(mode)
        if name:
            self.c.apply_profile(mode, name)

    def _p_save(self, mode):
        name = self.c.active_profile(mode) or self._selected(mode)
        if not name:
            W.popup_info(tr("No active profile", "Aucun profil actif"),
                         tr("Load or create a profile before saving.", "Charge ou crée un profil avant de sauvegarder."))
            return
        self.c.save_profile(mode, name)
        self._refresh_profiles(mode)

    def _p_share(self, mode):
        name = self._selected(mode) or self.c.active_profile(mode)
        cfg = self.c.profiles[mode].load(name) if name else None
        if not cfg:
            W.popup_info("Code", tr("Select a saved profile first.", "Sélectionne d'abord un profil sauvegardé."))
            return
        code = profile_to_code(mode, cfg, self.c.private_texts())
        self.clipboard_clear()
        self.clipboard_append(code)
        W.popup_info(tr("Profile code", "Code de profil"),
                     tr(f"Code of '{name}' copied ({len(code)} characters). Never contains names, webhook or token.",
                        f"Code de « {name} » copié ({len(code)} caractères). Il ne contient jamais pseudos, webhook ni token."))

    def _p_import(self, mode):
        text = W.popup_ask(tr("Import code", "Importer un code"), tr("Paste the profile code:", "Colle le code du profil :"))
        if not text:
            return
        try:
            code_mode, data = profile_from_code(text)
        except ValueError as exc:
            W.popup_error("Code", str(exc))
            return
        if code_mode != mode:
            W.popup_error("Code", tr("This code is for the other village: switch mode first.",
                                     "Ce code est pour l'autre village : change de mode d'abord."))
            return
        name = W.popup_ask(tr("Imported", "Importé"), tr("Name of the imported profile:", "Nom du profil importé :"))
        if not name:
            return
        if name in self.c.profiles[mode].names() and not W.popup_yesno("Code", tr("Replace it?", "Le remplacer ?")):
            return
        self.c.profiles[mode].save(name, data)
        self.c.apply_profile(mode, name)
        self._refresh_profiles(mode)

    def _profile_loaded(self, mode, _name):
        self.binders[mode].refresh()
        self._refresh_profiles(mode)
        self._refresh_status()

    def _accounts_card(self, page, mode):
        s = self.c.settings
        key = "accounts" if mode == "TH" else "accounts_bh"
        data = s.get(key) or {}
        sec = W.Section(page, tr("Accounts", "Comptes"))
        sec.pack(fill="x", pady=(0, 10))
        ev = tk.BooleanVar(value=bool(data.get("enabled")))
        every = tk.StringVar(value=str(data.get("every", "3")))
        kind = tk.StringVar(value=data.get("name_kind", "game"))
        names = [tk.StringVar(value=(data.get("names", []) + [""] * 6)[i]) for i in range(6)]
        profs = [tk.StringVar(value=(data.get("profiles", []) + [""] * 6)[i]) for i in range(6)]

        def save(*_a):
            s.set(key, {"enabled": bool(ev.get()), "every": every.get(), "name_kind": kind.get(),
                        "names": [v.get() for v in names], "profiles": [v.get() for v in profs]})

        for v in [ev, every, kind] + names + profs:
            v.trace_add("write", save)
        self._toggle(sec, tr("Switch accounts", "Changer de compte"), ev, (
            "Link all your accounts to Supercell ID. Every N battles the bot switches to the next account of the "
            "list and loads its profile.", "Lie tous tes comptes à Supercell ID. Tous les N combats le bot passe au "
            "compte suivant de la liste et charge son profil."))
        self._field(sec, tr("Every", "Tous les"), every, 50, indent=True, suffix=tr("battles", "combats"))
        right = sec.row(tr("Names are", "Noms"), indent=True)
        W.segmented(right, ["game", "scid"], kind, width=120, height=28).pack(side="right")
        prof_names = ["(keep current)"] + self.c.profiles[mode].names()
        for i in range(6):
            right = sec.row(f"{i + 1}.", divider=False)
            W.option_menu(right, prof_names, profs[i], 170).pack(side="right")
            W.entry(right, names[i], 200).pack(side="right", padx=(0, 8))

    # ================================================================ page Système (commune)
    def _page_system(self, page):
        s = self.c.settings
        sec = W.Section(page, tr("Game connection", "Connexion au jeu"))
        sec.pack(fill="x", pady=(0, 10))
        labels = {"screen": tr("Screen (mouse)", "Écran (souris)"), "window": tr("Background window", "Fenêtre arrière-plan"),
                  "adb": "ADB / MuMu"}
        var = tk.StringVar(value=labels.get(s.get("backend", "screen")))
        rev = {v: k for k, v in labels.items()}
        line = tk.Frame(sec.body, bg=C["CARD"])
        line.pack(fill="x", pady=(6, 6))
        W.segmented(line, list(labels.values()), var, lambda v: s.set("backend", rev[v])).pack(
            side="left", fill="x", expand=True)
        W.help_button(line, tr("Connection", "Connexion"), (
            "Screen: the game is full screen on a 16:9 screen, the bot uses your mouse.\n"
            "Background window (Windows): the bot captures and clicks the Google Play Games window, "
            "you can use your PC.\nADB: an Android emulator (MuMu, BlueStacks…) in 1920x1080 is best; "
            "MuMu 12 instance n listens on 127.0.0.1:16384+32×(n-1)."), (
            "Écran : le jeu est en plein écran sur un écran 16:9, le bot utilise ta souris.\n"
            "Fenêtre arrière-plan (Windows) : le bot capture et clique la fenêtre de Google Play Games, "
            "tu peux utiliser ton PC.\nADB : un émulateur Android (MuMu, BlueStacks…), idéalement en "
            "1920x1080 ; l'instance n de MuMu 12 écoute sur 127.0.0.1:16384+32×(n-1).")).pack(side="left", padx=(8, 0))
        for text, key in ((tr("ADB device", "Appareil ADB"), "adb_device"), (tr("ADB path", "Chemin d'ADB"), "adb_path")):
            v = tk.StringVar(value=s.get(key) or "")
            v.trace_add("write", lambda *_a, k=key, vv=v: s.set(k, vv.get()))
            self._field(sec, text, v, 280)
        nv = tk.BooleanVar(value=bool(s.get("desktop_notify")))
        nv.trace_add("write", lambda *_a: s.set("desktop_notify", bool(nv.get())))
        self._toggle(sec, tr("Windows notifications", "Notifications Windows"), nv)
        right = sec.row(tr("Several games at once", "Plusieurs jeux en même temps"))
        W.secondary(right, tr("New instance", "Nouvelle instance"),
                    lambda: dashboard.launch_instance(max(list(dashboard.read_all()) + [paths.INSTANCE]) + 1),
                    width=150, height=30).pack(side="right")
        self._discord_card(page)

    def _discord_card(self, page):
        s = self.c.settings
        sec = W.Section(page, "Discord", tr("Notifications and remote control.",
                                            "Notifications et contrôle à distance."))
        sec.pack(fill="x", pady=(0, 10))
        for text, key, w in ((tr("Webhook", "Webhook"), "webhook", 300), (tr("ID to ping", "ID à mentionner"), "discord_id", 200),
                             (tr("Bot token", "Token du bot"), "remote_token", 300),
                             (tr("Your user ID", "Ton ID utilisateur"), "remote_user_id", 200)):
            v = tk.StringVar(value=s.get(key) or "")
            v.trace_add("write", lambda *_a, k=key, vv=v: s.set(k, vv.get().strip()))
            right = sec.row(text)
            e = W.entry(right, v, w)
            if key == "remote_token":
                e.configure(show="•")
            e.pack(side="right")
        rv = tk.BooleanVar(value=bool(s.get("remote_enabled")))
        rv.trace_add("write", lambda *_a: s.set("remote_enabled", bool(rv.get())))
        self._toggle(sec, tr("Remote control (restart)", "Contrôle à distance (relance)"), rv, (
            "Control Cocoto from Discord with your own bot: /status /start /stop /screen /settings /set /profile. "
            "Create a bot on discord.com/developers, invite it to your server, paste its token here.",
            "Pilote Cocoto depuis Discord avec ton propre bot : /status /start /stop /screen /settings /set "
            "/profile. Crée un bot sur discord.com/developers, invite-le sur ton serveur, colle son token ici."))

    # ================================================================ actions
    def start(self, mode):
        errors, warnings = self.c.validate(mode)
        if errors:
            W.popup_error(tr("Settings", "Réglages"), "• " + "\n• ".join(errors))
            return
        if warnings and not W.popup_yesno(tr("Check your settings", "Vérifie tes réglages"),
                                          "• " + "\n• ".join(warnings) + "\n\n" + tr("Start anyway?", "Lancer quand même ?")):
            return
        err = self.c.start(mode)
        if err:
            W.popup_error("Cocoto", err)
        self._refresh_status()

    def _autostart(self, mode):
        errors, _warnings = self.c.validate(mode)
        err = "; ".join(errors) if errors else self.c.start(mode)
        if err:
            log(f"❌ Démarrage automatique impossible : {err}")

    def _set_army_from_game(self, mode):
        def work():
            err = self.c.prepare_backend() if self.c.game is None else None
            if err:
                self.run_in_ui(lambda: W.popup_error(tr("Read army", "Lire l'armée"), err), wait=False)

        def apply():
            from ..features.attack import read_army_stable
            army = read_army_stable(self.c.game)
            troops = [c for c in army if not c.spell]
            if not army:
                W.popup_info(tr("Read army", "Lire l'armée"),
                             tr("Army bar not found: start a search and stay on the enemy base.",
                                "Barre d'armée introuvable : lance une recherche et reste sur la base ennemie."))
                return
            cfg = self.c.cfg[mode]
            cfg.set("slots", " ".join(str(i + 1) for i in range(len(army))))
            cfg.set("number", " ".join(str(c.count or 1) for c in army))
            if mode == "TH":
                cfg.set("spell", " ".join(str(i + 1) for i, c in enumerate(army) if c.spell))
            self.binders[mode].refresh()
            W.popup_info(tr("Read army", "Lire l'armée"),
                         tr(f"{len(troops)} troop card(s), {len(army) - len(troops)} spell card(s) read.",
                            f"{len(troops)} carte(s) de troupes, {len(army) - len(troops)} de sorts lues."))

        def run():
            work()
            if self.c.game is not None:
                self.run_in_ui(apply, wait=False)

        threading.Thread(target=run, daemon=True).start()

    def _tick(self):
        if self.wm_state() != "iconic":       # fenêtre réduite : rien à redessiner
            self._update_numbers()
            self._refresh_status()            # rattrape la fin du thread (arrêt en cours → arrêté)
        self.after(1000, self._tick)

    def _hotkey(self):
        def toggle():
            self.run_in_ui(lambda: self.c.stop() if self.c.state.running else self.start(self.c.state.mode), wait=False)
        try:
            import keyboard  # type: ignore
            keyboard.add_hotkey("f1", toggle)
        except Exception:
            self.bind_all("<F1>", lambda _e: toggle())

    def _offer_restore(self):
        data = self.c.previous_session()
        if not data:
            return
        st = data.get("stats", {}).get("TH", {})
        when = time.strftime("%d/%m %H:%M", time.localtime(data.get("saved_at", 0)))
        msg = tr(f"Restore the stats of your last session?\n\n{when} — {st.get('attacks', 0)} attacks, "
                 f"{fmt_number(st.get('gold', 0))} gold",
                 f"Remettre les stats de ta dernière session ?\n\n{when} — {st.get('attacks', 0)} attaques, "
                 f"{fmt_number(st.get('gold', 0))} or")
        if W.popup_yesno(tr("Previous session", "Session précédente"), msg):
            self.c.restore_session(data)

    def _on_close(self):
        self.c.stop()
        self.c.save_session_stats()
        self.destroy()


def run(controller, autostart: str | None = None) -> None:
    App(controller, autostart).mainloop()
