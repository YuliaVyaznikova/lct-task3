"""Геокодер: лестница провайдеров и проверка правдоподобия."""

from __future__ import annotations

import pytest

from planner.core.models import GeocodeQuality
from planner.ingest import store
from planner.ingest.address import normalize
from planner.ingest.geocode import (
    Cache,
    Districts,
    GeoResult,
    _jitter,
    _plausible,
    geocode_one,
    haversine_km,
)

OFFICE_VOSTOK = (55.7006, 37.7623)


def test_haversine_known_distance():
    assert 7.3 < haversine_km((55.7520, 37.6175), (55.8197, 37.6117)) < 7.8
    assert haversine_km((55.75, 37.61), (55.75, 37.61)) == 0.0


def test_plausible_accepts_moscow_point():
    addr = normalize("Город Москва, ул.Окская, д. 32")
    result = GeoResult(55.70, 37.76, GeocodeQuality.EXACT, "test", "1")
    assert _plausible(result, addr, OFFICE_VOSTOK, None) is None


def test_plausible_rejects_far_from_office():
    addr = normalize("Город Москва, ул.Окская, д. 32")
    result = GeoResult(55.95, 37.20, GeocodeQuality.EXACT, "test", "1")
    assert _plausible(result, addr, OFFICE_VOSTOK, None) is not None


def test_plausible_rejects_outside_region():
    addr = normalize("Город Москва, ул.Окская, д. 32")
    result = GeoResult(59.93, 30.33, GeocodeQuality.EXACT, "test", "1")
    assert "вне Московского региона" in (_plausible(result, addr, None, None) or "")


def test_district_limit_wider_outside_moscow():
    """Подмосковный «район» целый город, точка в 10 км от центра допустима."""
    moscow = normalize("Город Москва, ул.Окская, д. 32")
    region = normalize("Домодедово, ул.Ильюшина, д. 20")
    centre = (55.44, 37.75)
    point = GeoResult(55.52, 37.79, GeocodeQuality.EXACT, "test", "1")
    assert _plausible(point, region, None, centre) is None
    assert _plausible(point, moscow, None, centre) is not None


def test_jitter_is_deterministic_and_bounded():
    a = _jitter(55.44, 37.75, "адрес")
    b = _jitter(55.44, 37.75, "адрес")
    assert a == b
    assert haversine_km(a, (55.44, 37.75)) <= 0.31
    assert _jitter(55.44, 37.75, "другой адрес") != a


def test_cache_roundtrip(tmp_path):
    cache = Cache(tmp_path / "geo.json")
    result = GeoResult(55.7, 37.6, GeocodeQuality.EXACT, "dadata", "1", "qc_geo=0")
    cache.put("адрес", result)
    cache.save()
    assert Cache(tmp_path / "geo.json").get("адрес") == result


def test_override_wins_over_everything(tmp_path):
    """Ручная правка имеет приоритет и не требует ни сети, ни ключей."""

    class Boom:
        def __getattr__(self, name):
            raise AssertionError("провайдер не должен вызываться при наличии override")

    result, _ = geocode_one(
        "Город Москва, ул.Окская, д. 32",
        "Кузьминки",
        Boom(),
        Districts(tmp_path / "districts.csv"),
        Cache(tmp_path / "geo.json"),
        overrides={"Город Москва, ул.Окская, д. 32": (55.5, 37.5)},
    )
    assert result.quality is GeocodeQuality.MANUAL
    assert (result.lat, result.lon) == (55.5, 37.5)


def test_cached_value_skips_providers(tmp_path):
    class Boom:
        def __getattr__(self, name):
            raise AssertionError("провайдер не должен вызываться при попадании в кэш")

    cache = Cache(tmp_path / "geo.json")
    cache.put("адрес", GeoResult(55.7, 37.6, GeocodeQuality.EXACT, "dadata", "1"))
    result, _ = geocode_one(
        "адрес", "Кузьминки", Boom(), Districts(tmp_path / "d.csv"), cache
    )
    assert result.provider == "dadata"


@pytest.fixture(scope="module")
def scenarios():
    data = {s.id: s for s in store.load_all()}
    if not data:
        pytest.skip("сценарии ещё не собраны: python -m planner.cli build && ... geocode")
    return data


def test_every_order_has_coordinates(scenarios):
    for scenario in scenarios.values():
        assert scenario.office.has_coords, scenario.id
        for order in scenario.orders:
            assert order.has_coords, f"{scenario.id}/{order.id}"
            assert order.geocode_quality is not GeocodeQuality.NONE


def test_coordinates_are_in_moscow_region(scenarios):
    for scenario in scenarios.values():
        for order in scenario.orders:
            assert 54.2 <= order.lat <= 56.95, f"{order.id}: {order.lat}"
            assert 35.1 <= order.lon <= 40.3, f"{order.id}: {order.lon}"


def test_geocoding_quality_is_high(scenarios):
    orders = [o for s in scenarios.values() for o in s.orders]
    exact = sum(
        1 for o in orders if o.geocode_quality in (GeocodeQuality.EXACT, GeocodeQuality.MANUAL)
    )
    assert exact / len(orders) >= 0.90, f"точных только {exact}/{len(orders)}"


def test_moscow_regions_are_compact(scenarios):
    """Восток и Югоцентр целиком в городе признак, что геокодинг не разъехался."""
    for region in ("vostok", "yugocentr"):
        scenario = scenarios[region]
        far = [
            o
            for o in scenario.orders
            if haversine_km(o.coords, scenario.office.coords) > 25
        ]
        assert not far, f"{region}: {[o.id for o in far]}"


def test_yugo_vostok_has_distant_orders(scenarios):
    """У Юго-Востока есть Домодедово, Кашира и Ступино это влияет на достижимость."""
    scenario = scenarios["yugo-vostok"]
    far = [o for o in scenario.orders if haversine_km(o.coords, scenario.office.coords) > 25]
    assert len(far) >= 15
