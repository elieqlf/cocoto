"""Journal : fichier tournant (5 Mo), mémoire pour la fenêtre Logs, abonnés (UI, Discord…)."""
from __future__ import annotations

import collections
import os
import threading
import time
from typing import Callable

from . import paths

LOG_MAX_BYTES = 5 * 1024 * 1024
_lock = threading.Lock()
_lines: collections.deque[str] = collections.deque(maxlen=3000)
_listeners: list[Callable[[str], None]] = []
last_log_time = time.monotonic()


def log_path() -> str:
    return paths.data_path("bot_log.txt")


def _rotate_if_needed(extra: int) -> None:
    p = log_path()
    try:
        if os.path.getsize(p) + extra > LOG_MAX_BYTES:
            old = os.path.splitext(p)[0] + ".old.txt"
            os.replace(p, old)
    except OSError:
        pass


def write_log(msg: str) -> None:
    global last_log_time
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    with _lock:
        _lines.append(line)
        last_log_time = time.monotonic()
        try:
            data = (line + "\n").encode("utf-8")
            _rotate_if_needed(len(data))
            with open(log_path(), "ab") as f:
                f.write(data)
        except OSError:
            pass
    for cb in list(_listeners):
        try:
            cb(line)
        except Exception:
            pass


log = write_log


def snapshot() -> list[str]:
    with _lock:
        return list(_lines)


def clear() -> None:
    with _lock:
        _lines.clear()


def subscribe(cb: Callable[[str], None]) -> None:
    _listeners.append(cb)


def seconds_since_last_log() -> float:
    return time.monotonic() - last_log_time
