"""Валидатор — единственный источник истины о допустимости плана (DESIGN.md §8)."""

from __future__ import annotations

import pytest

from planner.core.models import Skill, Transport
from planner.core.timeutil import hhmm_to_min
from planner.core.validate import (
    Geo,
    StartState,
    best_insertion,
    can_append,
    check_static,
    evaluate,
    evaluate_route,
    first_blocking_violation,
)
from tests.conftest import make_engineer, make_order, make_scenario


def codes(violations):
    return sorted(v.code for v in violations)


# ------------------------------------------------------- арифметика маршрута


def test_times_are_chained(toy_geo):
    engineer = toy_geo.engineers["E03"]
    route, violations = evaluate_route(toy_geo, engineer, ["A", "B"])
    assert not violations
    assert [s.order_id for s in route.stops] == ["A", "B"]
    assert [s.seq for s in route.stops] == [1, 2]
    # Первая заявка: выезд в 09:00, но начать раньше окна нельзя.
    first, second = route.stops
    assert first.start == "10:00"
    assert first.wait_min > 0
    assert first.finish == "10:30"
    # Вторая начинается не раньше, чем закончилась первая плюс дорога.
    assert hhmm_to_min(second.arrival) == hhmm_to_min(first.finish) + second.travel_min
    assert route.end_time == second.finish


def test_totals_match_stops(toy_geo):
    route, _ = evaluate_route(toy_geo, toy_geo.engineers["E03"], ["A", "B"])
    assert route.work_min == 60
    assert route.travel_min == sum(s.travel_min for s in route.stops)
    assert route.wait_min == sum(s.wait_min for s in route.stops)
    assert route.distance_km == pytest.approx(sum(s.travel_km for s in route.stops), abs=0.02)


def test_arriving_early_waits_and_never_starts_before_window(toy_geo):
    """Приехать раньше окна можно, начать работу — нет (Q&A, блок 5)."""
    route, violations = evaluate_route(toy_geo, toy_geo.engineers["E03"], ["A"])
    assert not violations
    stop = route.stops[0]
    assert hhmm_to_min(stop.arrival) < hhmm_to_min(stop.start)
    assert stop.start == "10:00"
    assert stop.wait_min == hhmm_to_min(stop.start) - hhmm_to_min(stop.arrival)


def test_finish_may_leave_the_window(toy_geo):
    """Обязательство — начать внутри окна; окончание за его пределами допустимо."""
    order = make_order("X", 1, Skill.LOCAL, ("10:00", "10:30"), duration=120)
    scenario = make_scenario([order], [make_engineer("E01", [Skill.LOCAL])])
    route, violations = evaluate_route(Geo(scenario), scenario.engineers[0], ["X"])
    assert not violations
    assert route.stops[0].finish == "12:00"


# ------------------------------------------------------------- нарушения


def test_missing_skill_is_reported(toy_geo):
    _, violations = evaluate_route(toy_geo, toy_geo.engineers["E03"], ["C"])
    assert "NO_SKILL" in codes(violations)


def test_wrong_transport_is_reported(toy_geo):
    """У заявки F требуется автомобиль, у E01 — пешком."""
    _, violations = evaluate_route(toy_geo, toy_geo.engineers["E01"], ["F"])
    assert "NO_TRANSPORT" in codes(violations)


def test_late_arrival_breaks_window(toy_geo):
    """E01 ходит пешком: до 5-й точки он не успеет к концу окна 12:00."""
    _, violations = evaluate_route(toy_geo, toy_geo.engineers["E01"], ["C", "A"])
    assert "WINDOW" in codes(violations)


def test_work_must_fit_into_shift():
    order = make_order("X", 1, Skill.LOCAL, ("17:00", "17:30"), duration=120)
    scenario = make_scenario([order], [make_engineer("E01", [Skill.LOCAL], shift=("09:00", "18:00"))])
    _, violations = evaluate_route(Geo(scenario), scenario.engineers[0], ["X"])
    assert "SHIFT" in codes(violations)


def test_duplicate_assignment_is_reported(toy_geo):
    _, violations = evaluate(toy_geo, {"E01": ["A"], "E03": ["A"]})
    assert "DUPLICATE" in codes(violations)


