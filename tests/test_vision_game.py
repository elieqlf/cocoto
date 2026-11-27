"""Vision et façade Game sur un faux jeu : des templates réels collés sur un fond synthétique."""
import os
import threading
import time

import cv2
import numpy as np
import pytest

from cocoto import ocr, paths, vision
from cocoto.backends import Backend
from cocoto.features import search
from cocoto.features.clan_games import challenge_ok, is_th_challenge
from cocoto.game import Game
from cocoto.state import BotState, BotStopped

HAS_ASSETS = os.path.isdir(paths.img_dir())
needs_assets = pytest.mark.skipif(not HAS_ASSETS, reason="assets/img absent (tools/extract_assets.py)")


def background():
    rng = np.random.default_rng(1)
    img = rng.integers(40, 90, (1080, 1920, 3), dtype=np.uint8)
    return cv2.GaussianBlur(img, (9, 9), 0)


def paste(screen, tpl, x, y):
    h, w = tpl.shape[:2]
    screen[y:y + h, x:x + w] = tpl
    return (x + w // 2, y + h // 2)


class FakeBackend(Backend):
    name = "fake"

    def __init__(self, frames):
        self.frames = list(frames)
        self.clicks = []

    def grab(self):
        return self.frames[0] if len(self.frames) == 1 else self.frames.pop(0)

    def move(self, x, y, duration=0.0):
        pass

    def mouse_down(self, x, y):
        pass

    def mouse_up(self, x, y):
        self.clicks.append((x, y))

    def scroll(self, clicks, x, y):
        pass

    def key(self, name):
        pass


def test_match_image_synthetic():
    screen = background()
    tpl = np.zeros((40, 60, 3), np.uint8)
    cv2.rectangle(tpl, (5, 5), (55, 35), (0, 200, 255), -1)
    cv2.putText(tpl, "OK", (14, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    cx, cy = paste(screen, tpl, 700, 300)
    m = vision.match_image(screen, tpl)
    assert m.score > 0.99 and (m.x, m.y) == (cx, cy)
    assert vision.match_image(screen, tpl, box=(0, 0, 400, 200)).score < 0.6
    paste(screen, tpl, 1200, 800)
    assert len(vision.match_all(screen, tpl, 0.95)) == 2


@needs_assets
def test_real_templates_and_click_launch_button():
    t = vision.Templates()
    screen = background()
    fm = t.get("find_match")
    assert fm is not None and t.get("end") is not None and t.exists("donate/t00")
    cx, cy = paste(screen, fm, 400, 700)
    backend = FakeBackend([screen])
    game = Game(backend, BotState(), t)
    assert game.find("find_match").score > 0.99
    assert search.click_launch_button(game, "find_match", "Find a Match", timeout=2)
    (x, y), = backend.clicks
    h, w = fm.shape[:2]
    assert abs(x - cx) <= w // 2 and abs(y - cy) <= h // 2


@needs_assets
def test_wait_stable_needs_two_identical_positions():
    t = vision.Templates()
    a, b = background(), background()
    tpl = t.get("army_attack")
    paste(a, tpl, 800, 500)        # le bouton glisse encore…
    paste(b, tpl, 1500, 900)       # …puis s'arrête
    game = Game(FakeBackend([a, b, b]), BotState(), t)
    m = game.wait("army_attack", timeout=3, stable=True, interval=0.01)
    assert m is not None and m.x > 1500


def test_state_stop_interrupts_sleep():
    st = BotState()
    st.thread = threading.current_thread()
    threading.Timer(0.2, st.request_stop).start()
    t0 = time.monotonic()
    with pytest.raises(BotStopped):
        st.sleep(5)
    assert time.monotonic() - t0 < 1.5


def test_prepare_digits_counts_components():
    img = np.full((40, 200, 3), (40, 30, 20), np.uint8)
    cv2.putText(img, "12345", (8, 32), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
    out, n = ocr.prepare_digits(img)
    assert n == 5 and out.ndim == 2 and out.shape[1] > img.shape[1]


def test_colors():
    img = np.zeros((100, 100, 3), np.uint8)
    img[:, :50] = (0, 200, 255)      # jaune/orange en BGR
    assert 0.4 < vision.yellow_ratio(img, (0, 0, 100, 100)) < 0.6
    img[:, 50:] = (0, 0, 230)        # rouge
    assert vision.red_ratio(img, (50, 0, 100, 100)) > 0.9


def test_clan_games_text_rules():
    assert challenge_ok("Win 5 Multiplayer battles")
    assert challenge_ok("Destroy 20 Mortars in Mulbiplayer battles")
    assert not challenge_ok("Destroy buildings using Archers in Multiplayer battles")
    assert not is_th_challenge("Builder Battle: win 3 battles")
