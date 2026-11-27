"""Contrôleur : relie réglages, profils, état, moteur d'entrée et threads du bot.
Utilisé par l'interface, le tableau de bord multi-instances et le contrôle Discord."""
from __future__ import annotations

import threading
import time
import traceback
from typing import Callable

from . import i18n, layout, notify, paths, vision
from .backends import make_backend
from .config import LiveConfig, PROFILE_CODE_KEYS
from .game import Game
from .logger import log
from .state import BotState, BotStopped
from .storage import ProfileStore, Settings, read_json_safely, write_json_safely
from .validate import validate_bh, validate_th
from .vision import Templates


class Controller:
    def __init__(self):
        self.settings = Settings()
        i18n.set_language(self.settings.get("language", "fr"))
        notify.bind_settings(self.settings)
        layout.load_overrides()
        self.profiles = {"TH": ProfileStore("TH"), "BH": ProfileStore("BH")}
        self.cfg = {m: LiveConfig(m, self._initial_profile(m)) for m in ("TH", "BH")}
        self.state = BotState()
        self.state.mode = self.settings.get("mode", "TH")
        self.templates = Templates()
        self.game: Game | None = None
        self.on_message: Callable[[str, str], None] = lambda t, m: log(f"ℹ️ {t} : {m}")
        self.on_profile_loaded: Callable[[str, str], None] = lambda mode, name: None
        self.raid_store: dict = self.settings.get("raids_state") or {}
        self._stats_path = paths.data_path("session_stats.json")
        notify.start_freeze_watchdog(self.state, self.screenshot_jpeg)

    # ---------------------------------------------------------------- profils
    def _initial_profile(self, mode: str) -> dict:
        name = self.settings.get(f"active_profile_{mode.lower()}") or ""
        return (self.profiles[mode].load(name) if name else None) or {}

    def active_profile(self, mode: str) -> str:
        return self.settings.get(f"active_profile_{mode.lower()}") or ""

    def apply_profile(self, mode: str, name: str) -> bool:
        data = self.profiles[mode].load(name)
        if data is None:
            log(f"⚠️ Profil « {name} » introuvable")
            return False
        self.cfg[mode].replace(data)
        self.settings.set(f"active_profile_{mode.lower()}", name)
        log(f"⚙️ Profil {mode} « {name} » chargé")
        self.on_profile_loaded(mode, name)
        return True

    def save_profile(self, mode: str, name: str | None = None) -> str:
        name = name or self.active_profile(mode) or "Default"
        data = {k: v for k, v in self.cfg[mode].snapshot().items() if k in PROFILE_CODE_KEYS[mode]}
        self.profiles[mode].save(name, data)
        self.settings.set(f"active_profile_{mode.lower()}", name)
        log(f"💾 Profil {mode} « {name} » sauvegardé")
        return name

    def private_texts(self) -> list[str]:
        texts = [self.settings.get("webhook"), self.settings.get("discord_id"),
                 self.settings.get("remote_token")]
        for key in ("accounts", "accounts_bh"):
            texts += (self.settings.get(key) or {}).get("names", [])
        return [t for t in texts if t]

    # ---------------------------------------------------------------- marche / arrêt
    def validate(self, mode: str) -> tuple[list[str], list[str]]:
        webhook = self.settings.get("webhook") or ""
        return (validate_th if mode == "TH" else validate_bh)(self.cfg[mode], webhook)

    def prepare_backend(self) -> str | None:
        """Branche le bot sur le jeu. Retourne un message d'erreur, ou None si tout va bien."""
        kind = self.settings.get("backend", "screen")
        try:
            backend = make_backend(kind, self.settings)
        except Exception as exc:
            return str(exc)
        if hasattr(backend, "ratio_ok") and not backend.ratio_ok():
            return "Le jeu doit être affiché en 16:9 (1920x1080, 2560x1440, 3840x2160…)."
        if kind == "window":
            from .backends.win32 import process_elevated, self_elevated
            if process_elevated(backend.hwnd) and not self_elevated():
                return ("Le jeu tourne en administrateur mais pas Cocoto : Windows bloquerait ses clics. "
                        "Lance Cocoto en administrateur.")
        try:
            if kind == "adb":
                fmt = backend.display_format()
                if fmt:
                    log(f"📱 Écran Android : {fmt[0]}x{fmt[1]} DPI {fmt[2]}")
                    if abs(fmt[0] / fmt[1] - 16 / 9) > 0.02:
                        log("ℹ️ Écran pas en 16:9 : image recomposée (1920x1080 conseillé)")
            if backend.grab() is None:
                return "Jeu introuvable, réduit ou fermé."
        except Exception as exc:   # ADB qui ne répond pas, fenêtre disparue…
            return f"Le jeu ne répond pas : {exc}"
        self.game = Game(backend, self.state, self.templates)
        log(f"🖥️ Moteur : {backend.describe()}")
        return None

    def start(self, mode: str | None = None, auto: bool = False) -> str | None:
        """Lance le bot. Retourne None, ou un message d'erreur à afficher."""
        if self.state.running:
            return "Le bot tourne déjà."
        if self.state.thread and self.state.thread.is_alive():
            return "Le bot finit de s'arrêter, réessaie dans quelques secondes."
        mode = mode or self.state.mode
        errors, _warnings = self.validate(mode)
        if errors:
            return "Corrige ces réglages :\n• " + "\n• ".join(errors)
        err = self.prepare_backend()
        if err:
            return err
        self.state.mode = mode
        self.state.stop_event.clear()
        self.state.reconnect_pending = False
        self.state.started_at = time.monotonic()
        self.state.thread = threading.Thread(target=self._run, args=(mode, auto), daemon=True, name="bot")
        self.state.thread.start()
        self._start_afk()
        log(f"▶️ Bot lancé ({'village principal' if mode == 'TH' else 'base des ouvriers'})")
        self.state.changed()
        return None

    def _start_afk(self) -> None:
        from .features.reconnect import AfkChecker

        def on_disconnect(_key):
            self.state.reconnect_pending = True

        AfkChecker(self.game, on_disconnect).start()

    def _run(self, mode: str, auto: bool) -> None:
        from .bot_bh import BuilderBaseBot
        from .bot_th import BotContext, HomeVillageBot, StopWithMessage
        ctx = BotContext(self.game, self.cfg["TH"], self.cfg["BH"], self.settings,
                         apply_profile=self.apply_profile, popup=self.on_message, raid_store=self.raid_store)
        try:
            (HomeVillageBot(ctx) if mode == "TH" else BuilderBaseBot(ctx)).run(auto)
        except BotStopped:
            log("⏹️ Bot arrêté")
        except StopWithMessage as exc:
            log(f"🛑 {exc.title} : {exc.message}")
            self.on_message(exc.title, exc.message)
        except Exception as exc:
            log(f"❌ Erreur inattendue : {exc}\n{traceback.format_exc()}")
            jpeg = self.screenshot_jpeg()
            notify.save_error_shot(str(exc), jpeg)
            notify.send_alert(f"erreur inattendue : {exc}", "exception", jpeg)
        finally:
            self.settings.set("raids_state", self.raid_store)
            uptime = self.state.uptime()
            self.state.uptime_before = uptime
            self.state.started_at = 0.0
            self.state.stop_event.set()
            self.state.running_mode = None
            self.state.set_status("stopped")
            self.save_session_stats()

    def stop(self) -> None:
        if self.state.thread and self.state.thread.is_alive():
            self.state.request_stop()
            log("⏹️ Arrêt demandé (le bot finit son action en cours)")

    def toggle(self) -> str | None:
        if self.state.running:
            self.stop()
            return None
        return self.start()

    # ---------------------------------------------------------------- captures
    def screenshot_jpeg(self) -> bytes | None:
        if self.game is None:
            return None
        screen = self.game.grab_now()
        return vision.to_jpeg(screen) if screen is not None else None

    # ---------------------------------------------------------------- stats de session
    def save_session_stats(self) -> None:
        data = {"saved_at": time.time(), "uptime": self.state.uptime(), "stats": self.state.stats}
        try:
            write_json_safely(self._stats_path, data)
        except OSError as exc:
            log(f"⚠️ Stats de session non sauvegardées : {exc}")

    def previous_session(self) -> dict | None:
        data = read_json_safely(self._stats_path, None)
        if not data or not any(any(v for v in s.values()) for s in data.get("stats", {}).values()):
            return None
        return data

    def restore_session(self, data: dict) -> None:
        for mode, values in data.get("stats", {}).items():
            if mode in self.state.stats:
                self.state.stats[mode].update({k: int(v) for k, v in values.items()})
        self.state.uptime_before = float(data.get("uptime", 0))
        self.state.changed()
        log("♻️ Stats de la session précédente remises")

    def start_autosave(self) -> None:
        def loop():
            while True:
                time.sleep(30)
                if self.state.running:
                    self.save_session_stats()
        threading.Thread(target=loop, daemon=True, name="autosave").start()

    # ---------------------------------------------------------------- état (tableau de bord, Discord)
    def status(self) -> dict:
        st = self.state
        mode = st.running_mode or st.mode
        return {
            "instance": paths.INSTANCE, "mode": mode, "state": st.status if st.running else "stopped",
            "until": st.status_until, "uptime": st.uptime(), "account": st.current_account,
            "profile": self.active_profile(mode), "stats": st.stats[mode], "battles": st.battles,
            "time": time.time(),
        }
