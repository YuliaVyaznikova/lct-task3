"""Конвертер нормализованных выгрузок «регион × дата» во входной формат сценариев."""

from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from planner.core import equipment
from planner.core.models import GeocodeQuality, Order, Point, Scenario, ScenarioMeta
from planner.ingest import beeline, engineers, geocode, store
from planner.ingest.address import NormalizedAddress
from planner.ingest.normatives import classify
from planner.paths import EXTRA_DIR

ENCODING = "utf-8-sig"
DELIMITER = ";"
CANCELLED_STATUS = "Отменена"
CANCELLED_DIR = "cancelled"
EXTRA_DISTRICTS = EXTRA_DIR / "dop_dni_districts.csv"


class OfflineProviders(geocode.Providers):
    """Геокодеры выключены: работают только кэш и центроиды районов."""

    def __init__(self) -> None:
        self.errors: list[str] = []

    def dadata(self, addr: NormalizedAddress) -> None:
        return None

    def yandex(self, addr: NormalizedAddress) -> None:
        return None

    def nominatim_structured(self, addr: NormalizedAddress) -> None:
        return None

    def nominatim_no_korpus(self, addr: NormalizedAddress) -> None:
        return None

    def photon(self, addr: NormalizedAddress) -> None:
        return None

    def nominatim_street_only(self, addr: NormalizedAddress) -> None:
        return None


@dataclass
class ConvertedSet:
    scenario: Scenario
    cancelled: list[dict[str, str]]
    quality: Counter[str] = field(default_factory=Counter)
    new_hd_types: set[str] = field(default_factory=set)


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding=ENCODING, newline="") as fh:
        return list(csv.DictReader(fh, delimiter=DELIMITER))


def group_by_region_and_date(rows: list[dict[str, str]]) -> dict[tuple[str, str], list[dict[str, str]]]:
    """Наборы по содержимому строк: колонки региона и даты, а не имя файла."""
    groups: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in rows:
        groups.setdefault((row["region"], row["date"]), []).append(row)
    return groups


def scenario_id(region_id: str, date: str) -> str:
    day, month, year = date.split(".")
    return f"{region_id}-{year}{month}{day}"


def order_id(region_id: str, date: str, external_id: str) -> str:
    return f"{scenario_id(region_id, date)}-{external_id}"


def _district_points() -> geocode.Districts:
    districts = geocode.Districts()
    districts.points.update(geocode.Districts(EXTRA_DISTRICTS).points)
    return districts


def _to_order(row: dict[str, str], region_id: str) -> Order:
    norm = classify(row["bk_type"], row["hd_type"])
    attributes: dict[str, object] = {
        "normative": norm.name,
        "gigabit": row["gigabit"].strip().casefold() == "да",
        "source_status": row["status_bk"],
    }
    return Order(
        id=order_id(region_id, row["date"], row["external_id"]),
        external_id=row["external_id"],
        address=row["address"],
        district=row["district"],
        skill=norm.skill,
        work_type=row["bk_type"],
        description=row["hd_type"],
        duration_min=norm.duration_min,
        window_start=row["window_start"],
        window_end=row["window_end"],
        priority=norm.priority,
        priority_tier=norm.priority_tier,
        attributes=attributes,
    )


def _locate(scenario: Scenario, districts: geocode.Districts, cache: geocode.Cache) -> Counter[str]:
    providers = OfflineProviders()
    office = (scenario.office.lat, scenario.office.lon)
    quality: Counter[str] = Counter()
    for order in scenario.orders:
        result, _ = geocode.geocode_one(
            order.address, order.district, providers, districts, cache, office
        )
        order.lat, order.lon = result.lat, result.lon
        order.geocode_quality = result.quality
        quality[result.quality.value] += 1
    return quality


def _known_hd_types(base: Scenario) -> set[str]:
    return {order.description for order in base.orders}


def convert_set(
    rows: list[dict[str, str]],
    base: Scenario,
    region_id: str,
    districts: geocode.Districts | None = None,
    cache: geocode.Cache | None = None,
) -> ConvertedSet:
    """Собирает сценарий набора; офис берётся у базового сценария региона, отмены исключаются."""
    date = rows[0]["date"]
    planned = [row for row in rows if row["status_bk"] != CANCELLED_STATUS]
    cancelled = [row for row in rows if row["status_bk"] == CANCELLED_STATUS]
    scenario = Scenario(
        id=scenario_id(region_id, date),
        name=f"{base.name} {date}",
        date=date,
        office=Point(address=base.office.address, lat=base.office.lat, lon=base.office.lon),
        orders=[_to_order(row, region_id) for row in planned],
        meta=ScenarioMeta(source="dop-dni", notes=f"доп. день {date}, отмены исключены"),
    )
    beeline.assign_incident_times(scenario)
    equipment.populate(scenario)
    quality = _locate(scenario, districts or _district_points(), cache or geocode.Cache())
    engineers.populate(scenario, region_id=region_id)
    new_hd = {row["hd_type"] for row in rows} - _known_hd_types(base)
    return ConvertedSet(scenario, cancelled, quality, new_hd)


def convert_files(
    paths: list[Path], out_dir: Path, base_dir: Path | None = None
) -> list[ConvertedSet]:
    """Читает выгрузки, пишет сценарии и списки отмен в out_dir."""
    rows = [row for path in paths for row in read_rows(path)]
    converted: list[ConvertedSet] = []
    for (region_id, date), group in sorted(group_by_region_and_date(rows).items()):
        base = store.load(region_id, base_dir)
        result = convert_set(group, base, region_id)
        store.save(result.scenario, out_dir)
        cancelled_path = out_dir / CANCELLED_DIR / f"{result.scenario.id}.json"
        cancelled_path.parent.mkdir(parents=True, exist_ok=True)
        cancelled_path.write_text(
            json.dumps(result.cancelled, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        converted.append(result)
    return converted


def describe(result: ConvertedSet) -> str:
    centroids = result.quality[GeocodeQuality.DISTRICT.value]
    return (
        f"{result.scenario.id}: заявок {len(result.scenario.orders)}, "
        f"отмен {len(result.cancelled)}, инженеров {len(result.scenario.engineers)}, "
        f"центроидов {centroids} из {len(result.scenario.orders)}"
    )
