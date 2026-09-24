"""Заявка, поступившая в течение дня, не обязана быть аварией."""

from __future__ import annotations

import copy

import pytest

from planner.core import replan, solver
from planner.core.models import (
    GeocodeQuality,
    NewOrderEvent,
    Order,
    PlanParams,
    Priority,
    Skill,
    UrgentOrderEvent,
)
from planner.core.validate import Geo
from planner.ingest import normatives, store

FAST = PlanParams(time_limit_s=5)


@pytest.fixture(scope="module")
def demo():
    scenarios = {s.id: s for s in store.load_all()}
    if "demo" not in scenarios:
        pytest.skip("демо-сценарий ещё не собран")
    return scenarios["demo"]


@pytest.fixture(scope="module")
def base_plan(demo):
    return solver.plan(demo, Geo(demo), FAST)


def order_like(scenario, order_id: str, skill: Skill, priority: Priority, window, duration=70):
    anchor = scenario.orders[5]
    return Order(
        id=order_id,
        address=anchor.address,
        district=anchor.district,
        lat=anchor.lat,
        lon=anchor.lon,
        geocode_quality=GeocodeQuality.MANUAL,
        skill=skill,
        work_type="Подключение" if skill is Skill.CONNECTION else "Глобальная проблема",
        description="проверка",
        duration_min=duration,
        window_start=window[0],
        window_end=window[1],
        priority=priority,
    )


def apply(demo, base_plan, event):
    working = copy.deepcopy(demo)
    plan, diff = replan.replan(working, base_plan, event, params=FAST)
    return plan, diff, working


def test_new_order_keeps_its_normal_priority(demo, base_plan):
    order = order_like(demo, "NEW-801", Skill.CONNECTION, Priority.NORMAL, ("16:00", "18:00"))
    plan, _, working = apply(demo, base_plan, NewOrderEvent(time="12:30", order=order))

    added = next(item for item in working.orders if item.id == "NEW-801")
    assert added.priority is Priority.NORMAL, "обычная заявка не должна становиться аварией"

    known = {stop.order_id for route in plan.routes for stop in route.stops}
    known |= {item.order_id for item in plan.unassigned}
    assert "NEW-801" in known


def test_new_order_is_called_new_not_urgent(demo, base_plan):
    order = order_like(demo, "NEW-802", Skill.CONNECTION, Priority.NORMAL, ("16:00", "18:00"))
    _, diff, _ = apply(demo, base_plan, NewOrderEvent(time="12:30", order=order))

    assert "новая заявка" in diff.summary
    assert "срочная заявка" not in diff.summary


def test_urgent_event_still_says_urgent(demo, base_plan):
    order = order_like(demo, "SOS-803", Skill.EMERGENCY, Priority.URGENT, ("12:30", "23:59"), 80)
    _, diff, _ = apply(demo, base_plan, UrgentOrderEvent(time="12:30", order=order))

    assert "срочная заявка" in diff.summary


def test_legacy_urgent_event_upgrades_priority(demo, base_plan):
    """Старый тип события помечает заявку срочной, даже если прислали обычную."""
    order = order_like(demo, "SOS-804", Skill.EMERGENCY, Priority.NORMAL, ("12:30", "23:59"), 80)
    _, diff, _ = apply(demo, base_plan, UrgentOrderEvent(time="12:30", order=order))

    assert "срочная заявка" in diff.summary


def test_new_order_does_not_move_orders_between_engineers(demo, base_plan):
    order = order_like(demo, "NEW-805", Skill.CONNECTION, Priority.NORMAL, ("16:00", "18:00"))
    _, diff, _ = apply(demo, base_plan, NewOrderEvent(time="12:30", order=order))

    moved = [change for change in diff.changed if change.from_engineer != change.to_engineer]
    assert not moved, f"обычная заявка перетасовала план: {moved}"


def test_emergency_is_allowed_to_rebuild_more_than_a_normal_order(demo, base_plan):
    normal = NewOrderEvent(
        time="12:30",
        order=order_like(demo, "NEW-806", Skill.CONNECTION, Priority.NORMAL, ("16:00", "18:00")),
    )
    urgent = NewOrderEvent(
        time="12:30",
        order=order_like(demo, "SOS-807", Skill.EMERGENCY, Priority.URGENT, ("12:30", "23:59"), 80),
    )

    assert replan._stability_for(normal) > replan._stability_for(urgent)


def test_work_types_reference_offers_regular_work():
    items = normatives.work_types()
    regular = [item for item in items if item["priority"] == "normal"]

    assert len(regular) >= 3
    assert all(item["duration_min"] > 0 for item in regular)
    assert {"Подключение", "Локальная заявка"} <= {item["work_type"] for item in regular}
