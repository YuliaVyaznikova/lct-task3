"""HTTP API (DESIGN.md §13) — полный путь сценария защиты через сеть."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from planner.api.app import app
from planner.ingest import store as scenario_store

FAST = {"objective": "min_engineers", "time_limit_s": 3}


@pytest.fixture(scope="module")
def client():
    if not scenario_store.load_all():
        pytest.skip("сценарии ещё не собраны")
    return TestClient(app)


@pytest.fixture(scope="module")
def plan(client):
    response = client.post("/api/plans", json={"scenario_id": "demo", "params": FAST})
    assert response.status_code == 200, response.text
    return response.json()


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["scenarios"] >= 3


def test_scenarios_list_puts_demo_first(client):
    body = client.get("/api/scenarios").json()
    assert body[0]["id"] == "demo", "с демо начинается защита"
    for item in body:
        assert item["orders"] > 0 and item["engineers"] > 0
        assert item["office"]


def test_scenario_has_coordinates_and_engineers(client):
    scenario = client.get("/api/scenarios/demo").json()
    assert scenario["office"]["lat"] and scenario["office"]["lon"]
    assert all(order["lat"] and order["lon"] for order in scenario["orders"])
    assert len(scenario["engineers"]) >= 10
    assert scenario["events"], "у демо-сценария должны быть заготовки событий"


def test_unknown_scenario_gives_readable_error(client):
    response = client.get("/api/scenarios/нет-такого")
    assert response.status_code == 404
    assert "не найден" in response.json()["detail"]


def test_reference_lists_dictionaries(client):
    body = client.get("/api/reference").json()
    assert set(body["skills"]) == {"local", "connection", "emergency"}
    assert set(body["transports"]) == {"car", "foot", "bike", "public"}
    assert "км/ч" in body["travel_model"]


# ---------------------------------------------------------------- планы


def test_plan_returns_both_variants_and_comparison(plan):
    assert plan["optimized"]["kind"] == "optimized"
    assert plan["baseline"]["kind"] == "baseline"
    keys = [row["key"] for row in plan["comparison"]]
    # Две обязательные метрики ТЗ §2.3 идут первыми.
    assert keys[:2] == ["engineers_used", "distance_total_km"]


def test_plan_beats_baseline_on_demo(plan):
    """Ради этого демо-набор и подбирался: выигрыш по обеим обязательным метрикам."""
    ours = plan["optimized"]["metrics"]
    base = plan["baseline"]["metrics"]
    assert ours["assigned"] > base["assigned"]
    assert ours["engineers_used"] <= base["engineers_used"]
    assert ours["distance_per_order_km"] < base["distance_per_order_km"]


def test_plan_has_explanations(plan):
    optimized = plan["optimized"]
    assert optimized["plan_explanation"]
    assert len(optimized["explanations"]) == optimized["metrics"]["assigned"]
    assert optimized["route_explanations"]


def test_every_order_is_assigned_or_explained(plan):
    optimized = plan["optimized"]
    assigned = {s["order_id"] for r in optimized["routes"] for s in r["stops"]}
    explained = {u["order_id"] for u in optimized["unassigned"]}
    all_orders = {o["id"] for o in plan["scenario"]["orders"]}
    assert assigned | explained == all_orders


def test_plan_can_be_fetched_again(client, plan):
    plan_id = plan["optimized"]["id"]
    again = client.get(f"/api/plans/{plan_id}").json()
    assert again["optimized"]["metrics"] == plan["optimized"]["metrics"]


def test_unknown_plan_gives_readable_error(client):
    response = client.get("/api/plans/нет-такого")
    assert response.status_code == 404
    assert "не найден" in response.json()["detail"]


def test_unknown_scenario_in_plan_request(client):
    response = client.post("/api/plans", json={"scenario_id": "zzz", "params": FAST})
    assert response.status_code == 404


# -------------------------------------------------------------- события


def test_cancel_event_produces_diff(client, plan):
    plan_id = plan["optimized"]["id"]
    target = next(
        s["order_id"]
        for r in plan["optimized"]["routes"]
        for s in r["stops"]
        if s["arrival"] > "11:10"
    )
    response = client.post(
        f"/api/plans/{plan_id}/events",
        json={"type": "cancel_order", "time": "11:10", "order_id": target},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["plan"]["id"] != plan_id, "перепланирование создаёт новый план"
    assert body["plan"]["parent_plan_id"] == plan_id
    assert target in body["diff"]["removed"]
    assert body["diff"]["summary"]
    assert body["diff"]["locked_stops"] > 0


def test_urgent_event_is_scheduled(client, plan):
    plan_id = plan["optimized"]["id"]
    anchor = plan["scenario"]["orders"][0]
    payload = {
        "type": "urgent_order",
        "time": "12:30",
        "order": {
            "id": "API-SOS-1",
            "address": "тестовая авария",
            "lat": anchor["lat"],
            "lon": anchor["lon"],
            "skill": "emergency",
            "duration_min": 80,
            "window_start": "12:30",
            "window_end": "23:59",
            "priority": "urgent",
        },
    }
    response = client.post(f"/api/plans/{plan_id}/events", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert "API-SOS-1" in body["diff"]["added"]


def test_engineer_unavailable_event(client, plan):
    plan_id = plan["optimized"]["id"]
    victim = max(plan["optimized"]["routes"], key=lambda r: len(r["stops"]))["engineer_id"]
    response = client.post(
        f"/api/plans/{plan_id}/events",
        json={"type": "engineer_unavailable", "time": "13:00", "engineer_id": victim},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    route = next((r for r in body["plan"]["routes"] if r["engineer_id"] == victim), None)
    if route:
        assert all(stop["arrival"] <= "13:00" for stop in route["stops"])


def test_impossible_event_gives_conflict(client, plan):
    plan_id = plan["optimized"]["id"]
    started = next(
        s["order_id"]
        for r in plan["optimized"]["routes"]
        for s in r["stops"]
        if s["arrival"] <= "11:10"
    )
    response = client.post(
        f"/api/plans/{plan_id}/events",
        json={"type": "cancel_order", "time": "11:10", "order_id": started},
    )
    assert response.status_code == 409
    assert "уже выполняется" in response.json()["detail"]


# ------------------------------------------------ ручное переназначение


def test_manual_move_to_another_engineer(client):
    created = client.post("/api/plans", json={"scenario_id": "demo", "params": FAST}).json()
    plan_id = created["optimized"]["id"]
    route = next(r for r in created["optimized"]["routes"] if r["stops"])
    order_id = route["stops"][0]["order_id"]
    card = client.get(f"/api/plans/{plan_id}/explain/{order_id}").json()
    alternative = next(
        (
            engineer["id"]
            for engineer in created["scenario"]["engineers"]
            if engineer["name"] in " ".join(card["alternatives"]) and "+" in " ".join(card["alternatives"])
        ),
        None,
    )
    if alternative is None:
        pytest.skip("у заявки нет допустимых альтернатив")

    response = client.post(
        f"/api/plans/{plan_id}/manual",
        json={"order_id": order_id, "engineer_id": alternative, "position": "best"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["optimized"]["metrics"]["assigned"] >= 1


def test_manual_move_to_unsuitable_engineer_is_refused(client, plan):
    plan_id = plan["optimized"]["id"]
    scenario = plan["scenario"]
    order = next(o for o in scenario["orders"] if o["skill"] == "emergency")
    wrong = next(
        (e for e in scenario["engineers"] if "emergency" not in e["skills"]),
        None,
    )
    if wrong is None:
        pytest.skip("все инженеры умеют аварийные работы")
    response = client.post(
        f"/api/plans/{plan_id}/manual",
        json={"order_id": order["id"], "engineer_id": wrong["id"], "position": "best"},
    )
    assert response.status_code == 422
    assert response.json()["detail"]


def test_manual_unassign(client):
    created = client.post("/api/plans", json={"scenario_id": "demo", "params": FAST}).json()
    plan_id = created["optimized"]["id"]
    order_id = next(r for r in created["optimized"]["routes"] if r["stops"])["stops"][0]["order_id"]
    response = client.post(
        f"/api/plans/{plan_id}/manual", json={"order_id": order_id, "engineer_id": None}
    )
    assert response.status_code == 200, response.text
    body = response.json()["optimized"]
    assert order_id not in {s["order_id"] for r in body["routes"] for s in r["stops"]}
    removed = next(u for u in body["unassigned"] if u["order_id"] == order_id)
    assert removed["reason_code"] == "MANUAL"


def test_manual_unknown_ids(client, plan):
    plan_id = plan["optimized"]["id"]
    assert client.post(f"/api/plans/{plan_id}/manual", json={"order_id": "ZZZ"}).status_code == 404
    order_id = next(r for r in plan["optimized"]["routes"] if r["stops"])["stops"][0]["order_id"]
    response = client.post(
        f"/api/plans/{plan_id}/manual", json={"order_id": order_id, "engineer_id": "E99"}
    )
    assert response.status_code == 404


# ------------------------------------------------------- объяснения и вывод


def test_explain_assigned_and_unassigned(client, plan):
    plan_id = plan["optimized"]["id"]
    assigned_id = next(r for r in plan["optimized"]["routes"] if r["stops"])["stops"][0]["order_id"]
    card = client.get(f"/api/plans/{plan_id}/explain/{assigned_id}").json()
    assert card["assigned"] is True
    assert card["checks"] and card["why"]

    if plan["optimized"]["unassigned"]:
        missing_id = plan["optimized"]["unassigned"][0]["order_id"]
        card = client.get(f"/api/plans/{plan_id}/explain/{missing_id}").json()
        assert card["assigned"] is False
        assert card["reason"]


def test_explain_unknown_order(client, plan):
    plan_id = plan["optimized"]["id"]
    assert client.get(f"/api/plans/{plan_id}/explain/ZZZ").status_code == 404


def test_export_matches_the_specification_format(client, plan):
    """ТЗ §2.4.2 перечисляет, что обязано быть в результате."""
    plan_id = plan["optimized"]["id"]
    body = client.get(f"/api/plans/{plan_id}/export").json()

    assert body["исполнители"], "по каждому исполнителю — упорядоченный список заявок"
    first = body["исполнители"][0]
    assert {"исполнитель", "пробег_км", "заявки"} <= set(first)
    visit = first["заявки"][0]
    assert {"заявка", "прибытие", "начало_работ", "пробег_км"} <= set(visit)

    итого = body["итого"]
    assert {
        "задействовано_исполнителей",
        "пробег_по_исполнителям_км",
        "суммарный_пробег_км",
    } <= set(итого)
    assert body["сравнение_с_базовым_вариантом"]
    assert body["объяснение"]
    for item in body["не_назначены"]:
        assert item["причина"]
