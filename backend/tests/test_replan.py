"""Перепланирование после события (DESIGN.md §9, ТЗ §2.1.6)."""

from __future__ import annotations

import pytest

from planner.core import replan, solver
from planner.core.models import (
    CancelOrderEvent,
    EngineerUnavailableEvent,
    PlanParams,
    Priority,
    Skill,
    UrgentOrderEvent,
)
from planner.core.timeutil import hhmm_to_min
from planner.core.validate import Geo, evaluate
from planner.ingest import store
from tests.conftest import at_km, make_engineer, make_order, make_scenario

FAST = PlanParams(objective="min_engineers", time_limit_s=2)


@pytest.fixture
def day():
    """Восемь заявок на троих инженеров — хватает места для манёвра."""
    orders = [
        make_order("O1", 1, Skill.LOCAL, ("09:00", "11:00")),
        make_order("O2", 2, Skill.LOCAL, ("09:00", "11:00")),
        make_order("O3", 3, Skill.LOCAL, ("11:00", "13:00")),
        make_order("O4", 4, Skill.LOCAL, ("11:00", "13:00")),
        make_order("O5", 5, Skill.LOCAL, ("13:00", "16:00")),
        make_order("O6", 6, Skill.LOCAL, ("13:00", "16:00")),
        make_order("O7", 7, Skill.LOCAL, ("14:00", "17:00")),
        make_order("O8", 8, Skill.LOCAL, ("14:00", "17:00")),
    ]
    engineers = [make_engineer(f"E{i:02d}", [Skill.LOCAL, Skill.EMERGENCY]) for i in (1, 2, 3)]
    return make_scenario(orders, engineers)


@pytest.fixture
def day_plan(day):
    return solver.plan(day, Geo(day), FAST)


# ------------------------------------------------------------- заморозка


def test_freeze_locks_started_visits(day, day_plan):
    geo = Geo(day)
    at = hhmm_to_min("12:00")
    frozen = replan.freeze(geo, day_plan, at)

    for state in frozen.starts.values():
        for stop in state.locked_stops:
            assert hhmm_to_min(stop.arrival) <= at
            assert stop.locked is True
    assert frozen.locked_count == sum(len(s.locked_stops) for s in frozen.starts.values())


def test_freeze_returns_future_visits_to_the_pool(day, day_plan):
    geo = Geo(day)
    at = hhmm_to_min("12:00")
    frozen = replan.freeze(geo, day_plan, at)

    future = [
        stop.order_id
        for route in day_plan.routes
        for stop in route.stops
        if hhmm_to_min(stop.arrival) > at
    ]
    assert sorted(frozen.pool) == sorted(future + [u.order_id for u in day_plan.unassigned])


def test_freeze_sets_position_and_clock(day, day_plan):
    geo = Geo(day)
    frozen = replan.freeze(geo, day_plan, hhmm_to_min("12:00"))
    for engineer_id, state in frozen.starts.items():
        if state.locked_stops:
            last = state.locked_stops[-1]
            assert state.node == geo.node(last.order_id)
            assert state.available_min == hhmm_to_min(last.finish)
        else:
            engineer = geo.engineers[engineer_id]
            assert state.available_min >= engineer.shift_start_min


def test_unassigned_orders_get_another_chance(day, day_plan):
    frozen = replan.freeze(Geo(day), day_plan, hhmm_to_min("12:00"))
    for unassigned in day_plan.unassigned:
        assert unassigned.order_id in frozen.pool


# ----------------------------------------------------- срочная заявка


def test_urgent_order_is_added_and_scheduled(day, day_plan):
    scenario = day.model_copy(deep=True)
    lat, lon = at_km(3)
    order = replan.make_urgent_order(
        scenario, "авария", lat, lon, Skill.EMERGENCY, ("12:00", "20:00"), 60
    )
    event = UrgentOrderEvent(time="12:00", order=order)
    new_plan, diff = replan.replan(scenario, day_plan, event, Geo(scenario), FAST)

    assert order.id in {o.id for o in scenario.orders}
    assert order.id in new_plan.assignment, "срочную заявку обязаны поставить в план"
    assert order.id in diff.added
    assert new_plan.event == event
    assert new_plan.parent_plan_id == day_plan.id


