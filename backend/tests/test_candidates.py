"""Варианты ручного переназначения и их прогноз."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from planner.api import lookup, manual
from planner.api.schemas import ManualRequest
from planner.api.candidates import list_candidates
from planner.api.store import PlanRecord
from planner.core.models import Plan, Skill
from planner.core.validate import Geo, evaluate, evaluate_route

from .conftest import make_engineer, make_order, make_scenario


@pytest.fixture
def candidate_plan():
    scenario = make_scenario(
        [make_order("A", 1), make_order("B", 2), make_order("C", 3, Skill.CONNECTION)],
        [
            make_engineer("E1"),
            make_engineer("E2", [Skill.LOCAL, Skill.CONNECTION]),
            make_engineer("E3", [Skill.CONNECTION]),
        ],
    )
    geo = Geo(scenario)
    routes, violations = evaluate(geo, {"E1": ["A", "B"], "E2": ["C"]})
    assert not violations
    return geo, Plan(id="candidate-test", scenario_id=scenario.id, routes=routes)


def test_candidates_show_donor_savings_and_both_shifted_routes(candidate_plan):
    geo, plan = candidate_plan
    rows = list_candidates(geo, plan, "A")
    assert [row["engineer_id"] for row in rows] == ["E1", "E2", "E3"]
    assert [row["feasible"] for row in rows] == [True, True, False]

    donor = plan.routes_by_engineer["E1"]
    without, _ = evaluate_route(geo, geo.engineers["E1"], ["B"])
    savings = round(donor.distance_km - without.distance_km, 3)
    moved = rows[1]
    assert moved["donor_removed_km"] == savings
    assert moved["total_delta_km"] == round(moved["added_km"] - savings, 3)
    assert moved["preview_routes"] == {"E2": ["A", "C"], "E1": ["B"]}
    assert {change["order_id"] for change in moved["shifted"]} == {"B", "C"}
    assert moved["position"] == 0
    assert moved["arrival"] and moved["start"]

    own = rows[0]
    assert own["total_delta_km"] == 0
    assert own["preview_routes"] == {"E1": ["A", "B"]}
    assert rows[2]["reason_code"] == "NO_SKILL"
    assert rows[2]["reason"]


def test_candidates_endpoint_checks_order_and_returns_each_engineer(monkeypatch, candidate_plan):
    geo, plan = candidate_plan
    record = PlanRecord(plan=plan, scenario=geo.scenario)
    record._geo = geo
    record._geo_key = tuple(order.id for order in geo.scenario.orders)
    monkeypatch.setattr(lookup, "record", lambda _: record)

    assert len(manual.get_candidates(plan.id, "A")) == len(geo.scenario.engineers)
    with pytest.raises(HTTPException) as error:
        manual.get_candidates(plan.id, "missing")
    assert error.value.status_code == 404


def test_manual_accepts_candidate_position(monkeypatch, candidate_plan):
    geo, plan = candidate_plan
    row = next(row for row in list_candidates(geo, plan, "A") if row["engineer_id"] == "E2")
    record = PlanRecord(
        plan=plan,
        scenario=geo.scenario,
        baseline=Plan(id="base", scenario_id=geo.scenario.id, kind="baseline"),
    )
    record._geo = geo
    record._geo_key = tuple(order.id for order in geo.scenario.orders)
    monkeypatch.setattr(lookup, "record", lambda _: record)
    monkeypatch.setattr(manual.store, "put", lambda _: None)
    monkeypatch.setattr(manual.store, "select", lambda _: None)

    response = manual.manual_assign(
        plan.id,
        ManualRequest(order_id="A", engineer_id="E2", position=row["position"]),
    )
    assert response.optimized.routes_by_engineer["E2"].order_ids == row["preview_routes"]["E2"]
    assert response.optimized.routes_by_engineer["E1"].order_ids == row["preview_routes"]["E1"]
