"""Разбиение участка на зоны и штраф за переходы между ними."""

from __future__ import annotations

import numpy as np
import pytest

from planner.core import solver, zones
from planner.core.models import PlanParams
from planner.core.validate import Geo
from planner.ingest import store


def distances(points_km: list[float]) -> np.ndarray:
    size = len(points_km)
    matrix = np.zeros((size, size), dtype=np.int64)
    for i in range(size):
        for j in range(size):
            matrix[i, j] = int(abs(points_km[i] - points_km[j]) * 1000)
    return matrix


def test_everything_near_the_office_is_one_zone():
    result = zones.split_into_zones(distances([0.0, 5.0, 12.0, 24.0]), office_node=0)
    assert result == [0, 0, 0, 0]


def test_far_points_form_their_own_cluster():
    result = zones.split_into_zones(distances([0.0, 10.0, 60.0, 65.0]), office_node=0)
    assert result[0] == result[1] == zones.BASE_ZONE
    assert result[2] == result[3] != zones.BASE_ZONE


def test_two_distant_clusters_do_not_merge():
    result = zones.split_into_zones(distances([0.0, 40.0, 90.0]), office_node=0)
    assert len({result[1], result[2]}) == 2
    assert zones.BASE_ZONE not in {result[1], result[2]}


def test_chain_of_close_points_stays_one_cluster():
    result = zones.split_into_zones(distances([0.0, 40.0, 55.0, 70.0]), office_node=0)
    assert result[1] == result[2] == result[3]


def test_town_on_the_radius_is_not_split():
    """Город на границе радиуса целиком уходит в удалённую зону, а ближние районы остаются в офисной."""
    result = zones.split_into_zones(distances([0.0, 12.0, 23.0, 27.0]), office_node=0)
    assert result[3] != zones.BASE_ZONE
    assert result[2] == result[3]
    assert result[0] == result[1] == zones.BASE_ZONE


@pytest.fixture(scope="module")
def scenarios():
    data = {s.id: s for s in store.load_all()}
    if not data:
        pytest.skip("сценарии ещё не собраны")
    return data


def test_compact_regions_have_a_single_zone(scenarios):
    for region in ("vostok", "yugocentr"):
        geo = Geo(scenarios[region])
        assert set(geo.zones) == {zones.BASE_ZONE}


def zone_sequence(geo, scenario, route) -> list[int]:
    engineer = scenario.engineers_by_id[route.engineer_id]
    visited = [geo.zone(geo.start_node(engineer))]
    visited += [geo.zone(geo.node(stop.order_id)) for stop in route.stops]
    return [zone for index, zone in enumerate(visited) if index == 0 or zone != visited[index - 1]]


def test_no_engineer_zigzags_between_zones(scenarios):
    """Одна поездка в удалённый город и обратно допустима, если без неё заявка останется невыполненной, метания туда-обратно нет."""
    scenario = scenarios["yugo-vostok"]
    geo = Geo(scenario)
    plan = solver.plan(scenario, geo, PlanParams(time_limit_s=20))

    for route in plan.routes:
        if not route.stops:
            continue
        sequence = zone_sequence(geo, scenario, route)
        assert len(sequence) <= 3, f"{route.engineer_id} мечется между зонами: {sequence}"


def test_yugo_vostok_separates_the_remote_towns(scenarios):
    scenario = scenarios["yugo-vostok"]
    geo = Geo(scenario)
    assert len(set(geo.zones)) >= 2

    by_zone: dict[int, set[str]] = {}
    for order in scenario.orders:
        by_zone.setdefault(geo.zone(geo.node(order.id)), set()).add(order.district)

    remote = [districts for zone, districts in by_zone.items() if zone != zones.BASE_ZONE]
    assert any("Кашира" in districts for districts in remote)
    assert all("Царицыно" not in districts for districts in remote)
