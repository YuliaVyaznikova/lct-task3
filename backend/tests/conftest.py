"""Игрушечный сценарий для модульных тестов ядра.

Координаты подобраны так, чтобы расстояния были предсказуемыми:
точки лежат на одной широте с шагом примерно 1 км по долготе.
"""

from __future__ import annotations

import pytest

from planner.core.models import (
    Engineer,
    Order,
    Point,
    Priority,
    Scenario,
    Skill,
    Transport,
)
from planner.core.validate import Geo

BASE_LAT = 55.700
BASE_LON = 37.700
KM_IN_DEGREES_LON = 1.0 / 63.0  # на широте Москвы 1° долготы ≈ 63 км


def at_km(east_km: float) -> tuple[float, float]:
    return BASE_LAT, BASE_LON + east_km * KM_IN_DEGREES_LON


def make_order(
    order_id: str,
    east_km: float,
    skill: Skill = Skill.LOCAL,
    window: tuple[str, str] = ("10:00", "18:00"),
    duration: int = 30,
    priority: Priority = Priority.NORMAL,
    required_transport: Transport | None = None,
) -> Order:
    lat, lon = at_km(east_km)
    return Order(
        id=order_id,
        address=f"точка {east_km} км",
        lat=lat,
        lon=lon,
        skill=skill,
        duration_min=duration,
        window_start=window[0],
        window_end=window[1],
        priority=priority,
        required_transport=required_transport,
    )


def make_engineer(
    engineer_id: str,
    skills: list[Skill] | None = None,
    transport: Transport = Transport.CAR,
    shift: tuple[str, str] = ("09:00", "18:00"),
) -> Engineer:
    lat, lon = at_km(0)
    return Engineer(
        id=engineer_id,
        name=f"Инженер {engineer_id}",
        skills=skills or [Skill.LOCAL],
        transport=transport,
        shift_start=shift[0],
        shift_end=shift[1],
        start=Point(address="офис", lat=lat, lon=lon),
    )


def make_scenario(orders: list[Order], engineers: list[Engineer]) -> Scenario:
    lat, lon = at_km(0)
    return Scenario(
        id="toy",
        name="Игрушечный",
        date="2026-08-17",
        office=Point(address="офис", lat=lat, lon=lon),
        orders=orders,
        engineers=engineers,
    )


@pytest.fixture
def toy() -> Scenario:
    """Шесть заявок, три инженера с разными навыками и транспортом."""
    orders = [
        make_order("A", 1, Skill.LOCAL, ("10:00", "12:00")),
        make_order("B", 2, Skill.LOCAL, ("10:00", "12:00")),
        make_order("C", 3, Skill.CONNECTION, ("12:00", "14:00"), duration=70),
        make_order("D", 4, Skill.CONNECTION, ("12:00", "14:00"), duration=70),
        make_order("E", 5, Skill.EMERGENCY, ("10:00", "16:00"), duration=80, priority=Priority.URGENT),
        make_order("F", 6, Skill.LOCAL, ("14:00", "16:00"), required_transport=Transport.CAR),
    ]
    engineers = [
        make_engineer("E01", [Skill.LOCAL, Skill.CONNECTION], Transport.FOOT),
        make_engineer("E02", [Skill.CONNECTION, Skill.EMERGENCY], Transport.CAR),
        make_engineer("E03", [Skill.LOCAL], Transport.CAR),
    ]
    return make_scenario(orders, engineers)


@pytest.fixture
def toy_geo(toy: Scenario) -> Geo:
    return Geo(toy)
