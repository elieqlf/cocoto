import pytest

from cocoto import parsing as p


@pytest.mark.parametrize("text,value", [
    ("400000", 400000), ("400k", 400000), ("1.5m", 1500000), ("1,5M", 1500000),
    ("1 500 000", 1500000), ("1.500.000", 1500000), ("", None), ("abc", None), ("2b", 2000000000),
])
def test_parse_amount(text, value):
    assert p.parse_amount(text) == value


def test_ranges():
    assert p.parse_range("40-70") == (40, 70)
    assert p.parse_range("70-40") == (40, 70)
    assert p.parse_range("30") == (30, 30)
    assert p.parse_range("x", (1, 2)) == (1, 2)
    assert p.parse_range("") is None


def test_schedule():
    assert p.parse_schedule("9-12 14:30-23") == [(540, 720), (870, 1380)]
    assert p.parse_schedule("22-2") == [(1320, 1440), (0, 120)]
    assert p.parse_schedule("9h-12") is None or p.parse_schedule("9h-12") == [(540, 720)]
    assert p.parse_schedule("nope") is None
    r = p.parse_schedule("9-12 14-23")
    assert p.in_schedule(r, 10 * 60) and not p.in_schedule(r, 13 * 60)
    assert p.minutes_until_next_start(r, 13 * 60) == 60
    assert p.minutes_until_next_start(r, 23 * 60 + 30) == 30 + 9 * 60


def test_early_end():
    rule = p.parse_early_end("120s 50% 60d 20f")
    assert (rule.seconds, rule.percent, rule.damage, rule.stale) == (120, 50, 60, 20)
    assert not p.parse_early_end("off").active
    with pytest.raises(ValueError):
        p.parse_early_end("120x")
    assert p.early_end_token_ok("50%") and not p.early_end_token_ok("50")


def test_slots_and_counts():
    assert p.parse_slots("1 2, 3") == [1, 2, 3]
    with pytest.raises(ValueError):
        p.parse_slots("13")
    assert p.parse_counts("10 10 5") == [10, 10, 5]
    assert p.is_auto("Auto") and p.is_auto("") and not p.is_auto("1 2")


def test_hero_delay():
    for _ in range(50):
        d = p.pick_hero_delay("2+1")
        assert 1 <= d <= 3
    assert p.pick_hero_delay("5") == 5
    assert p.pick_hero_delay("x") == 0
    assert p.pick_hero_delay("0+3") >= 0


def test_names():
    assert p.player_name_score("brandon 2.0", "Brandon 20") == 1.0
    assert p.closest_name("Brandn", ["Alice", "Brandon", "brandon 2.0"]) == "Brandon"
    assert p.closest_name("zzz", ["Alice"]) is None
    assert p.parse_bool_word("oui") is True and p.parse_bool_word("off") is False


def test_format():
    assert p.fmt_number(1234567) == "1 234 567"
    assert p.short_number(1_500_000) == "1.5M"
    assert p.digits_to_int("x12a") == 12
