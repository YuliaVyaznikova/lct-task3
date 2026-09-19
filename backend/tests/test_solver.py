"""Оптимизатор на OR-Tools (DESIGN.md §6)."""

from __future__ import annotations

import pytest

from planner.core import baseline, metrics, solver
from planner.core.models import PlanParams, Priority, Skill, Transport
from planner.core.validate import Geo, evaluate
from planner.ingest import store
from tests.conftest import make_engineer, make_order, make_scenario

FAST = PlanParams(objective="min_engineers", time_limit_s=2)


def test_assigns_everything_it_can(toy, toy_geo):
    plan = solver.plan(toy, toy_geo, FAST)
    assert plan.metrics.assigned >= 5, "на игрушечном сценарии почти всё выполнимо"
    assert plan.metrics.assigned + plan.metrics.unassigned == len(toy.orders)


def test_result_is_always_feasible(toy, toy_geo):
    plan = solver.plan(toy, toy_geo, FAST)
    _, violations = evaluate(toy_geo, {r.engineer_id: r.order_ids for r in plan.routes})
    assert not violations


def test_unique_skill_goes_to_its_only_owner():
    orders = [make_order("E", 2, Skill.EMERGENCY, ("10:00", "16:00"), duration=80)]
    engineers = [
        make_engineer("E01", [Skill.LOCAL]),
        make_engineer("E02", [Skill.EMERGENCY]),
        make_engineer("E03", [Skill.CONNECTION]),
    ]
    plan = solver.plan(make_scenario(orders, engineers), params=FAST)
    assert plan.assignment == {"E": "E02"}


def test_required_transport_is_respected():
    orders = [make_order("F", 2, required_transport=Transport.CAR)]
    engineers = [
        make_engineer("E01", [Skill.LOCAL], Transport.FOOT),
        make_engineer("E02", [Skill.LOCAL], Transport.BIKE),
        make_engineer("E03", [Skill.LOCAL], Transport.CAR),
    ]
    plan = solver.plan(make_scenario(orders, engineers), params=FAST)
    assert plan.assignment == {"F": "E03"}


def test_time_windows_are_respected(toy, toy_geo):
    plan = solver.plan(toy, toy_geo, FAST)
    orders = toy.orders_by_id
    for route in plan.routes:
        for stop in route.stops:
            order = orders[stop.order_id]
            assert order.window_start <= stop.start <= order.window_end


def test_shift_is_respected(toy, toy_geo):
    plan = solver.plan(toy, toy_geo, FAST)
    engineers = toy.engineers_by_id
    for route in plan.routes:
        if route.stops:
            assert route.end_time <= engineers[route.engineer_id].shift_end


def test_impossible_order_is_dropped_with_a_reason():
    """Навыка нет ни у кого: заявка обязана попасть в неназначенные с причиной."""
    orders = [make_order("A", 1, Skill.LOCAL), make_order("X", 1, Skill.EMERGENCY, duration=80)]
    plan = solver.plan(make_scenario(orders, [make_engineer("E01", [Skill.LOCAL])]), params=FAST)
    assert plan.assignment == {"A": "E01"}
    assert [u.order_id for u in plan.unassigned] == ["X"]
    assert plan.unassigned[0].reason


def test_urgent_orders_are_never_dropped_for_normal_ones():
    """Штраф за пропуск срочной на порядок выше — она вытесняет обычную."""
    window = ("10:00", "11:00")
    orders = [
        make_order("N1", 1, Skill.LOCAL, window, duration=55),
        make_order("N2", 9, Skill.LOCAL, window, duration=55),
        make_order("U", 18, Skill.LOCAL, window, duration=55, priority=Priority.URGENT),
    ]
    plan = solver.plan(make_scenario(orders, [make_engineer("E01")]), params=FAST)
    assert "U" in plan.assignment, "срочная заявка должна вытеснить обычную"
    assert plan.metrics.urgent_assigned == 1


def test_urgent_order_is_scheduled_early():
    """Аварию с окном на целые сутки нужно выполнять как можно раньше (Q&A, блок 3)."""
    orders = [
        make_order("U", 1, Skill.EMERGENCY, ("00:01", "23:59"), duration=80, priority=Priority.URGENT),
        make_order("N", 2, Skill.LOCAL, ("09:00", "18:00")),
    ]
    engineers = [make_engineer("E01", [Skill.LOCAL, Skill.EMERGENCY])]
    plan = solver.plan(make_scenario(orders, engineers), params=FAST)
    urgent_stop = next(s for r in plan.routes for s in r.stops if s.order_id == "U")
    assert urgent_stop.start <= "10:30"


