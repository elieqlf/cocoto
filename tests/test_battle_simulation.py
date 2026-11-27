"""Cycle complet d'un combat du village principal sur un faux jeu qui réagit aux clics :
village → Battle → Find a Match → Attack! → scout → pose → écran de fin → Return Home → village.
L'OCR est remplacé par des valeurs fixes (EasyOCR n'est pas nécessaire au test)."""
import os

import cv2
import numpy as np
import pytest

from cocoto import layout, paths, vision
from cocoto.backends import Backend
from cocoto.bot_th import BotContext, HomeVillageBot
from cocoto.config import LiveConfig
from cocoto.features import attack, search, village
from cocoto.game import Game
from cocoto.state import BotState
from cocoto.storage import Settings

pytestmark = pytest.mark.skipif(not os.path.isdir(paths.img_dir()), reason="assets/img absent")


def inside(x, y, box, pad=0):
    x1, y1, x2, y2 = box
    return x1 - pad <= x <= x2 + pad and y1 - pad <= y <= y2 + pad


class SimGame(Backend):
    name = "sim"

    def __init__(self, tpl):
        self.tpl = tpl
        self.state = "village"
        self.log = []
        self.deploy_clicks = 0
        self.pos = {}
        rng = np.random.default_rng(3)
        self.bg = cv2.GaussianBlur(rng.integers(30, 80, (1080, 1920, 3), dtype=np.uint8), (9, 9), 0)

    def _paste(self, img, name, x, y):
        t = self.tpl.get(name)
        h, w = t.shape[:2]
        img[y:y + h, x:x + w] = t
        self.pos[name] = (x, y, x + w, y + h)

    def grab(self):
        img = self.bg.copy()
        if self.state == "village":
            x1, y1, x2, y2 = layout.BATTLE_BUTTON_BOX
            img[y1:y2, x1:x2] = (0, 210, 255)                  # bouton Battle jaune
            self._paste(img, "village_th", 50, 900)
        elif self.state == "panel":
            self._paste(img, "find_match", 155, 713)            # carte Battle (mesuré GPG)
        elif self.state == "army":
            self._paste(img, "army_attack", 1500, 950)
        elif self.state == "scout":
            self._paste(img, "end", 40, 820)
        elif self.state == "end":
            self._paste(img, "return_home", 830, 870)
        return img

    def move(self, x, y, duration=0.0):
        pass

    def mouse_down(self, x, y):
        pass

    def mouse_up(self, x, y):
        self.click_at(x, y)

    def drag(self, x1, y1, x2, y2, duration=0.4, hold_end=0.15):
        self.log.append(("drag", self.state))

    def scroll(self, clicks, x, y):
        self.log.append(("scroll", self.state))

    def key(self, name):
        pass

    def click_at(self, x, y):
        self.log.append(("click", self.state, x, y))
        s = self.state
        if s == "village" and inside(x, y, layout.BATTLE_BUTTON):
            self.state = "panel"
        elif s == "panel" and inside(x, y, self.pos["find_match"]):
            self.state = "army"
        elif s == "army" and inside(x, y, self.pos["army_attack"]):
            self.state = "scout"
        elif s == "scout" and y < layout.ARMY_BAR_Y[0]:
            self.deploy_clicks += 1
            if self.deploy_clicks >= 6:
                self.state = "end"
        elif s == "end" and inside(x, y, layout.RETURN_HOME):
            self.state = "village"


@pytest.fixture()
def bot(monkeypatch, tmp_path):
    tpl = vision.Templates()
    sim = SimGame(tpl)
    state = BotState()
    game = Game(sim, state, tpl)
    monkeypatch.setattr(game, "sleep", lambda s: None)
    monkeypatch.setattr(state, "sleep", lambda s: state.check())
    monkeypatch.setattr(search, "scout_loot", lambda g: [600000, 550000, 2000])
    monkeypatch.setattr(attack, "read_army_stable", lambda g, tries=3: [
        attack.Card(400, 340, 460, 5), attack.Card(520, 460, 580, None, hero="hero1")])
    monkeypatch.setattr(attack, "card_alive", lambda screen, x: False)
    monkeypatch.setattr(attack, "count_stars", lambda screen, boxes=None, ratio=None: 2)
    monkeypatch.setattr(attack, "read_end_loot", lambda screen, ranked=False: [300000, 250000, 900])
    monkeypatch.setattr(attack, "read_league_bonus", lambda g, timeout=4.0: [10000, 10000, 50])
    monkeypatch.setattr(village, "game_in_english", lambda g, s: True)
    cfg_th = LiveConfig("TH", {"slots": "auto", "gold": "500k", "elixir": "500k", "dark": "0",
                               "collect_enabled": False,
                               "heroes": {"hero1": {"enabled": True, "delay": "0"}}})
    ctx = BotContext(game, cfg_th, LiveConfig("BH"), Settings(str(tmp_path / "s.json")))
    return HomeVillageBot(ctx), sim, state


def test_full_battle_cycle(bot):
    hv, sim, state = bot
    village.check_village(hv.g, "TH")
    hv.battle()
    hv.after_battle()
    states = [e[1] for e in sim.log if e[0] == "click"]
    # ordre des écrans traversés
    order = [s for i, s in enumerate(states) if i == 0 or s != states[i - 1]]
    assert order[:5] == ["village", "panel", "army", "scout", "end"]
    assert sim.state == "village"
    assert ("scroll", "scout") in sim.log and ("drag", "scout") in sim.log     # dézoom + calage de la vue
    st = state.stats["TH"]
    assert st["wins"] == 1 and st["stars"] == 2 and st["attacks"] == 1
    assert st["gold"] == 310000 and st["elixir"] == 260000 and st["dark"] == 950
    assert state.accum["gold"] == 310000


def test_next_until_loot_is_enough(bot, monkeypatch):
    hv, sim, state = bot
    loots = iter([[100, 100, 0], [200000, 900000, 0], [700000, 700000, 0]])
    monkeypatch.setattr(search, "scout_loot", lambda g: next(loots))
    sim.state = "scout"
    loot = search.find_target(hv.g, hv.cfg)
    assert loot == [700000, 700000, 0]
    nexts = [e for e in sim.log if e[0] == "click" and inside(e[2], e[3], layout.NEXT_BUTTON)]
    assert len(nexts) == 2
