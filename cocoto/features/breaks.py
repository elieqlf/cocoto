"""Pauses « comme un vrai joueur », plages horaires, délai entre deux combats, jeu fermé (Closed).

- Random breaks : Play (ex. 40-70 min de farm) puis Break (ex. 10-25 min au village) ;
- Closed (mode arrière-plan / ADB) : chaque pause ferme complètement le jeu pendant une durée tirée
  dans cette plage (elle remplace Break), puis le rouvre ; le jeu est aussi fermé hors des plages ;
- Schedule : le bot ne farme que dans les plages « 9-12 14:30-23 » ;
- les pauses n'ont lieu qu'entre deux combats ; une déconnexion pendant la pause est rechargée ;
- pendant une attente au village (pause, plage horaire, long délai), un clic sans effet (barre d'or)
  toutes les 100-170 s évite la popup d'inactivité (sauf jeu fermé)."""
from __future__ import annotations

import random
import time
from typing import Callable

from ..config import LiveConfig
from ..game import Game
from ..logger import log
from ..parsing import in_schedule, minutes_until_next_start, parse_range, parse_schedule, pick_in_range


def closed_range(cfg: LiveConfig, game: Game) -> tuple[float, float] | None:
    if game.backend.name not in ("window", "adb"):
        return None
    return parse_range(cfg.text("break_closed"))


def reopen_game(game: Game, attempts: int = 2) -> bool:
    for attempt in range(attempts):
        log(f"🎮 Réouverture du jeu ({attempt + 1}/{attempts})")
        try:
            game.backend.open_game()
        except Exception as exc:
            log(f"⚠️ Réouverture impossible : {exc}")
        end = time.monotonic() + 120
        while time.monotonic() < end:
            game.state.sleep(3)
            screen = game.grab_now()
            if screen is None:
                continue
            game.backend.wake()
            from .reconnect import handle_popup_if_any
            handle_popup_if_any(game, screen)
            game.dismiss_common_popups(screen)
            if game.battle_button_visible(screen):
                log("🎮 Jeu rouvert, village affiché")
                return True
        try:
            game.backend.close_game()
        except Exception:
            pass
    return False


KEEP_ALIVE_EVERY = (100, 170)   # secondes entre deux gestes pendant une attente au village


def keep_alive(game: Game) -> None:
    """Geste sans effet pour que le jeu ne coupe pas pour inactivité (« Anyone there? », ~5 min sans
    action) pendant une attente au village. Mesuré GPG 2026-11 : la molette n'est PAS comptée comme
    activité (popup à 5 min 30 malgré deux crans) ; un clic l'est. Le clic tombe sur la barre d'or en
    haut à droite : il n'affiche qu'une info-bulle (capacité, production) qui disparaît seule."""
    from .. import humanize, layout
    x, y = humanize.point_in_box(layout.KEEP_ALIVE_TAP)
    try:
        game.click(x, y, jitter=0)
    except Exception as exc:
        if exc.__class__.__name__ == "BotStopped":
            raise
        log(f"⚠️ Maintien de connexion : {exc}")


def rest(game: Game, until: Callable[[], bool], status: str, label: str, closed: bool = False,
         notify: Callable[[str], None] | None = None) -> bool:
    """Attend au village jusqu'à until() ; closed = jeu fermé pendant l'attente puis rouvert.
    False si le bot a été arrêté ou n'a pas pu reprendre."""
    game.state.set_status(status)
    if notify:
        notify(label)
    log(label)
    if closed:
        try:
            game.backend.close_game()
            log("🎮 Jeu fermé pendant la pause")
        except Exception as exc:
            log(f"⚠️ Fermeture du jeu impossible : {exc}")
            closed = False
    last = 0.0
    next_alive = time.monotonic() + random.uniform(*KEEP_ALIVE_EVERY)
    while not until():
        game.state.sleep(5)
        if not closed and time.monotonic() >= next_alive:
            keep_alive(game)
            next_alive = time.monotonic() + random.uniform(*KEEP_ALIVE_EVERY)
        if time.monotonic() - last > 60:
            last = time.monotonic()
            if game.state.status_until:
                left = max(0, game.state.status_until - time.time()) / 60
                log(f"⏸ Pause : encore {left:.0f} min")
    game.state.set_status("farming")
    if closed:
        return reopen_game(game)
    from .reconnect import reload_if_disconnected
    reload_if_disconnected(game)
    return game.wait_village(60)


class BreakScheduler:
    """Décide, au village entre deux combats, s'il est temps de faire une pause."""

    def __init__(self, cfg: LiveConfig):
        self.cfg = cfg
        self.next_break_at: float | None = None

    def schedule(self) -> None:
        play = parse_range(self.cfg.text("break_play"), (40, 70))
        self.next_break_at = time.time() + pick_in_range(play) * 60
        log(f"⏱️ Prochaine pause dans {(self.next_break_at - time.time()) / 60:.0f} min")

    def check(self, game: Game, notify=None) -> bool:
        if not self.cfg.flag("breaks_enabled"):
            self.next_break_at = None
            return True
        if self.next_break_at is None:
            self.schedule()
            return True
        if time.time() < self.next_break_at:
            return True
        closed = closed_range(self.cfg, game)
        rng = closed or parse_range(self.cfg.text("break_pause"), (10, 25))
        minutes = pick_in_range(rng)
        resume = time.time() + minutes * 60
        game.state.status_until = resume
        ok = rest(game, lambda: time.time() >= resume, "break",
                  f"😴 Pause de {minutes:.0f} min{' (jeu fermé)' if closed else ''}", bool(closed), notify)
        game.state.status_until = 0
        self.schedule()
        return ok


def check_schedule(game: Game, cfg: LiveConfig, notify=None) -> bool:
    """Hors des plages horaires : attend au village (ou jeu fermé) jusqu'à la prochaine."""
    if not cfg.flag("schedule_enabled"):
        return True
    ranges = parse_schedule(cfg.text("schedule_hours"))
    if not ranges:
        return True
    now = time.localtime()
    minute = now.tm_hour * 60 + now.tm_min
    if in_schedule(ranges, minute):
        return True
    wait = minutes_until_next_start(ranges, minute)
    resume = time.time() + wait * 60
    game.state.status_until = resume

    def done() -> bool:
        t = time.localtime()
        return in_schedule(ranges, t.tm_hour * 60 + t.tm_min)

    ok = rest(game, done, "off_hours", f"🕒 Hors des plages horaires : reprise dans {wait} min",
              closed_range(cfg, game) is not None, notify)
    game.state.status_until = 0
    return ok


def wait_between_battles(game: Game, cfg: LiveConfig) -> None:
    rng = parse_range(cfg.text("battle_delay"))
    if rng and rng[1] > 0:
        delay = random.uniform(*rng)
        log(f"⏳ Délai entre deux combats : {delay:.0f} s")
        end = time.monotonic() + delay
        while True:
            left = end - time.monotonic()
            if left <= 0:
                break
            step = min(left, random.uniform(*KEEP_ALIVE_EVERY))
            game.state.sleep(step)
            if end - time.monotonic() > 5:
                keep_alive(game)
