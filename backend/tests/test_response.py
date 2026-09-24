"""Время реакции на аварию: от момента поступления до начала работ."""

from __future__ import annotations

import copy

import pytest

from planner.core import metrics, replan, solver
from planner.core.models import (
    GeocodeQuality,
    Order,
    PlanParams,
    Priority,
    Skill,
    UrgentOrderEvent,
)
from planner.core.timeutil import hhmm_to_min
from planner.core.validate import Geo
from planner.ingest import store

FAST = PlanParams(time_limit_s=5)


@pytest.fixture(scope="module")
def scenarios():
    data = {s.id: s for s in store.load_all()}
    if not data:
        pytest.skip("сценарии ещё не собраны")
    return data


def incident(scenario, order_id: str, reported: str, window=("12:30", "23:59")):
    anchor = scenario.orders[7]
    return Order(
        id=order_id,
        address=anchor.address,
        district=anchor.district,
        lat=anchor.lat,
        lon=anchor.lon,
        geocode_quality=GeocodeQuality.MANUAL,
        skill=Skill.EMERGENCY,
        work_type="Глобальная проблема",
        description="Авария",
        duration_min=80,
        window_start=window[0],
        window_end=window[1],
        priority=Priority.URGENT,
        attributes={"reported_at": reported} if reported else {},
    )


def test_response_is_measured_from_the_reported_time(scenarios):
    scenario = scenarios["yugo-vostok"].model_copy(deep=True)
    plan = solver.plan(scenario, Geo(scenario), PlanParams(time_limit_s=20))
    measured = metrics.response_times(scenario, plan.routes)

    assert measured, "на юго-востоке есть аварии с отметкой о поступлении"
    starts = {stop.order_id: stop.start for route in plan.routes for stop in route.stops}
    for order_id, minutes in measured.items():
        order = scenario.orders_by_id[order_id]
        expected = hhmm_to_min(starts[order_id]) - hhmm_to_min(order.attributes["reported_at"])
        assert minutes == expected


def test_orders_without_a_reported_time_are_not_counted(scenarios):
    scenario = scenarios["yugo-vostok"].model_copy(deep=True)
    for order in scenario.orders:
        order.attributes.pop("reported_at", None)
    plan = solver.plan(scenario, Geo(scenario), FAST)

    assert metrics.response_times(scenario, plan.routes) == {}
    assert plan.metrics.response_measured == 0


def test_ordinary_orders_never_count_as_incidents(scenarios):
    scenario = scenarios["demo"].model_copy(deep=True)
    for order in scenario.orders:
        if order.priority is not Priority.URGENT:
            order.attributes["reported_at"] = "09:00"
    plan = solver.plan(scenario, Geo(scenario), FAST)

    measured = metrics.response_times(scenario, plan.routes)
    assert all(
        scenario.orders_by_id[order_id].priority is Priority.URGENT for order_id in measured
    )


def test_summary_counts_those_over_the_two_hour_norm(scenarios):
    scenario = scenarios["yugo-vostok"].model_copy(deep=True)
    plan = solver.plan(scenario, Geo(scenario), PlanParams(time_limit_s=20))
    measured = sorted(metrics.response_times(scenario, plan.routes).values())
    m = plan.metrics

    assert m.response_measured == len(measured)
    assert m.response_max_min == measured[-1]
    assert m.response_over_norm == sum(1 for v in measured if v > metrics.RESPONSE_NORM_MIN)


def test_incident_arriving_during_the_day_gets_its_reported_time(scenarios):
    scenario = scenarios["demo"].model_copy(deep=True)
    base = solver.plan(scenario, Geo(scenario), FAST)
    working = copy.deepcopy(scenario)
    order = incident(scenario, "SOS-960", reported="")

    plan, _ = replan.replan(
        working, base, UrgentOrderEvent(time="12:30", order=order), params=FAST
    )

    added = next(item for item in working.orders if item.id == "SOS-960")
    assert added.attributes["reported_at"] == "12:30", "момент поступления это время события"

    started = {stop.order_id: stop.start for route in plan.routes for stop in route.stops}
    if "SOS-960" in started:
        assert plan.metrics.response_measured >= 1
        assert plan.metrics.response_max_min == hhmm_to_min(started["SOS-960"]) - hhmm_to_min("12:30")


def test_existing_reported_time_is_not_overwritten(scenarios):
    scenario = scenarios["demo"].model_copy(deep=True)
    base = solver.plan(scenario, Geo(scenario), FAST)
    working = copy.deepcopy(scenario)
    order = incident(scenario, "SOS-961", reported="11:00")

    replan.replan(working, base, UrgentOrderEvent(time="12:30", order=order), params=FAST)

    added = next(item for item in working.orders if item.id == "SOS-961")
    assert added.attributes["reported_at"] == "11:00"
