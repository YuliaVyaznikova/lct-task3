"""Базовый вариант планирования для сравнения."""

from __future__ import annotations

from planner.core import metrics as metrics_module
from planner.core import reasons
from planner.core.models import Plan, PlanParams, Scenario
from planner.core.validate import Geo, can_append, evaluate


def plan(
    scenario: Scenario,
    geo: Geo | None = None,
    plan_id: str = "baseline",
    params: PlanParams | None = None,
) -> Plan:
    geo = geo or Geo(scenario)
    assignment: dict[str, list[str]] = {engineer.id: [] for engineer in scenario.engineers}
    unassigned_ids: list[str] = []

    for order in scenario.orders:
        for engineer in scenario.engineers:
            if can_append(geo, engineer, assignment[engineer.id], order.id):
                assignment[engineer.id].append(order.id)
                break
        else:
            unassigned_ids.append(order.id)

    routes, violations = evaluate(geo, assignment)
    if violations:
        raise AssertionError(
            "базовый вариант построил недопустимый план: "
            + "; ".join(v.text for v in violations[:3])
        )

    unassigned = reasons.diagnose_all(geo, unassigned_ids, routes)
    result = Plan(
        id=plan_id,
        scenario_id=scenario.id,
        kind="baseline",
        params=params or PlanParams(objective="min_engineers"),
        planned_from=min(
            (e.shift_start for e in scenario.engineers), default="00:00"
        ),
        routes=routes,
        unassigned=unassigned,
    )
    result.metrics = metrics_module.compute(
        scenario, routes, unassigned, reasons.extra_engineers_needed(geo, unassigned)
    )
    result.plan_explanation = (
        "Базовый вариант: заявки в порядке поступления, "
        "каждая первому подходящему инженеру, без оптимизации маршрута."
    )
    return result
