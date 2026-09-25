"""Геометрия маршрутов для карты (core/geometry.py)."""

from __future__ import annotations

import json

import pytest

from planner.core import geometry, solver
from planner.core.models import PlanParams, Point
from planner.core.validate import Geo

FAST = PlanParams(objective="min_engineers", time_limit_s=2)

UNREACHABLE = "http://127.0.0.1:1"


@pytest.fixture
def plan(toy, toy_geo):
    return solver.plan(toy, toy_geo, FAST)


def test_route_points_start_from_the_engineers_own_point(toy, toy_geo, plan):
    """Линия начинается там же, где начинается маршрут, у инженера, не у офиса."""
    route = next(r for r in plan.routes if r.stops)
    points = geometry.route_points(toy_geo, plan, route.engineer_id)

    engineer = toy_geo.engineers[route.engineer_id]
    assert points[0] == engineer.start.coords
    assert len(points) == len(route.stops) + 1
    for point, stop in zip(points[1:], route.stops):
        assert point == toy_geo.orders[stop.order_id].coords


def test_route_points_respect_a_remote_base(toy, plan):
    remote = toy.engineers[0].model_copy(
        update={"start": Point(address="выездная база", lat=55.9, lon=37.9)}
    )
    scenario = toy.model_copy(update={"engineers": [remote, *toy.engineers[1:]]})
    geo = Geo(scenario)
    rebuilt = solver.plan(scenario, geo, FAST)
    route = next((r for r in rebuilt.routes if r.engineer_id == remote.id and r.stops), None)
    if route is None:
        pytest.skip("этому инженеру не досталось заявок")
    assert geometry.route_points(geo, rebuilt, remote.id)[0] == (55.9, 37.9)


def test_engineer_without_stops_has_no_line(toy_geo, plan):
    idle = [r.engineer_id for r in plan.routes if not r.stops]
    for engineer_id in idle:
        assert geometry.route_points(toy_geo, plan, engineer_id) == []


def test_single_point_gives_no_line():
    line, error = geometry.fetch_line([(55.7, 37.6)], UNREACHABLE)
    assert line is None and error is None


def test_too_many_waypoints_are_refused():
    points = [(55.7 + i * 0.001, 37.6) for i in range(geometry.MAX_WAYPOINTS + 2)]
    line, error = geometry.fetch_line(points, UNREACHABLE)
    assert line is None
    assert "слишком много точек" in (error or "")


def test_unreachable_service_reports_an_error_instead_of_raising():
    line, error = geometry.fetch_line([(55.70, 37.60), (55.71, 37.62)], UNREACHABLE)
    assert line is None
    assert error


def test_cache_is_used_before_the_network(monkeypatch, tmp_path):
    """Повторный показ той же карты не должен снова дёргать сервис."""
    points = [(55.70, 37.60), (55.71, 37.62)]
    stored = [[55.70, 37.60], [55.705, 37.61], [55.71, 37.62]]

    path = tmp_path / "line.json"
    path.write_text(json.dumps(stored), encoding="utf-8")
    monkeypatch.setattr(geometry, "_cache_path", lambda _points: path)

    import httpx

    def refuse(*args, **kwargs):
        raise AssertionError("при попадании в кэш запрос делать не нужно")

    monkeypatch.setattr(httpx, "get", refuse)

    line, error = geometry.fetch_line(points, UNREACHABLE)
    assert line == stored
    assert error is None


def test_broken_cache_does_not_crash(monkeypatch, tmp_path):
    path = tmp_path / "line.json"
    path.write_text("не json", encoding="utf-8")
    monkeypatch.setattr(geometry, "_cache_path", lambda _points: path)
    line, error = geometry.fetch_line([(55.70, 37.60), (55.71, 37.62)], UNREACHABLE)
    assert line is None
    assert error


def test_build_degrades_gracefully(toy_geo, plan):
    """Недоступный маршрутизатор это прямые линии на карте, а не ошибка."""
    result = geometry.build(toy_geo, plan, UNREACHABLE)
    assert result.available is False
    assert result.routes == {}
    assert result.errors
    for route in plan.routes:
        if route.stops:
            assert len(result.legs[route.engineer_id]) == len(route.stops)
            points = geometry.route_points(toy_geo, plan, route.engineer_id)
            assert result.legs[route.engineer_id][0][0] == list(points[0])
            assert result.legs[route.engineer_id][-1][-1] == list(points[-1])


def test_split_legs_keeps_road_bends_and_stop_boundaries():
    points = [(55.7, 37.7), (55.7, 37.702), (55.7, 37.704)]
    line = [
        [55.7, 37.7], [55.701, 37.701], [55.7, 37.702],
        [55.702, 37.703], [55.7, 37.704],
    ]
    legs = geometry.split_legs(points, line)

    assert len(legs) == 2
    assert legs[0] == [[55.7, 37.7], [55.701, 37.701], [55.7, 37.702]]
    assert legs[1] == [[55.7, 37.702], [55.702, 37.703], [55.7, 37.704]]


def test_split_legs_falls_back_for_off_route_stop():
    points = [(55.7, 37.7), (56.0, 38.0), (55.7, 37.704)]
    line = [[55.7, 37.7], [55.701, 37.701], [55.7, 37.704]]
    legs = geometry.split_legs(points, line)

    assert legs[0] == [[55.7, 37.7], [56.0, 38.0]]
    assert legs[1] == [[56.0, 38.0], [55.7, 37.704]]


def test_build_reports_nothing_to_draw(toy, toy_geo):
    empty = solver.plan(toy, toy_geo, FAST, order_ids=[])
    result = geometry.build(toy_geo, empty, UNREACHABLE)
    assert result.available is False
    assert "нет маршрутов" in " ".join(result.errors)


def test_geometry_never_touches_the_plan(toy_geo, plan):
    """Оформление не имеет права менять расчёт."""
    before = plan.model_dump()
    geometry.build(toy_geo, plan, UNREACHABLE)
    assert plan.model_dump() == before


def test_coordinates_are_returned_in_map_order(monkeypatch, tmp_path):
    """OSRM отдаёт «долгота, широта»; карте нужен обратный порядок."""
    import httpx

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "code": "Ok",
                "routes": [{"geometry": {"coordinates": [[37.60, 55.70], [37.62, 55.71]]}}],
            }

    monkeypatch.setattr(geometry, "_cache_path", lambda _points: tmp_path / "x.json")
    monkeypatch.setattr(httpx, "get", lambda *a, **k: Response())

    line, error = geometry.fetch_line([(55.70, 37.60), (55.71, 37.62)], "http://osrm.local")
    assert error is None
    assert line == [[55.70, 37.60], [55.71, 37.62]]
