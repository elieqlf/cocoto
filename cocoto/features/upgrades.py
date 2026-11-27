"""Améliorations des bâtiments (onglet Upgrade), suggestions du jeu et laboratoire.

Comme pour les murs, au village principal le bot ne paie qu'avec le loot qu'il a farmé ; à la base
des ouvriers avec les réserves de la BH. Après un combat (avant les murs) : panneau Build, filtre
« Type » sur la catégorie, lignes lues par OCR, premier bâtiment coché améliorable et payable →
ligne → Upgrade → Confirm vert. Quantité décomptée à chaque amélioration ; aucun ouvrier libre →
attente de quelques combats."""
from __future__ import annotations

import re

from .. import layout, ocr
from ..config import LiveConfig
from ..game import Game
from ..logger import log
from ..parsing import parse_amount
from .panel import BuildPanel, match_name

TH_BUILDINGS = {
    "Defense": ["Cannon", "Archer Tower", "Mortar", "Air Defense", "Wizard Tower", "Air Sweeper",
                "Hidden Tesla", "Bomb Tower", "X-Bow", "Inferno Tower", "Eagle Artillery",
                "Scattershot", "Builder's Hut", "Spell Tower", "Monolith", "Multi-Archer Tower",
                "Ricochet Cannon", "Firespitter", "Multi-Gear Tower", "Town Hall"],
    "Resource": ["Gold Mine", "Elixir Collector", "Dark Elixir Drill", "Gold Storage",
                 "Elixir Storage", "Dark Elixir Storage", "Clan Castle"],
    "Army": ["Army Camp", "Barracks", "Dark Barracks", "Laboratory", "Spell Factory",
             "Dark Spell Factory", "Workshop", "Pet House", "Blacksmith", "Hero Hall"],
    "Hero": ["Barbarian King", "Archer Queen", "Grand Warden", "Royal Champion", "Minion Prince",
             "Dragon Duke"],
}
BH_BUILDINGS = {
    "Defense": ["Cannon", "Double Cannon", "Archer Tower", "Hidden Tesla", "Firecrackers", "Crusher",
                "Guard Post", "Air Bombs", "Multi Mortar", "Roaster", "Giant Cannon", "Mega Tesla",
                "Lava Launcher", "X-Bow", "Builder Hall"],
    "Resource": ["Gold Mine", "Elixir Collector", "Gold Storage", "Elixir Storage", "Gem Mine",
                 "Clock Tower", "O.T.T.O's Outpost"],
    "Army": ["Builder Barracks", "Army Camp", "Star Laboratory", "Reinforcement Camp", "Healing Hut"],
    "Hero": ["Battle Machine", "Battle Copter"],
}
TH_LAB = {"Lab": ["Barbarian", "Archer", "Giant", "Goblin", "Wall Breaker", "Balloon", "Wizard",
                  "Healer", "Dragon", "P.E.K.K.A", "Baby Dragon", "Miner", "Electro Dragon", "Yeti",
                  "Dragon Rider", "Electro Titan", "Root Rider", "Thrower", "Minion", "Hog Rider",
                  "Valkyrie", "Golem", "Witch", "Lava Hound", "Bowler", "Ice Golem", "Headhunter",
                  "Apprentice Warden", "Druid", "Furnace", "Lightning Spell", "Healing Spell",
                  "Rage Spell", "Jump Spell", "Freeze Spell", "Clone Spell", "Invisibility Spell",
                  "Recall Spell", "Revive Spell", "Poison Spell", "Earthquake Spell", "Haste Spell",
                  "Skeleton Spell", "Bat Spell", "Overgrowth Spell", "Wall Wrecker",
                  "Battle Blimp", "Stone Slammer", "Siege Barracks", "Log Launcher", "Flame Flinger",
                  "Battle Drill"]}
BH_LAB_TROOPS = ["Raged Barbarian", "Sneaky Archer", "Boxer Giant", "Beta Minion", "Bomber",
                 "Baby Dragon", "Cannon Cart", "Night Witch", "Drop Ship", "Power P.E.K.K.A",
                 "Hog Glider", "Electrofire Wizard"]
HERO_NAMES_ALL = TH_BUILDINGS["Hero"] + BH_BUILDINGS["Hero"]


