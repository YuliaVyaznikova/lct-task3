"""Подсказка ближайшего свободного окна для неназначенной заявки."""

from __future__ import annotations

from fastapi.testclient import TestClient

from planner.api import app as api
from planner.api.candidates import nearest_window
from planner.core import solver
from planner.core.models import PlanParams, Priority, Skill
from planner.core.validate import Geo
from tests.conftest import make_engineer, make_order, make_scenario

QUICK = PlanParams(objective="min_engineers", time_limit_s=2, no_improve_s=1)


def morning_only():
    late = make_order("LATE", 3, window=("16:00", "18:00"))
    early = make_order("EARLY", 2, window=("10:00", "12:00"))
    return make_scenario([late, early], [make_engineer("A", shift=("09:00", "13:00"))])


def test_suggests_the_closest_window_that_fits():
    scenario = morning_only()
    geo = Geo(scenario)
    plan = solver.plan(scenario, geo, QUICK)
    assert [u.order_id for u in plan.unassigned] == ["LATE"]

    hint = nearest_window(geo, plan, "LATE")

    assert hint["available"] is True
    assert (hint["window_start"], hint["window_end"]) == ("12:00", "14:00")
    assert hint["engineer_id"] == "A"
    assert "12:00–14:00" in hint["text"]


def test_other_visits_keep_their_windows():
    scenario = morning_only()
    geo = Geo(scenario)
    plan = solver.plan(scenario, geo, QUICK)
    before = {stop.order_id: stop.start for route in plan.routes for stop in route.stops}

    hint = nearest_window(geo, plan, "LATE")

    assert hint["available"]
    assert before == {"EARLY": "10:00"}


def test_no_window_helps_without_the_skill():
    order = make_order("NET", 3, skill=Skill.EMERGENCY, window=("16:00", "18:00"))
    scenario = make_scenario([order], [make_engineer("A")])
    geo = Geo(scenario)
    plan = solver.plan(scenario, geo, QUICK)

    hint = nearest_window(geo, plan, "NET")

    assert hint["available"] is False
    assert "навыка" in hint["text"]


def test_incident_is_never_offered_an_earlier_window():
    order = make_order("SOS", 3, skill=Skill.EMERGENCY, window=("16:00", "18:00"), priority=Priority.URGENT)
    scenario = make_scenario(
        [order], [make_engineer("A", skills=[Skill.EMERGENCY], shift=("09:00", "13:00"))]
    )
    geo = Geo(scenario)
    plan = solver.plan(scenario, geo, QUICK)

    hint = nearest_window(geo, plan, "SOS")

    assert hint["available"] is False


def test_endpoint_returns_the_hint(monkeypatch):
    scenario = morning_only()
    monkeypatch.setattr(api, "_load_scenario", lambda _: scenario)
    client = TestClient(api.app)
    created = client.post("/api/plans", json={"scenario_id": scenario.id, "params": QUICK.model_dump()}).json()

    response = client.get(f"/api/plans/{created['optimized']['id']}/nearest/LATE")

    assert response.status_code == 200
    assert response.json()["window_start"] == "12:00"
