import numpy as np

from cocoto import layout
from cocoto.backends.adb import FrameMap
from cocoto.features import attack
from cocoto.bot_bh import bh_edge_points
from cocoto.features.raids import raid_weekend_id


def test_edge_points_on_screen_and_inward():
    for side in layout.ATTACK_SIDES:
        pts = attack.edge_points(side)
        assert len(pts) >= 8, side
        assert all(attack.on_screen(x, y) for x, y in pts)
        nx, ny = attack.inward_normal(side)
        view = attack.SIDE_EDGES[side][0]
        mx, my = np.mean(pts, axis=0)
        cx, cy = layout.MAP_CX, layout.MAP_VIEW_CY[view]
        # la normale pointe vers le centre de la carte
        assert (cx - mx) * nx + (cy - my) * ny > 0


def test_sweep_and_spell_points():
    pts = attack.sweep_points("top_left", 12)
    assert len(pts) == 12
    assert len(attack.spell_points("bottom_right", 3)) == 3


def test_choose_side_never_twice():
    last = None
    for _ in range(30):
        s = attack.choose_side()
        assert s != last
        last = s


def test_framemap_identity():
    fm = FrameMap(1920, 1080)
    assert fm.identity_ratio and fm.to_device(100, 200) == (100, 200)
    img = np.zeros((1080, 1920, 3), np.uint8)
    assert fm.compose(img).shape == (1080, 1920, 3)
    fm2 = FrameMap(3840, 2160)
    assert fm2.to_device(960, 540) == (1920, 1080)


def test_framemap_16_10_anchors():
    fm = FrameMap(1728, 1080)
    assert not fm.identity_ratio
    assert fm.to_device(100, 100) == (100, 100)            # coin haut gauche : collé à gauche
    assert fm.to_device(1900, 1000) == (1708, 1000)        # coin bas droit : collé à droite
    assert fm.to_device(960, 540) == (864, 540)            # centre : centré
    src = np.zeros((1080, 1728, 3), np.uint8)
    src[1000:1080, 1650:1728] = 255                         # bouton en bas à droite
    out = fm.compose(src)
    assert out.shape == (1080, 1920, 3) and out[1040, 1880].max() == 255


def test_bh_points():
    for stage in (1, 2):
        for side in ("left", "right"):
            pts = bh_edge_points(stage, side, 5)
            assert pts and all(30 < x < 1890 and 80 < y < 860 for x, y in pts)


def test_raid_weekend():
    import datetime as dt
    utc = dt.timezone.utc
    assert raid_weekend_id(dt.datetime(2026, 11, 13, 8, 0, tzinfo=utc)) == "2026-11-13"    # vendredi 8 h
    assert raid_weekend_id(dt.datetime(2026, 11, 16, 6, 0, tzinfo=utc)) == "2026-11-13"    # lundi 6 h
    assert raid_weekend_id(dt.datetime(2026, 11, 16, 8, 0, tzinfo=utc)) is None           # lundi 8 h
    assert raid_weekend_id(dt.datetime(2026, 11, 13, 6, 0, tzinfo=utc)) is None           # vendredi 6 h
