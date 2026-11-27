"""Notifications : webhook Discord (stats en embed, alertes avec capture et mention, infos),
notification Windows, captures d'erreur pour le support, zip de support, chien de garde."""
from __future__ import annotations

import base64
import datetime as dt
import glob
import io
import json
import os
import platform
import subprocess
import threading
import time
import zipfile

from . import paths
from .logger import log, seconds_since_last_log, snapshot
from .parsing import fmt_number

ALERT_COOLDOWN = 600
FREEZE_ALERT_SECONDS = 15 * 60
ERROR_SHOTS_MAX = 30
ERROR_SHOTS_MAX_AGE = 2 * 86400
_last_alerts: dict[str, float] = {}
_settings = None


def bind_settings(settings) -> None:
    global _settings
    _settings = settings


def _setting(key: str, default=""):
    return _settings.get(key, default) if _settings else default


def _post(url: str, payload: dict, files: dict | None = None, timeout: float = 10) -> None:
    import requests
    try:
        if files:
            r = requests.post(url, data={"payload_json": json.dumps(payload)}, files=files, timeout=timeout)
        else:
            r = requests.post(url, json=payload, timeout=timeout)
        if r.status_code >= 300:
            log(f"❌ Discord a refusé le message ({r.status_code}) : {r.text[:200]}")
    except Exception as exc:
        log(f"❌ Envoi Discord impossible : {exc}")


def _bg(fn, *args) -> None:
    threading.Thread(target=fn, args=args, daemon=True).start()


# ---------------------------------------------------------------- Discord
def send_info(text: str) -> None:
    url = _setting("webhook")
    if url:
        _bg(_post, url, {"username": "Cocoto", "content": text})


def send_alert(reason: str, key: str, screen_jpeg: bytes | None = None) -> None:
    """Message séparé de l'embed des stats, qui mentionne l'utilisateur (une mention dans un embed
    ne notifie pas). Au plus une alerte par raison toutes les 10 min."""
    now = time.monotonic()
    if now - _last_alerts.get(key, -1e9) < ALERT_COOLDOWN:
        return
    _last_alerts[key] = now
    if _setting("desktop_notify", False):
        windows_toast("Cocoto a besoin de toi", reason)
    url = _setting("webhook")
    if not url:
        return
    uid = "".join(ch for ch in str(_setting("discord_id")) if ch.isdigit())
    mention = f"<@{uid}> " if uid else ""
    payload = {"username": "Cocoto", "content": f"{mention}🚨 **Cocoto** — {reason}",
               "allowed_mentions": {"users": [uid] if uid else []}}
    files = {"files[0]": ("screen.jpg", screen_jpeg, "image/jpeg")} if screen_jpeg else None
    log(f"🚨 Alerte : {reason}")
    _bg(_post, url, payload, files)


def per_hour(total: int, seconds: float) -> str:
    if seconds < 60:
        return "—"
    return fmt_number(total * 3600 / seconds)


def stats_payload(mode: str, stats: dict, seconds: float) -> dict:
    label = "🏰 Home Village" if mode == "TH" else "🔨 Builder Base"
    loot = [("🟡", "Gold", stats.get("gold", 0)), ("🟣", "Elixir", stats.get("elixir", 0))]
    if mode == "TH":
        loot.append(("⚫", "Dark", stats.get("dark", 0)))
    h, rem = divmod(int(seconds), 3600)
    lines = "\n".join(f"{e} {n}: {fmt_number(t)}  (+{per_hour(t, seconds)}/h)" for e, n, t in loot)
    attacks = stats.get("wins", 0) + stats.get("losses", 0)
    return {
        "username": f"Cocoto • {label}",
        "embeds": [{
            "title": f"⚡ COCOTO Live Stats — {label}",
            "color": 0xF5B83D,
            "fields": [
                {"name": "⏳ UPTIME", "value": f"```{h:02d}:{rem // 60:02d}```", "inline": True},
                {"name": "🧱 WALLS", "value": f"```{stats.get('walls', 0)}```", "inline": True},
                {"name": "📦 TOTAL LOOTED", "value": f"```{lines}```", "inline": False},
                {"name": "🛡 BATTLES", "value": (
                    f"```🗡 Attacks: {attacks}  ({per_hour(attacks, seconds)}/h)\n🏆 Wins: {stats.get('wins', 0)}"
                    f"\n💀 Losses: {stats.get('losses', 0)}\n⭐ Stars: {stats.get('stars', 0)}```"), "inline": False},
            ],
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        }],
    }


