"""État partagé du bot : marche / arrêt, statistiques de la session, budget farmé."""
from __future__ import annotations

import threading
import time
from typing import Callable

STAT_FIELDS = ("gold", "elixir", "dark", "wins", "losses", "stars", "walls", "attacks",
               "capital", "raids")


class BotStopped(Exception):
    """Levée dès que l'utilisateur arrête le bot : remonte jusqu'à la boucle principale."""


class Reconnect(Exception):
    """Popup de déconnexion vue par la surveillance : la boucle recharge le jeu puis reprend."""


class BotState:
    def __init__(self):
        self._lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.mode = "TH"
        self.running_mode: str | None = None
        self.status = "stopped"          # stopped | farming | break | off_hours | full | reconnecting
        self.status_until = 0.0
        self.started_at = 0.0
        self.uptime_before = 0.0         # uptime restauré d'une session précédente
        self.stats = {"TH": dict.fromkeys(STAT_FIELDS, 0), "BH": dict.fromkeys(STAT_FIELDS, 0)}
        self.accum = {"gold": 0, "elixir": 0, "dark": 0}   # loot farmé disponible pour les murs/bâtiments
        self.battles = 0
        self.reconnecting = False
        self.reconnect_pending = False
        self.current_account = ""
        self.last_error = ""
        self._listeners: list[Callable[[], None]] = []

    # ---------------------------------------------------------------- marche / arrêt
    @property
    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive() and not self.stop_event.is_set()

    def request_stop(self) -> None:
        self.stop_event.set()

    def check(self) -> None:
        if self.stop_event.is_set():
            raise BotStopped()
        if self.reconnect_pending and threading.current_thread() is self.thread:
            self.reconnect_pending = False
            raise Reconnect()

    def sleep(self, seconds: float) -> None:
        """Pause interrompue par STOP (et par une reconnexion pour le thread du bot)."""
        end = time.monotonic() + max(0.0, seconds)
        while True:
            self.check()
            left = end - time.monotonic()
            if left <= 0:
                return
            if self.stop_event.wait(min(left, 0.5)):
                raise BotStopped()

    # ---------------------------------------------------------------- stats
    def add(self, field: str, amount: int = 1, mode: str | None = None) -> None:
        with self._lock:
            m = mode or self.running_mode or self.mode
            self.stats[m][field] = self.stats[m].get(field, 0) + int(amount)
        self.changed()

    def farmed(self, gold: int = 0, elixir: int = 0, dark: int = 0) -> None:
        with self._lock:
            self.accum["gold"] += gold
            self.accum["elixir"] += elixir
            self.accum["dark"] += dark

    def spend(self, resource: str, cost: int) -> None:
        with self._lock:
            self.accum[resource] = max(0, self.accum.get(resource, 0) - cost)

    def uptime(self) -> float:
        extra = time.monotonic() - self.started_at if self.running and self.started_at else 0.0
        return self.uptime_before + extra

    def set_status(self, status: str, until: float = 0.0) -> None:
        self.status, self.status_until = status, until
        self.changed()

    def reset_stats(self) -> None:
        with self._lock:
            for m in self.stats:
                self.stats[m] = dict.fromkeys(STAT_FIELDS, 0)
            self.uptime_before = 0.0
        self.changed()

    # ---------------------------------------------------------------- abonnés (UI)
    def on_change(self, cb: Callable[[], None]) -> None:
        self._listeners.append(cb)

    def changed(self) -> None:
        for cb in list(self._listeners):
            try:
                cb()
            except Exception:
                pass
