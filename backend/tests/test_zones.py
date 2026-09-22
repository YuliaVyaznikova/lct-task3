"""Разбиение участка на зоны и штраф за переходы между ними."""

from __future__ import annotations

import numpy as np
import pytest

from planner.core import zones
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