def test_unknown_ids_are_reported(toy_geo):
    _, violations = evaluate(toy_geo, {"E99": ["A"]})
    assert "NO_ENGINEER" in codes(violations)
    _, violations = evaluate(toy_geo, {"E01": ["ZZZ"]})
    assert "NO_ORDER" in codes(violations)


def test_valid_plan_has_no_violations(toy_geo):
    routes, violations = evaluate(toy_geo, {"E03": ["A", "B"], "E02": ["E"]})
    assert not violations
    assert {r.engineer_id for r in routes} == {"E02", "E03"}


def test_routes_are_ordered_like_the_directory(toy_geo):
    routes, _ = evaluate(toy_geo, {"E03": ["A"], "E01": ["B"]})
    assert [r.engineer_id for r in routes] == ["E01", "E03"]


# --------------------------------------------------------------- вставки


def test_can_append_respects_constraints(toy_geo):
    assert can_append(toy_geo, toy_geo.engineers["E03"], [], "A")
    assert not can_append(toy_geo, toy_geo.engineers["E03"], [], "C")  # нет навыка
    assert not can_append(toy_geo, toy_geo.engineers["E01"], [], "F")  # не тот транспорт


def test_best_insertion_finds_cheapest_position(toy_geo):
    engineer = toy_geo.engineers["E03"]
    found = best_insertion(toy_geo, engineer, ["A", "F"], "B")
    assert found is not None
    position, delta = found
    assert position == 1, "B лежит между A и F — вставка в середину дешевле краёв"
    assert delta >= 0


def test_best_insertion_returns_none_when_impossible(toy_geo):
    assert best_insertion(toy_geo, toy_geo.engineers["E03"], [], "C") is None


def test_first_blocking_violation_explains_the_obstacle(toy_geo):
    blocking = first_blocking_violation(toy_geo, toy_geo.engineers["E03"], [], "C")
    assert blocking is not None and blocking.code == "NO_SKILL"

    blocking = first_blocking_violation(toy_geo, toy_geo.engineers["E01"], [], "F")
    assert blocking is not None and blocking.code == "NO_TRANSPORT"

    assert first_blocking_violation(toy_geo, toy_geo.engineers["E03"], [], "A") is None


# ------------------------------------------------------- старт не из офиса


def test_start_state_shifts_the_whole_route(toy_geo):
    """При перепланировании инженер стартует из точки последней заявки."""
    late = StartState(node=toy_geo.node("E"), available_min=hhmm_to_min("13:00"))
    route, violations = evaluate_route(toy_geo, toy_geo.engineers["E03"], ["F"], late)
    assert not violations
    assert hhmm_to_min(route.stops[0].arrival) >= hhmm_to_min("13:00")


def test_locked_stops_are_preserved(toy_geo):
    base, _ = evaluate_route(toy_geo, toy_geo.engineers["E03"], ["A"])
    locked = base.stops[0].model_copy(update={"locked": True})
    start = StartState(
        node=toy_geo.node("A"),
        available_min=hhmm_to_min(locked.finish),
        locked_stops=[locked],
        distance_km=base.distance_km,
        travel_min=base.travel_min,
        work_min=base.work_min,
    )
    route, violations = evaluate_route(toy_geo, toy_geo.engineers["E03"], ["F"], start)
    assert not violations
    assert [s.order_id for s in route.stops] == ["A", "F"]
    assert route.stops[0].locked is True
    assert route.work_min == base.work_min + 30


# --------------------------------------------------------------- прочее


def test_geo_requires_coordinates():
    order = make_order("X", 1)
    order.lat = order.lon = None
    scenario = make_scenario([order], [make_engineer("E01")])
    with pytest.raises(ValueError, match="координат"):
        Geo(scenario)


def test_check_static_passes_for_suitable_engineer(toy_geo):
    assert check_static(toy_geo.engineers["E02"], toy_geo.orders["E"]) is None
    assert check_static(toy_geo.engineers["E03"], toy_geo.orders["F"]) is None


def test_engineer_cannot_leave_before_shift(toy_geo):
    engineer = make_engineer("LATE", [Skill.LOCAL], Transport.CAR, ("14:00", "23:00"))
    scenario = make_scenario(list(toy_geo.scenario.orders), [engineer])
    route, _ = evaluate_route(Geo(scenario), engineer, ["A"])
    assert hhmm_to_min(route.stops[0].arrival) >= hhmm_to_min("14:00")