def test_urgent_order_does_not_shift_engineers_start_points(day, day_plan):
    """Регрессия: добавление заявки сдвигает нумерацию узлов.

    Точки сценария идут как «заявки, затем офис, затем выездные базы».
    Срочная заявка дописывается в конец списка заявок, и офис съезжает
    на следующий индекс. Состояние заморозки, посчитанное до события,
    после этого указывало бы на новую заявку: инженер без начатых визитов
    начинал бы день из точки аварии, а не из офиса.
    """
    scenario = day.model_copy(deep=True)
    before = Geo(scenario)
    frozen = replan.freeze(before, day_plan, hhmm_to_min("09:00"))
    idle = [e_id for e_id, s in frozen.starts.items() if not s.locked_stops]
    assert idle, "к началу смены никто не должен быть в работе"

    lat, lon = at_km(3)
    order = replan.make_urgent_order(
        scenario, "авария", lat, lon, Skill.EMERGENCY, ("09:00", "20:00"), 60
    )
    after, _, _ = replan.apply_event(
        scenario, before, frozen, UrgentOrderEvent(time="09:00", order=order), hhmm_to_min("09:00")
    )
    replan.remap_starts(after, frozen)

    for engineer_id in idle:
        node = frozen.starts[engineer_id].node
        assert node == after.start_node(after.engineers[engineer_id])
        assert node != after.node(order.id), "инженер не должен стартовать из точки аварии"


def test_urgent_order_with_closed_window_is_rejected(day, day_plan):
    scenario = day.model_copy(deep=True)
    lat, lon = at_km(3)
    order = replan.make_urgent_order(
        scenario, "поздно", lat, lon, Skill.EMERGENCY, ("09:00", "10:00"), 60
    )
    with pytest.raises(replan.ReplanError, match="закрылось"):
        replan.replan(
            scenario, day_plan, UrgentOrderEvent(time="15:00", order=order), Geo(scenario), FAST
        )


def test_urgent_order_keeps_its_priority(day, day_plan):
    scenario = day.model_copy(deep=True)
    lat, lon = at_km(3)
    order = replan.make_urgent_order(
        scenario, "авария", lat, lon, Skill.EMERGENCY, ("12:00", "20:00"), 60
    )
    replan.replan(scenario, day_plan, UrgentOrderEvent(time="12:00", order=order), Geo(scenario), FAST)
    assert scenario.order(order.id).priority is Priority.URGENT


# ------------------------------------------------------------- отмена


def test_cancelled_order_disappears_from_the_plan(day, day_plan):
    target = next(
        stop.order_id
        for route in day_plan.routes
        for stop in route.stops
        if stop.arrival > "12:00"
    )
    scenario = day.model_copy(deep=True)
    new_plan, diff = replan.replan(
        scenario, day_plan, CancelOrderEvent(time="12:00", order_id=target), Geo(scenario), FAST
    )
    assert target not in new_plan.assignment
    assert target not in {u.order_id for u in new_plan.unassigned}
    assert target in diff.removed


def test_cancelling_a_started_visit_is_refused(day, day_plan):
    started = next(
        stop.order_id
        for route in day_plan.routes
        for stop in route.stops
        if stop.arrival <= "12:00"
    )
    scenario = day.model_copy(deep=True)
    with pytest.raises(replan.ReplanError, match="уже выполняется"):
        replan.replan(
            scenario,
            day_plan,
            CancelOrderEvent(time="12:00", order_id=started),
            Geo(scenario),
            FAST,
        )


def test_cancelling_unknown_order_is_refused(day, day_plan):
    scenario = day.model_copy(deep=True)
    with pytest.raises(replan.ReplanError, match="нет заявки"):
        replan.replan(
            scenario, day_plan, CancelOrderEvent(time="12:00", order_id="ZZZ"), Geo(scenario), FAST
        )


# ------------------------------------------------- недоступность инженера


def test_unavailable_engineer_gets_no_new_work(day, day_plan):
    victim = max(day_plan.routes, key=lambda r: len(r.stops)).engineer_id
    scenario = day.model_copy(deep=True)
    new_plan, _ = replan.replan(
        scenario,
        day_plan,
        EngineerUnavailableEvent(time="12:00", engineer_id=victim),
        Geo(scenario),
        FAST,
    )
    route = next((r for r in new_plan.routes if r.engineer_id == victim), None)
    if route is not None:
        assert all(stop.arrival <= "12:00" for stop in route.stops)


def test_unavailable_engineer_keeps_completed_work(day, day_plan):
    victim = max(day_plan.routes, key=lambda r: len(r.stops)).engineer_id
    done = [
        stop.order_id
        for route in day_plan.routes
        if route.engineer_id == victim
        for stop in route.stops
        if stop.arrival <= "12:00"
    ]
    scenario = day.model_copy(deep=True)
    new_plan, _ = replan.replan(
        scenario,
        day_plan,
        EngineerUnavailableEvent(time="12:00", engineer_id=victim),
        Geo(scenario),
        FAST,
    )
    for order_id in done:
        assert new_plan.assignment.get(order_id) == victim