def pending(cfg: LiveConfig, key: str = "upgrades") -> dict[str, list[str]]:
    """{catégorie: [noms]} des lignes cochées avec une quantité > 0."""
    out: dict[str, list[str]] = {}
    for k, v in (cfg.get(key) or {}).items():
        if not isinstance(v, dict) or not v.get("enabled"):
            continue
        if (parse_amount(str(v.get("count", "1"))) or 0) <= 0:
            continue
        cat, _, name = k.partition("|")
        out.setdefault(cat, []).append(name)
    return out


def decrement(cfg: LiveConfig, key: str, item: str) -> None:
    data = cfg.get(key) or {}
    row = data.get(item, {})
    n = (parse_amount(str(row.get("count", "1"))) or 1) - 1
    row["count"] = str(max(0, n))
    if n <= 0:
        row["enabled"] = False
    data[item] = row
    cfg.set(key, data)


def set_filter(game: Game, category: str | None) -> None:
    """Filtre « Type » de la liste (boutons radio : en activer un désactive l'autre)."""
    game.click(*layout.UPGRADE_FILTER_BUTTON)
    if not game.wait("upgrade_filters", 3):
        return
    if category in layout.UPGRADE_FILTERS:
        game.click_box(layout.UPGRADE_FILTERS[category])
    game.sleep(0.3)
    game.close_window()


