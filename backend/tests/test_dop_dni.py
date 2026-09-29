"""Конвертер доп. дней на синтетической выгрузке из нескольких строк."""

from __future__ import annotations

from planner.core.models import GeocodeQuality, Point, Scenario
from planner.ingest import dop_dni, geocode, store

HEADER = (
    "region;date;source_file;external_id;bk_type;status_bk;hd_type;window_start;window_end;"
    "district;address;gigabit;is_emergency_hd;bk_hd_mismatch_emergency;outside_moscow"
)
ROWS = [
    "vostok;28.09.2026;a.csv;101;Подключение;Выполнена;Конвергенция абонента;12:00;14:00;Выхино;Москва, ул Тестовая, д 1;Да;0;0;0",
    "vostok;28.09.2026;a.csv;102;Локальная заявка;Отменена;Нет линка;12:00;14:00;GPON Выхино;Москва, ул Тестовая, д 2;;0;0;0",
    "vostok;29.09.2026;b.csv;101;Глобальная проблема;Отправлена;Авария;00:01;23:59;Выхино;Москва, ул Тестовая, д 1;;1;0;0",
]


def write_csv(path, rows):
    path.write_text("\n".join([HEADER, *rows]) + "\n", encoding="utf-8-sig")
    return path


def make_base(tmp_path) -> Scenario:
    base = Scenario(
        id="vostok", name="Восток", date="2026-08-17",
        office=Point(address="Москва, ул Офисная, д 1", lat=55.7, lon=37.76),
    )
    store.save(base, tmp_path / "base")
    return base


def test_sets_are_split_by_content_and_ids_do_not_clash(tmp_path):
    make_base(tmp_path)
    source = write_csv(tmp_path / "renamed-anything.csv", ROWS)
    converted = dop_dni.convert_files([source], tmp_path / "out", tmp_path / "base")
    assert [c.scenario.id for c in converted] == ["vostok-20260928", "vostok-20260929"]
    ids = [o.id for c in converted for o in c.scenario.orders]
    assert len(ids) == len(set(ids))
    assert ids[0] == "vostok-20260928-101"


def test_cancelled_rows_are_left_out_of_the_plan(tmp_path):
    make_base(tmp_path)
    source = write_csv(tmp_path / "x.csv", ROWS)
    first = dop_dni.convert_files([source], tmp_path / "out", tmp_path / "base")[0]
    assert [o.external_id for o in first.scenario.orders] == ["101"]
    assert [row["external_id"] for row in first.cancelled] == ["102"]
    assert (tmp_path / "out" / "cancelled" / "vostok-20260928.json").is_file()


def test_missing_district_uses_extra_centroid_and_office_comes_from_base(tmp_path):
    base = make_base(tmp_path)
    rows = dop_dni.group_by_region_and_date(
        dop_dni.read_rows(write_csv(tmp_path / "x.csv", ROWS))
    )[("vostok", "28.09.2026")]
    result = dop_dni.convert_set(rows, base, "vostok", cache=geocode.Cache(tmp_path / "none.json"))
    assert result.scenario.office.address == base.office.address
    assert result.quality[GeocodeQuality.DISTRICT.value] == 1
    assert len(result.scenario.engineers) == 12


def test_emergency_order_keeps_urgent_priority(tmp_path):
    base = make_base(tmp_path)
    rows = dop_dni.group_by_region_and_date(
        dop_dni.read_rows(write_csv(tmp_path / "x.csv", ROWS))
    )[("vostok", "29.09.2026")]
    order = dop_dni.convert_set(rows, base, "vostok", cache=geocode.Cache(tmp_path / "n.json")).scenario.orders[0]
    assert order.priority.value == "urgent"
