"""Contrôle à distance par Discord, avec TON propre bot Discord (CoCoBot passait par son serveur).

Réglages : remote_enabled, remote_token (token du bot créé sur discord.com/developers),
remote_user_id (ton ID Discord : seul toi peux donner des ordres). Commandes (réponses privées) :
/status /start [TH|BH] /stop /screen /settings /set option valeur /profile [nom]
Nécessite `pip install discord.py`."""
from __future__ import annotations

import asyncio
import io
import threading

from .logger import log
from .parsing import fmt_number, parse_amount, parse_bool_word, parse_range, parse_schedule, early_end_token_ok

# option /set → (clé du profil, type, modes)
SET_OPTIONS = {
    "gold": ("gold", "number", "TH"), "elixir": ("elixir", "number", "TH"), "dark": ("dark", "number", "TH"),
    "early_end": ("early_end", "early", "TH"), "walls": ("click_wall_enabled", "bool", "TH BH"),
    "wall_cost": ("wall_cost", "number", "TH BH"), "collect": ("collect_enabled", "bool", "TH BH"),
    "suggested": ("suggested_upgrades", "bool", "TH"), "breaks": ("breaks_enabled", "bool", "TH BH"),
    "break_play": ("break_play", "range", "TH BH"), "break_pause": ("break_pause", "range", "TH BH"),
    "break_closed": ("break_closed", "range_off", "TH BH"), "schedule": ("schedule_hours", "schedule", "TH BH"),
    "stop_when_full": ("stop_when_full", "bool", "TH"), "ranked": ("ranked", "bool", "TH"),
    "ranked_limit": ("ranked_max", "limit", "TH"), "donations": ("donate", "bool", "TH"),
    "reinforcements": ("request_cc", "bool", "TH"), "cake": ("cake_enabled", "bool", "TH"),
    "clan_games": ("clan_games", "bool", "TH"), "treasure": ("treasure_enabled", "bool", "TH"),
}
STATE_LABELS = {"stopped": "🔴 Arrêté", "farming": "🟢 En train de farmer", "break": "⏸ Pause",
                "off_hours": "🕒 Hors des plages horaires", "full": "🏦 Réserves pleines",
                "reconnecting": "🔌 Reconnexion"}


def apply_set(controller, option: str, value: str) -> str:
    """/set option valeur : contrôle, application au profil actif et sauvegarde."""
    option = option.strip().lower()
    if option not in SET_OPTIONS:
        return "❌ Option inconnue. Tape /settings pour les voir."
    key, kind, modes = SET_OPTIONS[option]
    mode = controller.state.running_mode or controller.state.mode
    if mode not in modes.split():
        return f"❌ {option} n'existe que pour le village principal."
    v = value.strip()
    if kind == "bool":
        b = parse_bool_word(v)
        if b is None:
            return "❌ Réponds on ou off."
        new = b
    elif kind == "number":
        n = 0 if v.lower() == "off" else parse_amount(v)
        if n is None:
            return "❌ Un nombre comme 400000, 400k ou 1.5m."
        new = str(n)
    elif kind == "early":
        if v.lower() in ("off", "0", ""):
            new = ""
        elif all(early_end_token_ok(t) for t in v.replace(",", " ").split()):
            new = v
        else:
            return f"❌ « {v} » n'est pas valide (exemples : 120s 50% 60d 20f, ou off)."
    elif kind in ("range", "range_off"):
        if kind == "range_off" and v.lower() == "off":
            new = ""
        elif parse_range(v):
            new = v
        else:
            return "❌ Des minutes comme 40-70 (min-max)."
    elif kind == "schedule":
        if v.lower() == "off":
            controller.cfg[mode].set("schedule_enabled", False)
            new = controller.cfg[mode].text("schedule_hours")
        elif parse_schedule(v):
            controller.cfg[mode].set("schedule_enabled", True)
            new = v
        else:
            return "❌ Des plages comme 9-12 14-23."
    elif kind == "limit":
        new = "" if v.lower() in ("off", "all") else (v if v.isdigit() else None)
        if new is None:
            return "❌ Un nombre d'attaques comme 10 (off = toutes)."
    else:
        return "❌ Option inconnue."
    controller.cfg[mode].set(key, new)
    name = controller.active_profile(mode)
    if name:
        controller.save_profile(mode, name)
        where = f"enregistré dans le profil **{name}**"
    else:
        where = "pas de profil actif : appliqué jusqu'à la fermeture"
    return f"✅ **{option}** : {new} ({where}). Le bot l'utilise dès sa prochaine action."


