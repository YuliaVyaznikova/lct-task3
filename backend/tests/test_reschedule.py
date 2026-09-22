"""Сдвиг обещанного клиенту времени при перепланировании (эксперты, п.2)."""

from __future__ import annotations

import pytest

from planner.core import replan, solver
from planner.core.models import CancelOrderEvent, PlanParams, Skill
from planner.core.validate import Geo, evaluate, evaluate_route
from planner.ingest import store
from tests.conftest import make_engineer, make_order, make_scenario

FAST = PlanParams(objective="min_engineers", time_limit_s=3)


def tight_day():
    """Четыре заявки в одно часовое окно на одного инженера влезает одна."""
    window = ("10:00", "11:00")
    orders = [
        make_order(f"O{i}", i * 2.0, Skill.LOCAL, window, duration=50) for i in range(1, 5)
    ]
    return make_scenario(orders, [make_engineer("E01", [Skill.LOCAL], shift=("09:00", "20:00"))])


def test_reschedule_is_off_by_default():
    assert PlanParams().allow_reschedule is False


def test_window_is_hard_on_the_first_plan():
    """Первичный расчёт не имеет права двигать обещанное клиенту время."""
    scenario = tight_day()
    geo = Geo(scenario)
    plan = solver.plan(scenario, geo, PlanParams(time_limit_s=3, allow_reschedule=True))

    orders = scenario.orders_by_id
    for route in plan.routes:
        for stop in route.stops:
            assert stop.start <= orders[stop.order_id].window_end
            assert stop.late_min == 0
    assert plan.metrics.rescheduled == 0


def test_validator_reports_a_late_start_as_a_violation_by_default():
    scenario = tight_day()
    geo = Geo(scenario)
    _, violations = evaluate_route(geo, scenario.engineers[0], ["O1", "O2"])
    assert any(v.code == "WINDOW" for v in violations)


def test_validator_records_lateness_instead_when_allowed():
    scenario = tight_day()
    geo = Geo(scenario)
    route, violations = evaluate_route(
        geo, scenario.engineers[0], ["O1", "O2"], allow_late=True
    )
    assert not violations, "с разрешённым переносом опоздание не нарушение"
    late = [stop for stop in route.stops if stop.late_min > 0]
    assert late, "но оно обязано быть зафиксировано"
    orders = scenario.orders_by_id
    for stop in late:
        expected = replan.hhmm_to_min(stop.start) - orders[stop.order_id].window_end_min
        assert stop.late_min == expected


def test_shift_end_stays_hard_even_with_reschedule():
    """За инженера решать нельзя: конец смены не двигается ни при каких условиях."""
    order = make_order("X", 1, Skill.LOCAL, ("17:00", "17:30"), duration=120)
    scenario = make_scenario([order], [make_engineer("E01", [Skill.LOCAL], shift=("09:00", "18:00"))])
    _, violations = evaluate_route(
        Geo(scenario), scenario.engineers[0], ["X"], allow_late=True
    )
    assert any(v.code == "SHIFT" for v in violations)


@pytest.fixture(scope="module")
def demo():
    scenarios = [s for s in store.load_all() if s.id == "demo"]
    if not scenarios:
        pytest.skip("демо-сценарий не собран")
    return scenarios[0]


def _replan(demo, allow: bool):
    scenario = demo.model_copy(deep=True)
    geo = Geo(scenario)
    base = solver.plan(scenario, geo, PlanParams(time_limit_s=6))
    target = next(
        stop.order_id
        for route in base.routes
        for stop in route.stops
        if stop.arrival > "12:00"
    )
    working = demo.model_copy(deep=True)
    return working, replan.replan(
        working,
        base,
        CancelOrderEvent(time="12:00", order_id=target),
        Geo(working),
        PlanParams(time_limit_s=6, allow_reschedule=allow),
    )


def test_reschedule_lets_the_plan_cover_more(demo):
    """Смысл послабления: приехать позже лучше, чем не приехать вовсе."""
    _, (strict, _) = _replan(demo, allow=False)
    _, (loose, _) = _replan(demo, allow=True)
    assert loose.metrics.assigned >= strict.metrics.assigned
    assert strict.metrics.rescheduled == 0


def test_rescheduled_visits_are_marked_and_counted(demo):
    working, (plan, _) = _replan(demo, allow=True)
    late = [stop for route in plan.routes for stop in route.stops if stop.late_min > 0]
    assert len(late) == plan.metrics.rescheduled
    orders = working.orders_by_id
    for stop in late:
        assert stop.start > orders[stop.order_id].window_end


def test_plan_stays_valid_under_its_own_policy(demo):
    working, (plan, _) = _replan(demo, allow=True)
    _, violations = evaluate(
        Geo(working),
        {route.engineer_id: route.order_ids for route in plan.routes},
        allow_late=True,
    )
    assert not violations


def test_summary_tells_support_to_call(demo):
    _, (plan, diff) = _replan(demo, allow=True)
    if plan.metrics.rescheduled == 0:
        pytest.skip("на этом событии переносить ничего не пришлось")
    assert "поддержки" in diff.summary
    assert "предупредить" in diff.summary
