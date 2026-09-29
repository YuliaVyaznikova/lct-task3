"""Вариант с ровной загрузкой инженеров."""

from __future__ import annotations

import pytest

from planner.core import solver
from planner.core.models import PlanParams
from planner.core.validate import Geo
from tests.conftest import make_engineer, make_order, make_scenario

pytestmark = pytest.mark.slow

QUICK = PlanParams(time_limit_s=3, no_improve_s=2)


def cluster():
    orders = [make_order(f"Z{i}", 5 + 0.1 * i, duration=60) for i in range(6)]
    return make_scenario(orders, [make_engineer("A"), make_engineer("B")])


def visits(plan) -> list[int]:
    return sorted(len(route.stops) for route in plan.routes)


def test_distance_plan_loads_one_engineer():
    scenario = cluster()
    plan = solver.plan(scenario, Geo(scenario), QUICK.model_copy(update={"objective": "min_distance"}))

    assert plan.metrics.assigned == 6
    assert visits(plan) == [0, 6], "без выравнивания дешевле отдать всё одному"


def test_balance_splits_the_work_without_losing_orders():
    scenario = cluster()
    geo = Geo(scenario)
    start = solver.plan(scenario, geo, QUICK.model_copy(update={"objective": "min_distance"}))

    balanced = solver.balance(scenario, geo, QUICK, start)

    assert balanced.metrics.assigned == start.metrics.assigned
    assert visits(balanced) == [3, 3]
    assert balanced.params.objective == "balanced"