def status_text(controller) -> str:
    s = controller.status()
    st = s["stats"]
    h, rem = divmod(int(s["uptime"]), 3600)
    return (f"**⚡ COCOTO — {s['mode']}** · {STATE_LABELS.get(s['state'], s['state'])}\n"
            f"Compte : {s['account'] or '—'} · profil : {s['profile'] or '—'} · uptime {h:02d}:{rem // 60:02d}\n"
            f"🟡 {fmt_number(st['gold'])}  🟣 {fmt_number(st['elixir'])}  ⚫ {fmt_number(st['dark'])}\n"
            f"🗡 {st['attacks']}  🏆 {st['wins']}  💀 {st['losses']}  ⭐ {st['stars']}  🧱 {st['walls']}")


def settings_text(controller) -> str:
    mode = controller.state.running_mode or controller.state.mode
    cfg = controller.cfg[mode]
    lines = [f"**⚙️ Réglages {mode}** · profil **{controller.active_profile(mode) or '(aucun)'}**"]
    for opt, (key, _kind, modes) in SET_OPTIONS.items():
        if mode in modes.split():
            lines.append(f"`{opt:<15}` {cfg.get(key)}")
    lines.append("Modifie avec `/set option valeur`.")
    return "\n".join(lines)


def start_remote(controller, run_in_ui) -> bool:
    s = controller.settings
    if not s.get("remote_enabled") or not s.get("remote_token"):
        return False
    try:
        import discord  # type: ignore
        from discord import app_commands  # type: ignore
    except ImportError:
        log("📱 Contrôle à distance : installe discord.py (pip install discord.py)")
        return False
    owner = str(s.get("remote_user_id") or "")
    client = discord.Client(intents=discord.Intents.default())
    tree = app_commands.CommandTree(client)

    def allowed(inter) -> bool:
        return owner and str(inter.user.id) == owner

    async def reply(inter, text, image: bytes | None = None):
        file = discord.File(io.BytesIO(image), "cocoto.jpg") if image else discord.utils.MISSING
        await inter.response.send_message(text[:1990], ephemeral=True, file=file)

    @tree.command(name="status", description="État du bot")
    async def _status(inter):
        if not allowed(inter):
            return await reply(inter, "⛔")
        await reply(inter, status_text(controller))

    @tree.command(name="start", description="Lance le bot (TH ou BH)")
    async def _start(inter, mode: str = ""):
        if not allowed(inter):
            return await reply(inter, "⛔")
        m = mode.upper() if mode.upper() in ("TH", "BH") else None
        err = await asyncio.get_running_loop().run_in_executor(None, lambda: run_in_ui(lambda: controller.start(m)))
        await reply(inter, f"❌ {err}" if err else "▶️ Bot lancé.")

    @tree.command(name="stop", description="Arrête le bot")
    async def _stop(inter):
        if not allowed(inter):
            return await reply(inter, "⛔")
        controller.stop()
        await reply(inter, "⏹️ Bot arrêté (il finit son action en cours).")

    @tree.command(name="screen", description="Capture du jeu")
    async def _screen(inter):
        if not allowed(inter):
            return await reply(inter, "⛔")
        jpeg = controller.screenshot_jpeg()
        await reply(inter, "📸" if jpeg else "❌ Jeu introuvable.", jpeg)

    @tree.command(name="settings", description="Réglages du profil actif")
    async def _settings(inter):
        if not allowed(inter):
            return await reply(inter, "⛔")
        await reply(inter, settings_text(controller))

    @tree.command(name="set", description="Change un réglage : /set option valeur")
    async def _set(inter, option: str, value: str):
        if not allowed(inter):
            return await reply(inter, "⛔")
        await reply(inter, run_in_ui(lambda: apply_set(controller, option, value)) or "❌")

    @tree.command(name="profile", description="Liste ou charge un profil")
    async def _profile(inter, name: str = ""):
        if not allowed(inter):
            return await reply(inter, "⛔")
        mode = controller.state.running_mode or controller.state.mode
        if not name:
            names = controller.profiles[mode].names()
            return await reply(inter, "Profils : " + (", ".join(names) or "aucun"))
        was_running = controller.state.running
        controller.stop()
        for _ in range(60):
            if not (controller.state.thread and controller.state.thread.is_alive()):
                break
            await asyncio.sleep(0.5)
        ok = run_in_ui(lambda: controller.apply_profile(mode, name))
        if ok and was_running:
            run_in_ui(lambda: controller.start(mode))
        await reply(inter, f"✅ Profil **{name}** chargé." if ok else f"❌ Profil « {name} » introuvable.")

    @client.event
    async def on_ready():
        await tree.sync()
        log(f"📱 Contrôle à distance prêt : {client.user}")

    def run():
        try:
            client.run(s.get("remote_token"), log_handler=None)
        except Exception as exc:
            log(f"⚠️ Contrôle à distance : {exc}")

    threading.Thread(target=run, daemon=True, name="remote").start()
    return True