def test_min_engineers_uses_fewer_people_than_min_distance():
    """Классический размен: меньше людей ценой лишних километров."""
    orders = [make_order(f"O{i}", i * 1.5, Skill.LOCAL, ("09:00", "18:00")) for i in range(1, 9)]
    engineers = [make_engineer(f"E{i:02d}") for i in range(1, 7)]
    scenario = make_scenario(orders, engineers)
    geo = Geo(scenario)

    few = solver.plan(scenario, geo, PlanParams(objective="min_engineers", time_limit_s=3))
    short = solver.plan(scenario, geo, PlanParams(objective="min_distance", time_limit_s=3))
    assert few.metrics.assigned == short.metrics.assigned == len(orders)
    assert few.metrics.engineers_used <= short.metrics.engineers_used


def test_auto_objective_picks_the_better_plan():
    orders = [make_order(f"O{i}", i * 1.5, Skill.LOCAL, ("09:00", "18:00")) for i in range(1, 9)]
    engineers = [make_engineer(f"E{i:02d}") for i in range(1, 7)]
    scenario = make_scenario(orders, engineers)
    geo = Geo(scenario)

    auto = solver.plan(scenario, geo, PlanParams(objective="auto", time_limit_s=6))
    for objective in ("min_engineers", "min_distance"):
        single = solver.plan(scenario, geo, PlanParams(objective=objective, time_limit_s=3))
        assert not metrics.is_better(single.metrics, auto.metrics), objective
    assert auto.params.objective in ("min_engineers", "min_distance")


def test_beats_the_baseline(toy, toy_geo):
    ours = solver.plan(toy, toy_geo, FAST)
    base = baseline.plan(toy, toy_geo)
    assert not metrics.is_better(base.metrics, ours.metrics)


def test_every_order_is_accounted_for(toy, toy_geo):
    plan = solver.plan(toy, toy_geo, FAST)
    covered = set(plan.assignment) | {u.order_id for u in plan.unassigned}
    assert covered == {o.id for o in toy.orders}


def test_plan_metadata_is_filled(toy, toy_geo):
    plan = solver.plan(toy, toy_geo, FAST, plan_id="p1")
    assert plan.id == "p1"
    assert plan.kind == "optimized"
    assert plan.scenario_id == toy.id
    assert plan.planned_from == min(e.shift_start for e in toy.engineers)


def test_lunch_break_option_keeps_the_plan_valid(toy, toy_geo):
    """Обед — необязательная настройка (Q&A, блок 5): план обязан остаться допустимым."""
    with_lunch = solver.plan(toy, toy_geo, PlanParams(objective="min_engineers", time_limit_s=2, lunch=True))
    _, violations = evaluate(toy_geo, {r.engineer_id: r.order_ids for r in with_lunch.routes})
    assert not violations
    assert with_lunch.params.lunch is True


def test_lunch_break_costs_capacity_but_is_not_default():
    """Перерыв отнимает мощность, поэтому по умолчанию выключен."""
    assert PlanParams().lunch is False

    orders = [
        make_order(f"O{i}", i * 0.8, Skill.LOCAL, ("12:00", "16:00"), duration=60)
        for i in range(1, 8)
    ]
    scenario = make_scenario(orders, [make_engineer("E01", [Skill.LOCAL])])
    geo = Geo(scenario)
    without = solver.plan(scenario, geo, PlanParams(objective="min_engineers", time_limit_s=3))
    with_break = solver.plan(
        scenario, geo, PlanParams(objective="min_engineers", time_limit_s=3, lunch=True)
    )
    assert with_break.metrics.assigned <= without.metrics.assigned


def test_empty_pool_is_handled(toy, toy_geo):
    plan = solver.plan(toy, toy_geo, FAST, order_ids=[])
    assert plan.metrics.assigned == 0
    assert plan.metrics.engineers_used == 0


# ------------------------------------------------- на реальных сценариях


@pytest.fixture(scope="module")
def real():
    data = [s for s in store.load_all() if s.engineers]
    if not data:
        pytest.skip("сценарии ещё не собраны")
    return data


@pytest.mark.parametrize("region", ["vostok", "yugo-vostok", "yugocentr"])
def test_real_region_is_solved_and_valid(real, region):
    scenario = next(s for s in real if s.id == region)
    geo = Geo(scenario)
    plan = solver.plan(scenario, geo, PlanParams(objective="min_engineers", time_limit_s=5))
    _, violations = evaluate(geo, {r.engineer_id: r.order_ids for r in plan.routes})
    assert not violations
    assert plan.metrics.assigned > 0


@pytest.mark.parametrize("region", ["vostok", "yugo-vostok", "yugocentr"])
def test_beats_baseline_on_real_data(real, region):
    """Главное обещание решения: на тех же данных мы не хуже жадного варианта."""
    scenario = next(s for s in real if s.id == region)
    geo = Geo(scenario)
    ours = solver.plan(scenario, geo, PlanParams(objective="min_engineers", time_limit_s=5))
    base = baseline.plan(scenario, geo)
    assert ours.metrics.assigned > base.metrics.assigned
    assert ours.metrics.distance_per_order_km < base.metrics.distance_per_order_km