_last_stats = 0.0


def send_stats(mode: str, stats: dict, seconds: float, cooldown: float = 360) -> None:
    global _last_stats
    url = _setting("webhook")
    if not url or time.monotonic() - _last_stats < cooldown:
        return
    _last_stats = time.monotonic()
    _bg(_post, url, stats_payload(mode, stats, seconds))


# ---------------------------------------------------------------- Windows
def windows_toast(title: str, message: str) -> None:
    if os.name != "nt":
        return
    from xml.sax.saxutils import escape
    xml = (f"<toast><visual><binding template='ToastGeneric'><text>{escape(title)}</text>"
           f"<text>{escape(message)}</text></binding></visual></toast>")
    script = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null\n"
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null\n"
        "$x = New-Object Windows.Data.Xml.Dom.XmlDocument\n"
        f"$x.LoadXml('{xml.replace(chr(39), chr(39) * 2)}')\n"
        "$n = [Windows.UI.Notifications.ToastNotification]::new($x)\n"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
        "'{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe').Show($n)\n")
    encoded = base64.b64encode(script.encode("utf-16-le")).decode()

    def run():
        try:
            subprocess.run(["powershell", "-NoProfile", "-EncodedCommand", encoded], capture_output=True,
                           timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception as exc:
            log(f"⚠️ Notification Windows impossible : {exc}")

    _bg(run)


# ---------------------------------------------------------------- captures d'erreur / support
def error_shots_dir() -> str:
    d = paths.data_path("error_shots")
    os.makedirs(d, exist_ok=True)
    return d


def save_error_shot(reason: str, jpeg: bytes | None) -> None:
    if not jpeg:
        return
    slug = "".join(c if c.isascii() and c.isalnum() else "_" for c in reason)[:40]
    name = os.path.join(error_shots_dir(), f"{time.strftime('%d-%m_%H-%M-%S')}_{slug}.jpg")
    try:
        with open(name, "wb") as f:
            f.write(jpeg)
        log(f"📸 Capture d'erreur gardée : {os.path.basename(name)}")
    except OSError:
        return
    files = sorted(glob.glob(os.path.join(error_shots_dir(), "*.jpg")), key=os.path.getmtime, reverse=True)
    now = time.time()
    for i, f in enumerate(files):
        if i >= ERROR_SHOTS_MAX or now - os.path.getmtime(f) > ERROR_SHOTS_MAX_AGE:
            try:
                os.remove(f)
            except OSError:
                pass


def export_support_zip(info: dict) -> str:
    """Zip sur le bureau : journal + captures d'erreur + infos (jamais le webhook ni le token)."""
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    folder = desktop if os.path.isdir(desktop) else paths.user_dir()
    path = os.path.join(folder, f"cocoto_support_{time.strftime('%Y%m%d_%H%M%S')}.zip")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("logs.txt", "\n".join(snapshot()))
        lines = [f"Cocoto v{paths.VERSION} (instance {paths.INSTANCE})", f"OS : {platform.platform()}",
                 f"Python : {platform.python_version()}"] + [f"{k} : {v}" for k, v in info.items()]
        z.writestr("info.txt", "\n".join(lines))
        for f in glob.glob(os.path.join(error_shots_dir(), "*.jpg")):
            z.write(f, "screens/" + os.path.basename(f))
    return path


# ---------------------------------------------------------------- chien de garde
def start_freeze_watchdog(state, get_jpeg) -> None:
    """Alerte si le bot tourne mais n'écrit plus rien (jeu figé, popup inattendue…)."""

    def loop():
        alerted = False
        while True:
            time.sleep(15)
            idle = seconds_since_last_log()
            if state.running and state.status == "farming" and idle > FREEZE_ALERT_SECONDS:
                if not alerted:
                    send_alert(f"aucune activité depuis {int(idle // 60)} min, le bot semble bloqué",
                               "freeze", get_jpeg())
                    alerted = True
            else:
                alerted = False

    threading.Thread(target=loop, daemon=True, name="watchdog").start()
