"""Модель времени в пути."""

from __future__ import annotations

import pytest

from planner.core.models import Transport
from planner.core.travel import (
    DETOUR_CALIBRATION,
    PROFILES,
    TravelModel,
    describe,
    detour_factor,
    haversine_km,
)


def test_haversine_symmetric_and_zero_on_diagonal():
    a, b = (55.70, 37.70), (55.75, 37.80)
    assert haversine_km(*a, *b) == pytest.approx(haversine_km(*b, *a))
    assert haversine_km(*a, *a) == 0.0


def test_haversine_known_distance():
    assert 7.3 < haversine_km(55.7520, 37.6175, 55.8197, 37.6117) < 7.8


def test_matrix_applies_detour_factor():
    points = [(55.700, 37.700), (55.700, 37.7159)]
    model = TravelModel(points)
    straight = haversine_km(*points[0], *points[1])
    expected = straight * float(detour_factor(straight))
    assert model.distance_km(0, 1) == pytest.approx(expected, rel=1e-6)
    assert model.distance_km(0, 1) > straight, "дорога длиннее прямой"


def test_detour_factor_is_calibrated_by_distance():
    """Коэффициент измерен по реальной сети: в городе объезд больше, на трассе меньше."""
    for (km, factor) in DETOUR_CALIBRATION:
        assert float(detour_factor(km)) == pytest.approx(factor, abs=1e-9)
    assert float(detour_factor(0.5)) > float(detour_factor(6.0)) > float(detour_factor(60.0))
    assert float(detour_factor(0.05)) == pytest.approx(DETOUR_CALIBRATION[0][1])
    assert float(detour_factor(500)) == pytest.approx(DETOUR_CALIBRATION[-1][1])


def test_road_distance_grows_with_straight_distance():
    """Иначе поездка на 1.01 км оказалась бы короче поездки на 0.99 км."""
    previous = 0.0
    for km in (0.1, 0.3, 0.5, 0.9, 1.1, 2, 3, 6, 10, 20, 30, 60, 91, 150):
        road = km * float(detour_factor(km))
        assert road > previous, f"немонотонно на {km} км"
        previous = road


def test_matrix_diagonal_is_zero():
    model = TravelModel([(55.70, 37.70), (55.71, 37.72), (55.72, 37.74)])
    for i in range(len(model.points)):
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
    """Норматив «дорога до клиента» 20 мин; типичный переезд внутри района 3–5 км."""
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
    """Пешеход до Каширы идёт двадцать часов такие заявки честно станут недостижимыми."""
    assert PROFILES[Transport.FOOT].minutes(91) > 12 * 60


def test_short_hops_have_realistic_overhead():
    """На 500 метрах пешком быстрее автомобиля и общественного транспорта."""
    assert PROFILES[Transport.FOOT].minutes(0.5) <= PROFILES[Transport.CAR].minutes(0.5)
    assert PROFILES[Transport.FOOT].minutes(0.5) < PROFILES[Transport.PUBLIC].minutes(0.5)


def test_zero_distance_costs_nothing():
    for profile in PROFILES.values():
        assert profile.minutes(0) == 0.0


def test_travel_returns_km_and_minutes():
    model = TravelModel([(55.700, 37.700), (55.700, 37.7794)])
    km, minutes = model.travel(Transport.CAR, 0, 1)
    assert 5.5 < km < 7.5
    assert 15 <= minutes <= 25


def test_time_matrix_is_cached():
    model = TravelModel([(55.70, 37.70), (55.71, 37.72)])
    assert model.time_min(Transport.CAR) is model.time_min(Transport.CAR)


def test_matrix_build_is_fast_enough_to_skip_caching():
    """Обоснование отказа от кэша матриц на диске."""
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


def test_osrm_falls_back_when_service_is_unreachable():
    """Недоступный маршрутизатор не должен срывать построение плана."""
    from planner.core.travel import OsrmTravel

    points = [(55.70, 37.70), (55.71, 37.72)]
    model = OsrmTravel(points, "http://127.0.0.1:1", timeout_s=0.5)
    assert model.connected is False
    assert model.errors
    assert "недоступен" in model.name
    assert model.distance_km(0, 1) > 0


def test_build_returns_offline_model_without_configuration(monkeypatch):
    from planner.core import travel as travel_module

    monkeypatch.delenv("OSRM_URL", raising=False)
    model = travel_module.build([(55.70, 37.70), (55.71, 37.72)])
    assert type(model) is TravelModel
    assert model.name == "haversine"


def test_build_falls_back_to_offline_on_bad_url(monkeypatch):
    """Оценка по прямой, но в названии модели видно, что OSRM не ответил;
    раньше модель выдавала себя за обычную оценку."""
    from planner.core import travel as travel_module

    monkeypatch.setenv("OSRM_URL", "http://127.0.0.1:1")
    points = [(55.70, 37.70), (55.71, 37.72)]
    model = travel_module.build(points)
    assert model.distance_km(0, 1) == TravelModel(points).distance_km(0, 1)
    assert model.name.startswith("haversine (osrm недоступен: ")


def test_osrm_refuses_oversized_requests():
    from planner.core.travel import OsrmTravel

    points = [(55.0 + i * 0.001, 37.0 + i * 0.001) for i in range(OsrmTravel.MAX_POINTS + 1)]
    model = OsrmTravel(points, "http://127.0.0.1:1", timeout_s=0.5)
    assert model.connected is False
    assert any("предел запроса" in e for e in model.errors)


def test_osrm_uses_our_speed_profiles_not_free_flow_times(tmp_path):
    """Публичный OSRM отдаёт время без пробок; время должно оставаться нашим."""
    import numpy as np

    from planner.core.travel import OsrmTravel

    points = [(55.70, 37.70), (55.75, 37.78)]
    model = OsrmTravel(points, "http://127.0.0.1:1", timeout_s=0.5, cache_dir=tmp_path)
    model._apply(np.array([[0.0, 10.0], [10.0, 0.0]]))
    expected = round(PROFILES[Transport.CAR].minutes(10.0))
    assert model.time_min(Transport.CAR)[0, 1] == expected
