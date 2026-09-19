import pytest

from planner.core.timeutil import fmt_minutes, hhmm_to_min, min_to_hhmm, parse_ru_datetime


@pytest.mark.parametrize(
    ("text", "minutes"),
    [("00:00", 0), ("0:01", 1), ("09:05", 545), ("9:05", 545), ("23:59", 1439), ("24:00", 1440)],
)
def test_hhmm_to_min(text, minutes):
    assert hhmm_to_min(text) == minutes


@pytest.mark.parametrize("text", ["", "9-05", "25:00", "10:60", "abc", "10:5"])
def test_hhmm_to_min_rejects_garbage(text):
    with pytest.raises(ValueError):
        hhmm_to_min(text)


@pytest.mark.parametrize("minutes", [0, 1, 545, 1439, 1440])
def test_roundtrip(minutes):
    assert hhmm_to_min(min_to_hhmm(minutes)) == minutes


def test_min_to_hhmm_pads():
    assert min_to_hhmm(1) == "00:01"
    assert min_to_hhmm(600) == "10:00"


def test_parse_ru_datetime():
    # Час без ведущего нуля встречается в аварийных заявках Юго-Востока.
    assert parse_ru_datetime("17.08.2026 0:01") == ("2026-08-17", 1)
    assert parse_ru_datetime("17.08.2026 23:59") == ("2026-08-17", 1439)
    assert parse_ru_datetime(" 17.08.2026 10:00 ") == ("2026-08-17", 600)


@pytest.mark.parametrize("text", ["17/08/2026 10:00", "17.08.2026", "32.08.2026 10:00"])
def test_parse_ru_datetime_rejects_garbage(text):
    with pytest.raises(ValueError):
        parse_ru_datetime(text)


def test_fmt_minutes():
    assert fmt_minutes(45) == "45 мин"
    assert fmt_minutes(60) == "1 ч"
    assert fmt_minutes(96) == "1 ч 36 мин"
