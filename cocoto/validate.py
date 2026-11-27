"""Contrôle des réglages au START : (erreurs → START refusé, avertissements → « lancer quand même ? »)."""
from __future__ import annotations

from .config import LiveConfig
from .parsing import (is_auto, parse_amount, parse_counts, parse_early_end, parse_range,
                      parse_schedule, parse_slots)


def _slots(cfg: LiveConfig, max_slots: int, exact: bool, errors: list, warnings: list) -> None:
    if is_auto(cfg.text("slots")):
        return
    try:
        slots = parse_slots(cfg.text("slots"), max_slots)
    except ValueError as exc:
        errors.append(f"Slot : {exc}")
        return
    if not slots:
        errors.append("Slot : indique « auto » ou les numéros de cartes (ex. 1 2 3).")
        return
    try:
        counts = parse_counts(cfg.text("number"))
    except ValueError as exc:
        errors.append(f"Count per Slot : {exc}")
        return
    if exact and counts and len(counts) != len(slots):
        errors.append(f"Count per Slot : {len(counts)} nombre(s) pour {len(slots)} slot(s) "
                      "(un nombre par slot, ex. 10 10 5).")
    if not counts:
        warnings.append("Count per Slot vide : 1 clic par slot.")


def _common(cfg: LiveConfig, errors: list, warnings: list, webhook: str) -> None:
    if cfg.flag("breaks_enabled"):
        for key, label in (("break_play", "Play"), ("break_pause", "Break")):
            if parse_range(cfg.text(key)) is None:
                errors.append(f"Random breaks {label} : des minutes comme 40-70.")
        if cfg.text("break_closed") and parse_range(cfg.text("break_closed")) is None:
            errors.append("Random breaks Closed : des minutes comme 30-60, ou vide.")
    if cfg.flag("schedule_enabled") and not parse_schedule(cfg.text("schedule_hours")):
        errors.append("Schedule : des plages comme 9-12 14-23 (8:30-12:15 possible).")
    if cfg.text("battle_delay") and parse_range(cfg.text("battle_delay")) is None:
        errors.append("Délai entre combats : des secondes comme 5-20, ou vide.")
    if cfg.flag("click_wall_enabled") and not parse_amount(cfg.text("wall_cost")):
        errors.append("Upgrade walls : remplis « Wall cost » (prix d'un mur, ex. 1.5m).")
    if webhook and not webhook.startswith("https://discord.com/api/webhooks/") \
            and not webhook.startswith("https://discordapp.com/api/webhooks/"):
        warnings.append("Le webhook Discord ne ressemble pas à une URL de webhook.")


def validate_th(cfg: LiveConfig, webhook: str = "") -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    _slots(cfg, 12, True, errors, warnings)
    if not is_auto(cfg.text("slots")):
        try:
            parse_slots(cfg.text("spell"), 12)
        except ValueError as exc:
            errors.append(f"Spell Slot : {exc}")
    for key in ("gold", "elixir", "dark"):
        if cfg.text(key) and parse_amount(cfg.text(key)) is None:
            errors.append(f"Loot minimum {key} : un nombre comme 400000 ou 400k.")
    try:
        parse_early_end(cfg.text("early_end"))
    except ValueError as exc:
        errors.append(f"Early end : {exc}")
    if cfg.flag("ranked") and cfg.text("ranked_max") and not cfg.text("ranked_max").isdigit():
        errors.append("Ranked « Stop at » : un nombre d'attaques, ou vide (= toutes).")
    if (parse_amount(cfg.text("gold")) or 0) == 0 and (parse_amount(cfg.text("elixir")) or 0) == 0:
        warnings.append("Aucun loot minimum : le bot attaquera la première base trouvée.")
    _common(cfg, errors, warnings, webhook)
    return errors, warnings


def validate_bh(cfg: LiveConfig, webhook: str = "") -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    _slots(cfg, 10, False, errors, warnings)
    _common(cfg, errors, warnings, webhook)
    return errors, warnings