class Upgrader:
    def __init__(self, game: Game, cfg: LiveConfig, mode: str = "TH"):
        self.game, self.cfg, self.mode = game, cfg, mode
        self.buildings = TH_BUILDINGS if mode == "TH" else BH_BUILDINGS
        box = layout.FREE_BUILDERS_BOX if mode == "TH" else layout.BH_FREE_BUILDERS_BOX
        self.panel = BuildPanel(game, box)
        self.wait_battles = 0
        self.prices: dict[str, tuple[int, str]] = {}

    # ---------------------------------------------------------------- décision
    def keep_free(self) -> int:
        if self.mode == "TH" and (self.cfg.flag("keep_builder_walls") or self.cfg.flag("suggested_upgrades")):
            return 1
        return 0

    def due(self, budget: dict) -> bool:
        if self.wait_battles > 0:
            self.wait_battles -= 1
            return False
        for cat, names in pending(self.cfg).items():
            for name in names:
                known = self.user_price(cat, name) or self.prices.get(f"{cat}|{name}")
                if not known or budget.get(known[1], 0) >= known[0]:
                    return True
        return False

    def user_price(self, cat: str, name: str) -> tuple[int, str] | None:
        row = (self.cfg.get("upgrades") or {}).get(f"{cat}|{name}", {})
        price = parse_amount(str(row.get("price", "")))
        return (price, row.get("resource") or "gold") if price else None

    # ---------------------------------------------------------------- action
    def run(self, budget: dict) -> int:
        """Lance les améliorations cochées tant qu'un ouvrier est libre. Retourne le nombre lancé."""
        todo = pending(self.cfg)
        if not todo or not self.panel.open():
            return 0
        started = 0
        try:
            free = self.panel.free_builders()
            if free is not None and free <= self.keep_free():
                log(f"🏗️ Aucun ouvrier libre ({free}) → nouvel essai dans 3 combats")
                self.wait_battles = 3
                return 0
            for cat, names in todo.items():
                self.game.state.check()
                set_filter(self.game, cat)
                started += self._scan(cat, names, budget)
                if self.wait_battles:
                    break
            set_filter(self.game, None)
        finally:
            self.panel.close()
        return started

    def _scan(self, cat: str, names: list[str], budget: dict, pages: int = 8) -> int:
        started = 0
        skipped: set[str] = set()
        self.panel.to_top()
        for _ in range(pages):
            screen = self.game.wait_still(layout.WALL_LIST_BOX)
            for y, text in self.panel.rows(screen):
                name = match_name(text, [n for n in names if n not in skipped])
                if not name or self.panel.in_progress(screen, y):
                    continue
                price = self.panel.read_cost(screen, y)
                res = self.panel.cost_resource(screen, y)
                if price is None or res is None:
                    continue
                self.prices[f"{cat}|{name}"] = (price, res)
                if self.panel.cost_is_red(screen, y) or budget.get(res, 0) < price:
                    log(f"🏗️ {name} : {price:,} {res} pas encore payable".replace(",", " "))
                    skipped.add(name)
                    continue
                if self.upgrade_row(y):
                    budget[res] = max(0, budget.get(res, 0) - price)
                    decrement(self.cfg, "upgrades", f"{cat}|{name}")
                    log(f"🏗️ Amélioration lancée : {name} ({price:,} {res})".replace(",", " "))
                    started += 1
                    free = self.panel.free_builders()
                    if free is not None and free <= self.keep_free():
                        self.wait_battles = 3
                        return started
                    if not self.panel.open():
                        return started
                    set_filter(self.game, cat)
                    return started + self._scan(cat, names, budget, pages)
                skipped.add(name)
            self.panel.scroll(-1, 3)
        return started

    def upgrade_row(self, row_y: int) -> bool:
        """Clique la ligne puis Upgrade puis le Confirm vert. True si l'amélioration est lancée."""
        self.panel.click_row(row_y)
        up = self.panel.find_button("up")
        if not up:
            return False
        self.game.click_match(up)
        m = self.game.wait("upgrade_confirm", 4, stable=True)
        if not m:
            self.game.close_window()
            return False
        self.game.click_match(m)
        self.game.sleep(0.6)
        if self.game.find("need_more") or self.game.find("bh_builders_busy"):
            x = self.game.find("close_x")
            if x:
                self.game.click_match(x)
            return False
        return True

    # ---------------------------------------------------------------- suggestions du jeu
    def suggested(self, storages: dict) -> int:
        """Améliore les bâtiments suggérés en haut du menu Build tant qu'il reste plus d'un ouvrier
        libre (1 gardé pour les murs). Héros seulement si « Include heroes »."""
        if not self.panel.open():
            return 0
        started = 0
        try:
            set_filter(self.game, None)
            self.panel.to_top()
            for _ in range(4):
                free = self.panel.free_builders()
                if free is not None and free <= 1:
                    break
                screen = self.game.grab()
                rows = self.panel.rows(screen)
                title = next((y for y, t in rows if "suggest" in t.lower()), None)
                if title is None:
                    break
                picked = None
                for y, text in rows:
                    if y <= title or y > title + 260:
                        continue
                    if match_name(text, HERO_NAMES_ALL, 0.7) and not self.cfg.flag("suggested_heroes"):
                        continue
                    price, res = self.panel.read_cost(screen, y), self.panel.cost_resource(screen, y)
                    if price and res and not self.panel.cost_is_red(screen, y) and storages.get(res, 0) >= price:
                        picked = (y, text, price, res)
                        break
                if not picked or not self.upgrade_row(picked[0]):
                    break
                storages[picked[3]] -= picked[2]
                started += 1
                log(f"💡 Suggestion lancée : {picked[1]} ({picked[2]:,})".replace(",", " "))
                if not self.panel.open():
                    break
        finally:
            self.panel.close()
        return started

    # ---------------------------------------------------------------- laboratoire (TH)
    def lab(self, budget: dict) -> bool:
        todo = pending(self.cfg, "lab").get("Lab", [])
        if not todo or not self.panel.open():
            return False
        try:
            self.game.click(*layout.PANEL_TABS["lab"])
            self.game.sleep(0.6)
            text = ocr.read_box_text(self.game.grab(), layout.LAB_FREE_BOX, allowlist="0123456789/")
            m = re.search(r"(\d)\s*/\s*(\d)", text)
            if m and int(m.group(1)) == 0:
                log("🧪 Laboratoire occupé")
                return False
            for _ in range(8):
                screen = self.game.wait_still(layout.WALL_LIST_BOX)
                for y, row in self.panel.rows(screen):
                    name = match_name(row, todo)
                    if not name:
                        continue
                    price, res = self.panel.read_cost(screen, y), self.panel.cost_resource(screen, y)
                    if not price or not res or budget.get(res, 0) < price:
                        continue
                    if self.upgrade_row(y):
                        budget[res] -= price
                        decrement(self.cfg, "lab", f"Lab|{name}")
                        log(f"🧪 Recherche lancée : {name}")
                        return True
                self.panel.scroll(-1, 3)
        finally:
            self.game.click(*layout.PANEL_TABS["builders"])
            self.panel.close()
        return False
