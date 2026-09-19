"""Модель времени в пути (DESIGN.md §5)."""

from __future__ import annotations

import pytest

from planner.core.models import Transport
from planner.core.travel import DETOUR_FACTOR, PROFILES, TravelModel, describe, haversine_km


def test_haversine_symmetric_and_zero_on_diagonal():
    a, b = (55.70, 37.70), (55.75, 37.80)
    assert haversine_km(*a, *b) == pytest.approx(haversine_km(*b, *a))
    assert haversine_km(*a, *a) == 0.0


def test_matrix_applies_detour_factor():
    points = [(55.700, 37.700), (55.700, 37.7159)]  # примерно 1 км по долготе
    model = TravelModel(points)
    straight = haversine_km(*points[0], *points[1])
    assert model.distance_km(0, 1) == pytest.approx(straight * DETOUR_FACTOR, rel=1e-6)


def test_matrix_diagonal_is_zero():
    model = TravelModel([(55.70, 37.70), (55.71, 37.72), (55.72, 37.74)])
    for i in range(model.size):
        assert model.distance_km(i, i) == 0.0
        for transport in Transport:
            assert model.time_min(transport)[i, i] == 0


def test_profiles_are_monotonic():
    for transport, profile in PROFILES.items():
        previous = -1.0
        for km in (0.5, 1, 2, 3, 5, 10, 20, 40, 91):
            value = profile.minutes(km)
            assert value > previous, transport
            previous = value


def test_car_matches_the_official_travel_norm():
    """Норматив «дорога до клиента» — 20 мин; типичный переезд внутри района 3–5 км."""
    car = PROFILES[Transport.CAR]
    assert 12 <= car.minutes(3) <= 20
    assert 15 <= car.minutes(5) <= 25


def test_long_trip_uses_highway_speed():
    """До Каширы 91 км: с единой городской скоростью вышло бы четыре часа."""
    minutes = PROFILES[Transport.CAR].minutes(91)
    assert 90 <= minutes <= 150


def test_public_transport_is_slower_than_car_but_reaches_far():
    car = PROFILES[Transport.CAR].minutes(91)
    public = PROFILES[Transport.PUBLIC].minutes(91)
    assert car < public < 240


def test_walking_far_is_effectively_impossible():
    """Пешеход до Каширы идёт двадцать часов — такие заявки честно станут недостижимыми."""
    assert PROFILES[Transport.FOOT].minutes(91) > 12 * 60


def test_short_hops_have_realistic_overhead():
    """На 500 метрах пешком быстрее автомобиля и общественного транспорта."""
    assert PROFILES[Transport.FOOT].minutes(0.5) <= PROFILES[Transport.CAR].minutes(0.5)
    assert PROFILES[Transport.FOOT].minutes(0.5) < PROFILES[Transport.PUBLIC].minutes(0.5)


def test_zero_distance_costs_nothing():
    for profile in PROFILES.values():
        assert profile.minutes(0) == 0.0


def test_travel_returns_km_and_minutes():
    model = TravelModel([(55.700, 37.700), (55.700, 37.7794)])  # около 5 км
    km, minutes = model.travel(Transport.CAR, 0, 1)
    assert 5.5 < km < 7.5
    assert 15 <= minutes <= 25


def test_time_matrix_is_cached():
    model = TravelModel([(55.70, 37.70), (55.71, 37.72)])
    assert model.time_min(Transport.CAR) is model.time_min(Transport.CAR)


def test_matrix_build_is_fast_enough_to_skip_caching():
    """Обоснование отказа от кэша матриц на диске (DESIGN.md §5)."""
    import time

    points = [(55.5 + i * 0.004, 37.5 + i * 0.006) for i in range(85)]
    start = time.perf_counter()
    model = TravelModel(points)
    for transport in Transport:
        model.time_min(transport)
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert elapsed_ms < 500, f"построение матриц заняло {elapsed_ms:.0f} мс"


def test_describe_mentions_every_transport():
    text = describe()
    for transport in Transport:
        assert transport.value in text
