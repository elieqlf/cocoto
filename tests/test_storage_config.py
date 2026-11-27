import json
import os

import pytest

from cocoto import storage
from cocoto.config import LiveConfig, merged


def test_json_safe_and_backup(tmp_path):
    path = str(tmp_path / "a.json")
    storage.write_json_safely(path, {"v": 1})
    storage.write_json_safely(path, {"v": 2})
    assert storage.read_json_safely(path) == {"v": 2}
    with open(path, "w") as f:
        f.write("{broken")
    assert storage.read_json_safely(path) == {"v": 1}      # .bak relu
    assert storage.read_json_safely(str(tmp_path / "none.json"), {"d": 0}) == {"d": 0}


def test_profiles_crud(tmp_path):
    store = storage.ProfileStore("TH", str(tmp_path / "config.json"))
    store.save("Farm", {"slots": "auto"})
    store.save("War", {"slots": "1 2"})
    assert store.names() == ["Farm", "War"]
    assert store.rename("Farm", "Farm2") and not store.rename("War", "Farm2")
    assert store.load("Farm2") == {"slots": "auto"}
    assert store.delete("War") and not store.delete("War")


def test_profile_code_roundtrip_and_privacy():
    cfg = {"slots": "auto", "gold": "500k", "note": "webhook https://discord.com/api/webhooks/123",
           "heroes": {"hero1": {"enabled": True, "delay": "2+1"}}, "account": "MyPseudo"}
    code = storage.profile_to_code("TH", cfg, private=["https://discord.com/api/webhooks/123", "MyPseudo"])
    assert code.startswith("COCO-TH-")
    mode, data = storage.profile_from_code("texte avant " + code + " après")
    assert mode == "TH" and data["gold"] == "500k" and data["heroes"]["hero1"]["delay"] == "2+1"
    assert "note" not in data and "account" not in data
    with pytest.raises(ValueError):
        storage.profile_from_code("COCO-TH-abc")
    with pytest.raises(ValueError):
        storage.profile_from_code("hello")


def test_settings(tmp_path):
    s = storage.Settings(str(tmp_path / "settings.json"))
    seen = []
    s.on_change(lambda k, v: seen.append(k))
    s.set("webhook", "x")
    assert storage.Settings(str(tmp_path / "settings.json")).get("webhook") == "x"
    assert seen == ["webhook"] and s.get("language") == "fr"


def test_live_config():
    cfg = LiveConfig("TH", {"gold": "1m", "heroes": {"hero2": {"enabled": True}}})
    assert cfg.number("gold") == 1_000_000
    assert cfg.hero("hero2")["enabled"] and cfg.hero("hero2")["delay"] == "0"
    assert not cfg.flag("click_wall_enabled")
    cfg.set("click_wall_enabled", "on")
    assert cfg.flag("click_wall_enabled")
    assert merged("BH", None)["heroes"]["machine"]["enabled"] is True
