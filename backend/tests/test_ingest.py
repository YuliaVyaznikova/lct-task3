"""Проверки адаптера выгрузки на реальных файлах из data/raw."""

from __future__ import annotations

import collections
import csv
import io

import pytest

from planner.core.models import Priority, Skill
from planner.ingest import beeline
from planner.ingest.normatives import classify
from planner.paths import RAW_DIR

EXPECTED = {
    "vostok": {"orders": 66, "brigades": 12, "cancelled": 6},
    "yugo-vostok": {"orders": 83, "brigades": 12, "cancelled": 10},
    "yugocentr": {"orders": 56, "brigades": 11, "cancelled": 5},
}


@pytest.fixture(scope="module")
def scenarios():
    if not RAW_DIR.is_dir():
        pytest.skip("нет data/raw с выгрузкой билайна")
    return {s.id: s for s in beeline.load_all()}


def test_all_regions_load(scenarios):
    assert set(scenarios) == set(EXPECTED)


@pytest.mark.parametrize("region", sorted(EXPECTED))
def test_order_counts(scenarios, region):
    assert len(scenarios[region].orders) == EXPECTED[region]["orders"]


@pytest.mark.parametrize("region", sorted(EXPECTED))
def test_office_found(scenarios, region):
    office = scenarios[region].office.address
    assert office, "адрес офиса обязателен: это стартовая точка всех инженеров"
    assert "осква" in office or "Симферопольск" in office


@pytest.mark.parametrize("region", sorted(EXPECTED))
def test_control_attached(scenarios, region):
    scenario = scenarios[region]
    assert len(beeline.control_brigades(scenario)) == EXPECTED[region]["brigades"]
    assert len(beeline.cancelled_orders(scenario)) == EXPECTED[region]["cancelled"]


@pytest.mark.parametrize("region", sorted(EXPECTED))
def test_every_order_has_required_fields(scenarios, region):
    for order in scenarios[region].orders:
        assert order.id.startswith(("V-", "YV-", "YC-"))
        assert order.external_id.isdigit()
        assert order.address
        assert order.duration_min > 0
        assert order.window_start_min < order.window_end_min


@pytest.mark.parametrize("region", sorted(EXPECTED))
def test_same_date_everywhere(scenarios, region):
    assert scenarios[region].date == "2026-08-17"


def test_ids_are_unique_and_ordered(scenarios):
    for scenario in scenarios.values():
        ids = [o.id for o in scenario.orders]
        assert len(set(ids)) == len(ids)
        assert ids == sorted(ids)


def test_midnight_window_parsed(scenarios):
    """Аварии Юго-Востока записаны окном 0:01–23:59 час без ведущего нуля."""
    day_long = [o for o in scenarios["yugo-vostok"].orders if o.window_end == "23:59"]
    assert len(day_long) == 11
    assert all(o.priority is Priority.URGENT for o in day_long)


def test_incidents_get_an_arrival_time(scenarios):
    """Суточное окно это срок обязательства, а не разрешение начать с полуночи."""
    incidents = [
        o for o in scenarios["yugo-vostok"].orders if o.attributes.get("reported_at")
    ]
    assert len(incidents) == 11
    for order in incidents:
        assert order.window_start == order.attributes["reported_at"]
        assert "10:00" <= order.window_start <= "20:00"
        assert order.window_start != "00:01"


def test_incident_times_are_reproducible():
    """Демонстрация должна повторяться: время поступления не случайно от запуска."""
    from planner.ingest.beeline import REGION_BY_ID, find_region_files, load_region

    spec = REGION_BY_ID["yugo-vostok"]
    synthetic, control = find_region_files(spec)
    first = load_region(synthetic, control, spec=spec)
    second = load_region(synthetic, control, spec=spec)
    assert [o.window_start for o in first.orders] == [o.window_start for o in second.orders]


def test_optional_connection_column(scenarios):
    """Колонка «Подключение» (FMC/FTTB) есть только у Востока остальные не должны падать."""
    assert any("connection" in o.attributes for o in scenarios["vostok"].orders)
    assert all("connection" not in o.attributes for o in scenarios["yugocentr"].orders)


def test_skill_distribution(scenarios):
    counts = collections.Counter(o.skill for o in scenarios["vostok"].orders)
    assert counts == {Skill.CONNECTION: 37, Skill.LOCAL: 21, Skill.EMERGENCY: 8}


def test_durations_follow_normatives(scenarios):
    """Длительность = тех."""
    by_type = {
        ("Подключение", ""): 70,
        ("Дозаказ", ""): 20,
        ("Локальная заявка", ""): 30,
        ("Глобальная проблема", "Авария"): 80,
        ("Глобальная проблема", "Информация"): 30,
    }
    for (work_type, hd), expected in by_type.items():
        assert classify(work_type, hd).duration_min == expected


def test_emergency_is_urgent_but_information_is_not():
    assert classify("Глобальная проблема", "Авария").priority is Priority.URGENT
    assert classify("Глобальная проблема", "Информация").priority is Priority.NORMAL
    assert classify("Глобальная проблема", "Информация").skill is Skill.EMERGENCY


def test_unknown_type_falls_back_to_local():
    norm = classify("Неведомый тип", "Что-то новое")
    assert norm.skill is Skill.LOCAL
    assert norm.duration_min == 30


def test_region_guessed_from_filename():
    """«Юго-восток» не должен определяться как «Восток» по подстроке."""
    synthetic, _ = beeline.find_region_files(beeline.REGION_BY_ID["yugo-vostok"])
    assert beeline._guess_spec(synthetic).id == "yugo-vostok"


@pytest.mark.parametrize(
    ("encoding", "delimiter"),
    [("utf-8-sig", ";"), ("utf-8", ","), ("cp1251", "\t")],
)
def test_export_saved_in_another_encoding_reads_the_same(tmp_path, encoding, delimiter):
    """Выгрузка, пересохранённая в Excel или редакторе, даёт те же заявки, что исходный файл."""
    if not RAW_DIR.is_dir():
        pytest.skip("нет data/raw с выгрузкой билайна")
    source, _ = beeline.find_region_files(beeline.REGION_BY_ID["vostok"])
    rows = list(csv.reader(io.StringIO(source.read_text(encoding="cp1251"), newline=""), delimiter=";"))
    resaved = tmp_path / source.name
    with resaved.open("w", encoding=encoding, newline="") as fh:
        csv.writer(fh, delimiter=delimiter).writerows(rows)

    original = beeline.load_region(source)
    converted = beeline.load_region(resaved)

    assert len(converted.orders) == 66
    assert converted.office.address == original.office.address
    assert [o.model_dump() for o in converted.orders] == [o.model_dump() for o in original.orders]


def test_unreadable_encoding_is_refused_in_russian(tmp_path):
    broken = tmp_path / "Восток Синтетические данные.csv"
    broken.write_bytes("Тип заявки BK;Адрес\n".encode("utf-16"))

    with pytest.raises(beeline.IngestError) as error:
        beeline.load_region(broken)

    assert "кодировк" in str(error.value)
