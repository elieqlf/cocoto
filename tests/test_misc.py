import os
import struct
import sys
import zlib

from cocoto import notify
from cocoto.config import LiveConfig
from cocoto.remote import apply_set
from cocoto.state import BotState
from cocoto.validate import validate_bh, validate_th

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import extract_assets  # noqa: E402


def test_validate_th():
    cfg = LiveConfig("TH", {"slots": "1 2 3", "number": "10 10", "early_end": "12x",
                            "click_wall_enabled": True, "wall_cost": ""})
    errors, _warnings = validate_th(cfg)
    joined = " ".join(errors)
    assert "Count per Slot" in joined and "Early end" in joined and "Wall cost" in joined
    ok, _ = validate_th(LiveConfig("TH", {"slots": "auto"}))
    assert ok == []
    bad, _ = validate_bh(LiveConfig("BH", {"slots": "11"}))
    assert bad


class FakeController:
    def __init__(self):
        self.state = BotState()
        self.cfg = {"TH": LiveConfig("TH"), "BH": LiveConfig("BH")}
        self.saved = []

    def active_profile(self, mode):
        return "Farm"

    def save_profile(self, mode, name):
        self.saved.append(name)


def test_remote_set():
    c = FakeController()
    assert "✅" in apply_set(c, "gold", "450k") and c.cfg["TH"].text("gold") == "450000"
    assert "✅" in apply_set(c, "walls", "on") and c.cfg["TH"].flag("click_wall_enabled")
    assert "❌" in apply_set(c, "early_end", "abc")
    assert "✅" in apply_set(c, "schedule", "9-12 14-23") and c.cfg["TH"].flag("schedule_enabled")
    assert "❌" in apply_set(c, "nope", "1")
    assert c.saved == ["Farm"] * 3


def test_stats_payload():
    p = notify.stats_payload("TH", {"gold": 1_000_000, "elixir": 5, "dark": 1, "wins": 3, "losses": 1,
                                    "stars": 7, "walls": 2}, 3600)
    fields = p["embeds"][0]["fields"]
    assert "1 000 000" in fields[2]["value"] and "Attacks: 4" in fields[3]["value"]


def _entry(name, data):
    return (name.encode("utf-16-le") + b"\0\0" + struct.pack("<Q", len(data))
            + struct.pack("<I", zlib.crc32(data) & 0xFFFFFFFF) + data)


def test_extractor_uncompressed(tmp_path):
    stream = _entry("img\\a.png", b"PNGDATA") + _entry("python313.dll", b"x" * 10) + b"\0\0"
    exe = tmp_path / "fake.exe"
    exe.write_bytes(b"MZ" + b"\0" * 100 + b"KAX" + stream)
    out = tmp_path / "out"
    assert extract_assets.main([str(exe), "--out", str(out)]) == 0
    assert (out / "img" / "a.png").read_bytes() == b"PNGDATA"
    assert not (out / "python313.dll").exists()
