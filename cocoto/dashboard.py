"""Tableau de bord multi-instances : chaque Cocoto ouvert sur le PC écrit son état dans un dossier
commun (status_<n>.json) et lit ses commandes (cmd_<n>.json : start / stop). La fenêtre Dashboard
de n'importe quelle instance affiche tout le monde et peut les piloter."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time

from . import paths
from .logger import log, snapshot

WRITE_SECONDS = 3
STALE_SECONDS = 20
FORGET_SECONDS = 86400


def folder() -> str:
    return paths.shared_dir("dashboard")


def _write(path: str, data: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def read_all() -> dict[int, dict]:
    out = {}
    now = time.time()
    for name in os.listdir(folder()):
        m = re.fullmatch(r"status_(\d+)\.json", name)
        if not m:
            continue
        try:
            with open(os.path.join(folder(), name), "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        age = now - data.get("time", 0)
        if age > FORGET_SECONDS:
            continue
        data["online"] = age < STALE_SECONDS
        out[int(m.group(1))] = data
    return dict(sorted(out.items()))


def send(n: int, cmd: str, mode: str | None = None) -> str:
    cid = f"{time.time():.3f}"
    _write(os.path.join(folder(), f"cmd_{n}.json"), {"cmd": cmd, "mode": mode, "id": cid})
    return cid


def launch_instance(n: int) -> None:
    """Lance un Cocoto pour l'instance n (émulateur n, port ADB 16384 + 32 x (n-1))."""
    cmd = [sys.executable, "-m", "cocoto"] + (["--instance", str(n)] if n > 1 else [])
    subprocess.Popen(cmd, cwd=paths.ROOT)


def start_loop(controller, run_in_ui) -> None:
    """Thread : écrit l'état de ce Cocoto et exécute les commandes reçues."""
    n = paths.INSTANCE
    status_path = os.path.join(folder(), f"status_{n}.json")
    cmd_path = os.path.join(folder(), f"cmd_{n}.json")

    def loop():
        while True:
            try:
                data = controller.status()
                lines = snapshot()
                data["last_log"] = lines[-1][11:] if lines else ""
                _write(status_path, data)
                if os.path.exists(cmd_path):
                    with open(cmd_path, "r", encoding="utf-8") as f:
                        cmd = json.load(f)
                    os.remove(cmd_path)
                    log(f"📋 Commande du tableau de bord : {cmd.get('cmd')}")
                    if cmd.get("cmd") == "start":
                        run_in_ui(lambda: controller.start(cmd.get("mode")))
                    elif cmd.get("cmd") == "stop":
                        controller.stop()
            except Exception as exc:
                log(f"⚠️ Tableau de bord : {exc}")
            time.sleep(WRITE_SECONDS)

    threading.Thread(target=loop, daemon=True, name="dashboard").start()
