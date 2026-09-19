"""Адаптер выгрузки билайна: CSV (cp1251, разделитель «;») -> Scenario.

Особенности реальных файлов (DESIGN.md §1.2), все учтены ниже:
* набор колонок различается между регионами: «Подключение» есть только у Востока,
  «Статус BK» и «Бригада» — только в контрольном распределении;
* буква «BK» в заголовках — латиница;
* после таблицы синтетики идут пустые строки и строка «Адрес Офиса;<адрес>»
  (в Югоцентре — «Адрес офиса», со строчной «о»);
* час может быть без ведущего нуля: «17.08.2026 0:01»;
* два файла контроля названы с двойной точкой перед расширением.

Порядок строк файла сохраняется: он же — «порядок поступления» заявок
для базового варианта из ТЗ §2.3.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

from planner.core.models import (
    Order,
    Point,
    Priority,
    Scenario,
    ScenarioMeta,
)
from planner.core.timeutil import min_to_hhmm, parse_ru_datetime
from planner.ingest.normatives import classify
from planner.paths import RAW_DIR

ENCODING = "cp1251"
DELIMITER = ";"

# Префикс строки с адресом офиса (регистр и окончание различаются между файлами).
OFFICE_PREFIX = "адрес оф"

# Время события «отмена заявки» в заготовках: за 50 минут до начала окна —
# клиент успевает отказаться, когда бригада уже в пути.
CANCEL_LEAD_MIN = 50

#: Окно шире этого считаем «суточным»: в выгрузке аварии стоят как 0:01–23:59.
FULL_DAY_WINDOW_MIN = 20 * 60

#: В какие часы может возникнуть авария. Эксперты (п.5): «начало выполнения
#: аварийной заявки определяется временем её фактического поступления»,
#: то есть авария возникает в течение рабочего дня, а не висит с полуночи.
INCIDENT_HOURS = (9 * 60, 19 * 60)


@dataclass(frozen=True)
class RegionSpec:
    id: str
    name: str
    code: str
    synthetic_glob: str
    control_glob: str


REGIONS: tuple[RegionSpec, ...] = (
    RegionSpec("vostok", "Восток", "V", "Восток Синтетические*.csv", "Восток Контрольное*.csv"),
    RegionSpec(
        "yugo-vostok",
        "Юго-Восток",
        "YV",
        "Юго-восток Синтетические*.csv",
        "Юго-восток Контрольное*.csv",
    ),
    RegionSpec(
        "yugocentr", "Югоцентр", "YC", "Югоцентр Синтетические*.csv", "Югоцентр Контрольное*.csv"
    ),
)

REGION_BY_ID = {spec.id: spec for spec in REGIONS}


class IngestError(RuntimeError):
    pass


def _read_rows(path: Path) -> tuple[list[str], list[list[str]]]:
    with path.open(encoding=ENCODING, newline="") as fh:
        rows = [row for row in csv.reader(fh, delimiter=DELIMITER) if any(c.strip() for c in row)]
    if not rows:
        raise IngestError(f"пустой файл: {path}")
    return [c.strip() for c in rows[0]], rows[1:]


def _column_index(header: list[str], *names: str) -> int | None:
    """Индекс первой из колонок; сравнение нечувствительно к регистру и раскладке B/В."""
    normalized = [h.strip().casefold().replace("в", "b") for h in header]
    for name in names:
        target = name.strip().casefold().replace("в", "b")
        if target in normalized:
            return normalized.index(target)
    return None


def _cell(row: list[str], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return row[index].strip()


def _split_orders_and_office(rows: list[list[str]]) -> tuple[list[list[str]], str | None]:
    """Строки заявок (первая ячейка — число) и адрес офиса из служебной строки."""
    orders: list[list[str]] = []
    office: str | None = None
    for row in rows:
        first = row[0].strip() if row else ""
        if first.casefold().startswith(OFFICE_PREFIX):
            office = _cell(row, 1) or None
            continue
        if first.isdigit():
            orders.append(row)
    return orders, office


def load_region(
    synthetic_csv: Path,
    control_csv: Path | None = None,
    *,
    spec: RegionSpec | None = None,
) -> Scenario:
    """Собирает Scenario без координат и без инженеров — их добавляют следующие шаги."""
    spec = spec or _guess_spec(synthetic_csv)
    header, rows = _read_rows(synthetic_csv)
    order_rows, office_address = _split_orders_and_office(rows)
    if not order_rows:
        raise IngestError(f"в файле нет строк заявок: {synthetic_csv}")
    if not office_address:
        raise IngestError(
            f"не найдена строка с адресом офиса (префикс «{OFFICE_PREFIX}…») в {synthetic_csv}"
        )

    idx = {
        "external_id": _column_index(header, "Заявка"),
        "work_type": _column_index(header, "Тип заявки BK"),
        "hd_type": _column_index(header, "Тип заявки HD"),
        "start": _column_index(header, "Начало"),
        "end": _column_index(header, "Окончание"),
        "district": _column_index(header, "Район"),
        "address": _column_index(header, "Адрес"),
        "connection": _column_index(header, "Подключение"),
        "gigabit": _column_index(header, "Гигабитное подключение"),
    }
    for required in ("work_type", "hd_type", "start", "end", "address"):
        if idx[required] is None:
            raise IngestError(f"в {synthetic_csv.name} нет обязательной колонки «{required}»")

    orders: list[Order] = []
    date: str | None = None
    for number, row in enumerate(order_rows, start=1):
        work_type = _cell(row, idx["work_type"])
        hd_type = _cell(row, idx["hd_type"])
        norm = classify(work_type, hd_type)

        start_date, window_start = parse_ru_datetime(_cell(row, idx["start"]))
        end_date, window_end = parse_ru_datetime(_cell(row, idx["end"]))
        date = date or start_date
        if end_date != start_date:
            # В данных такого нет, но окно через полночь сломало бы арифметику смены.
            raise IngestError(f"окно заявки пересекает сутки: строка {number} в {synthetic_csv.name}")

        attributes: dict[str, object] = {}
        connection = _cell(row, idx["connection"])
        if connection:
            attributes["connection"] = connection
        gigabit = _cell(row, idx["gigabit"])
        if gigabit:
            attributes["gigabit"] = gigabit.casefold() == "да"
        attributes["normative"] = norm.name

        orders.append(
            Order(
                id=f"{spec.code}-{number:03d}",
                external_id=_cell(row, idx["external_id"]),
                address=_cell(row, idx["address"]),
                district=_cell(row, idx["district"]),
                skill=norm.skill,
                work_type=work_type,
                description=hd_type,
                duration_min=norm.duration_min,
                window_start=min_to_hhmm(window_start),
                window_end=min_to_hhmm(window_end),
                priority=norm.priority,
                priority_tier=norm.priority_tier,
                attributes=attributes,
            )
        )

    scenario = Scenario(
        id=spec.id,
        name=spec.name,
        date=date or "",
        office=Point(address=office_address),
        orders=orders,
        meta=ScenarioMeta(source="beeline", notes=f"синтетика: {synthetic_csv.name}"),
    )

    assign_incident_times(scenario)
    if control_csv is not None:
        attach_control(scenario, control_csv)
    return scenario


def attach_control(scenario: Scenario, control_csv: Path) -> int:
    """Переносит «Статус BK» и «Бригада» из контроля в attributes заявок.

    Сопоставление построчное: i-я строка синтетики соответствует i-й строке контроля
    (файлы совпадают по составу и порядку, синтетика — это контроль без статуса,
    бригады и номера квартиры). Каждая пара сверяется по типу заявки и окну;
    при расхождении строка пропускается, и возвращённое число будет меньше.
    """
    header, rows = _read_rows(control_csv)
    control_rows, _ = _split_orders_and_office(rows)
    idx = {
        "work_type": _column_index(header, "Тип заявки BK"),
        "start": _column_index(header, "Начало"),
        "status": _column_index(header, "Статус BK"),
        "brigade": _column_index(header, "Бригада"),
        "external_id": _column_index(header, "Заявка"),
    }
    matched = 0
    for order, row in zip(scenario.orders, control_rows, strict=False):
        if _cell(row, idx["work_type"]) != order.work_type:
            continue
        _, window_start = parse_ru_datetime(_cell(row, idx["start"]))
        if min_to_hhmm(window_start) != order.window_start:
            continue
        status = _cell(row, idx["status"])
        brigade = _cell(row, idx["brigade"])
        if status:
            order.attributes["control_status"] = status
        if brigade:
            order.attributes["control_engineer"] = brigade
        control_id = _cell(row, idx["external_id"])
        if control_id:
            order.attributes["control_id"] = control_id
        matched += 1
    scenario.meta.notes += f"; контроль: {control_csv.name} ({matched} строк)"
    return matched


def assign_incident_times(scenario: Scenario, seed: int = 42) -> int:
    """Проставляет аварийным заявкам время фактического поступления.

    В выгрузке аварии записаны окном 0:01–23:59: это не значит, что их можно
    начинать с полуночи, — это суточный срок обязательства перед клиентом.
    Эксперты уточнили, что авария возникает в течение дня и с этого момента
    влияет на расписание бригады. Самого времени в данных нет, поэтому оно
    распределяется по рабочему дню детерминированно — одинаково при каждом
    запуске, чтобы демонстрация была воспроизводимой.
    """
    import hashlib

    low, high = INCIDENT_HOURS
    marked = 0
    for order in scenario.orders:
        span = order.window_end_min - order.window_start_min
        if order.priority is not Priority.URGENT or span < FULL_DAY_WINDOW_MIN:
            continue
        digest = hashlib.sha256(f"{seed}|{order.id}".encode()).digest()
        reported = low + int.from_bytes(digest[:4], "big") % max(1, high - low)
        reported -= reported % 5  # ровные пять минут читаются лучше
        order.window_start = min_to_hhmm(reported)
        order.attributes["reported_at"] = order.window_start
        order.attributes["incident_window"] = "сутки от поступления"
        marked += 1
    return marked


def cancelled_orders(scenario: Scenario) -> list[Order]:
    """Заявки, отменённые в контрольном распределении, — кандидаты на событие «отмена»."""
    return [o for o in scenario.orders if o.attributes.get("control_status") == "Отменена"]


def control_brigades(scenario: Scenario) -> list[str]:
    """Бригады из контроля в порядке появления — ориентир для числа инженеров."""
    seen: list[str] = []
    for order in scenario.orders:
        brigade = order.attributes.get("control_engineer")
        if isinstance(brigade, str) and brigade and brigade not in seen:
            seen.append(brigade)
    return seen


def _guess_spec(path: Path) -> RegionSpec:
    name = path.name.casefold()
    # «Юго-восток» проверяем раньше «Восток»: иначе подстрока совпадёт не с тем регионом.
    for spec in sorted(REGIONS, key=lambda s: -len(s.name)):
        if spec.name.casefold() in name:
            return spec
    raise IngestError(f"не удалось определить регион по имени файла: {path.name}")


def find_region_files(spec: RegionSpec, raw_dir: Path | None = None) -> tuple[Path, Path | None]:
    raw_dir = raw_dir or RAW_DIR
    synthetic = sorted(raw_dir.glob(spec.synthetic_glob))
    control = sorted(raw_dir.glob(spec.control_glob))
    if not synthetic:
        raise IngestError(f"не найден файл синтетики «{spec.synthetic_glob}» в {raw_dir}")
    return synthetic[0], (control[0] if control else None)


def load_all(raw_dir: Path | None = None) -> list[Scenario]:
    scenarios = []
    for spec in REGIONS:
        synthetic, control = find_region_files(spec, raw_dir)
        scenarios.append(load_region(synthetic, control, spec=spec))
    return scenarios


_SUFFIX_RE = re.compile(r"\s+")


def normalize_whitespace(value: str) -> str:
    return _SUFFIX_RE.sub(" ", value).strip()
