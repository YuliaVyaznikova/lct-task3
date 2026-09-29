"""Время внутри ядра минуты от полуночи (int)."""

from __future__ import annotations

import re

_HHMM = re.compile(r"^(\d{1,2}):(\d{2})$")
_DT = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})\s+(\d{1,2}):(\d{2})$")


def hhmm_to_min(value: str) -> int:
    """'9:05' / '09:05' -> 545."""
    m = _HHMM.match(value.strip())
    if not m:
        raise ValueError(f"не время в формате HH:MM: {value!r}")
    hours, minutes = int(m.group(1)), int(m.group(2))
    if minutes > 59 or hours > 24 or (hours == 24 and minutes > 0):
        raise ValueError(f"недопустимое время: {value!r}")
    return hours * 60 + minutes


def min_to_hhmm(value: int) -> str:
    """545 -> '09:05'."""
    if value < 0:
        raise ValueError(f"отрицательное время: {value}")
    return f"{value // 60:02d}:{value % 60:02d}"


def parse_ru_datetime(value: str) -> tuple[str, int]:
    """'17.08.2026 0:01' -> ('2026-08-17', 1)."""
    m = _DT.match(value.strip())
    if not m:
        raise ValueError(f"не дата-время dd.mm.yyyy HH:MM: {value!r}")
    day, month, year, hours, minutes = (int(g) for g in m.groups())
    if not (1 <= month <= 12 and 1 <= day <= 31):
        raise ValueError(f"недопустимая дата: {value!r}")
    if minutes > 59 or hours > 23:
        raise ValueError(f"недопустимое время: {value!r}")
    return f"{year:04d}-{month:02d}-{day:02d}", hours * 60 + minutes


def fmt_minutes(value: int) -> str:
    """Длительность в человекочитаемом виде: 96 -> '1 ч 36 мин', 45 -> '45 мин'."""
    if value < 60:
        return f"{value} мин"
    hours, minutes = divmod(value, 60)
    return f"{hours} ч" if minutes == 0 else f"{hours} ч {minutes} мин"