def test_unavailable_engineer_stays_visible_in_the_plan(day, day_plan):
    """Ни одна заявка не должна пропасть: всё либо назначено, либо объяснено."""
    victim = max(day_plan.routes, key=lambda r: len(r.stops)).engineer_id
    scenario = day.model_copy(deep=True)
    new_plan, _ = replan.replan(
        scenario,
        day_plan,
        EngineerUnavailableEvent(time="12:00", engineer_id=victim),
        Geo(scenario),
        FAST,
    )
    covered = set(new_plan.assignment) | {u.order_id for u in new_plan.unassigned}
    assert covered == {o.id for o in scenario.orders}
    assert new_plan.metrics.assigned + new_plan.metrics.unassigned == len(scenario.orders)


def test_unknown_engineer_is_refused(day, day_plan):
    scenario = day.model_copy(deep=True)
    with pytest.raises(replan.ReplanError, match="нет инженера"):
        replan.replan(
            scenario,
            day_plan,
            EngineerUnavailableEvent(time="12:00", engineer_id="E99"),
            Geo(scenario),
            FAST,
        )


# --------------------------------------------------------------- общее


@pytest.mark.parametrize("hour", ["10:00", "12:00", "15:00"])
def test_new_plan_is_always_feasible(day, day_plan, hour):
    target = next(
        (
            stop.order_id
            for route in day_plan.routes
            for stop in route.stops
            if stop.arrival > hour
        ),
        None,
    )
    if target is None:
        pytest.skip("после этого часа визитов не осталось")
    scenario = day.model_copy(deep=True)
    geo = Geo(scenario)
    new_plan, _ = replan.replan(
        scenario, day_plan, CancelOrderEvent(time=hour, order_id=target), geo, FAST
    )
    frozen = replan.freeze(geo, day_plan, hhmm_to_min(hour))
    _, violations = evaluate(
        geo, {r.engineer_id: r.order_ids for r in new_plan.routes}
    )
    assert not violations


def test_completed_visits_never_move(day, day_plan):
    at = "12:00"
    before = {
        stop.order_id: (route.engineer_id, stop.start)
        for route in day_plan.routes
        for stop in route.stops
        if stop.arrival <= at
    }
    target = next(
        stop.order_id
        for route in day_plan.routes
        for stop in route.stops
        if stop.arrival > at
    )
    scenario = day.model_copy(deep=True)
    new_plan, _ = replan.replan(
        scenario, day_plan, CancelOrderEvent(time=at, order_id=target), Geo(scenario), FAST
    )
    after = {
        stop.order_id: (route.engineer_id, stop.start)
        for route in new_plan.routes
        for stop in route.stops
    }
    for order_id, value in before.items():
        assert after[order_id] == value, f"визит {order_id} был начат и не должен меняться"


def test_diff_summary_is_readable(day, day_plan):
    target = next(
        stop.order_id
        for route in day_plan.routes
        for stop in route.stops
        if stop.arrival > "12:00"
    )
    scenario = day.model_copy(deep=True)
    _, diff = replan.replan(
        scenario, day_plan, CancelOrderEvent(time="12:00", order_id=target), Geo(scenario), FAST
    )
    assert "Событие:" in diff.summary
    assert "Пробег" in diff.summary
    assert diff.before_plan_id == day_plan.id
    assert diff.metrics_before.assigned == day_plan.metrics.assigned


def test_replan_is_stable(day, day_plan):
    """Штраф за смену исполнителя не даёт плану рассыпаться из-за одного события."""
    target = next(
        stop.order_id
        for route in day_plan.routes
        for stop in route.stops
        if stop.arrival > "12:00"
    )
    scenario = day.model_copy(deep=True)
    _, diff = replan.replan(
        scenario, day_plan, CancelOrderEvent(time="12:00", order_id=target), Geo(scenario), FAST
    )
    moved = [c for c in diff.changed if c.from_engineer != c.to_engineer]
    assert len(moved) <= max(2, day_plan.metrics.assigned // 4)


# --------------------------------------------------- на реальных данных


def test_replan_on_real_region():
    scenarios = [s for s in store.load_all() if s.id == "vostok"]
    if not scenarios:
        pytest.skip("сценарии ещё не собраны")
    scenario = scenarios[0]
    geo = Geo(scenario)
    plan = solver.plan(scenario, geo, PlanParams(objective="min_engineers", time_limit_s=4))

    working = scenario.model_copy(deep=True)
    target = next(
        stop.order_id for route in plan.routes for stop in route.stops if stop.arrival > "13:00"
    )
    new_plan, diff = replan.replan(
        working,
        plan,
        CancelOrderEvent(time="13:00", order_id=target),
        Geo(working),
        PlanParams(objective="min_engineers", time_limit_s=4),
    )
    _, violations = evaluate(
        Geo(working), {r.engineer_id: r.order_ids for r in new_plan.routes}
    )
    assert not violations
    assert diff.locked_stops > 0
    assert new_plan.plan_explanation
