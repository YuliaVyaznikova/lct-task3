"""HTTP API полный путь сценария защиты через сеть."""

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


def test_unknown_api_path_is_not_swallowed_by_the_spa(client):
    """Опечатка в адресе должна дать понятный 404, а не страницу интерфейса."""
    response = client.get("/api/нет-такого-метода")
    assert response.status_code == 404
    assert "application/json" in response.headers.get("content-type", "")


def test_reference_lists_dictionaries(client):
    body = client.get("/api/reference").json()
    assert set(body["skills"]) == {"local", "connection", "emergency"}
    assert set(body["transports"]) == {"car", "foot", "bike", "public"}
    assert "км/ч" in body["travel_model"]


@pytest.mark.slow
def test_plan_returns_both_variants_and_comparison(plan):
    assert plan["optimized"]["kind"] == "optimized"
    assert plan["baseline"]["kind"] == "baseline"
    keys = [row["key"] for row in plan["comparison"]]
    assert keys[:2] == ["engineers_used", "distance_total_km"]


@pytest.mark.slow
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


@pytest.mark.slow
def test_cancel_event_produces_diff(client, plan):
    plan_id = plan["optimized"]["id"]
    target = next(
        s["order_id"]
        for r in plan["optimized"]["routes"]
        for s in r["stops"]
        if s["departure"] > "11:10"
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


@pytest.mark.slow
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


@pytest.mark.slow
def test_urgent_order_stays_usable_after_replanning(client):
    """Регрессия: заявка, добавленная событием, должна быть полноценной."""
    created = client.post("/api/plans", json={"scenario_id": "demo", "params": FAST}).json()
    plan_id = created["optimized"]["id"]
    anchor = created["scenario"]["orders"][0]
    payload = {
        "type": "urgent_order",
        "time": "12:30",
        "order": {
            "id": "REGRESS-1",
            "address": "авария после события",
            "lat": anchor["lat"],
            "lon": anchor["lon"],
            "skill": "emergency",
            "duration_min": 80,
            "window_start": "12:30",
            "window_end": "23:59",
            "priority": "urgent",
        },
    }
    replanned = client.post(f"/api/plans/{plan_id}/events", json=payload)
    assert replanned.status_code == 200, replanned.text
    new_plan = replanned.json()["plan"]
    new_id = new_plan["id"]

    assigned = {s["order_id"] for r in new_plan["routes"] for s in r["stops"]}
    explained = {u["order_id"] for u in new_plan["unassigned"]}
    assert "REGRESS-1" in assigned | explained, "новая заявка не должна пропадать из плана"

    card = client.get(f"/api/plans/{new_id}/explain/REGRESS-1")
    assert card.status_code == 200, card.text

    response = client.post(
        f"/api/plans/{new_id}/manual", json={"order_id": "REGRESS-1", "engineer_id": None}
    )
    assert response.status_code == 200, response.text
    body = response.json()["optimized"]
    assert any(u["order_id"] == "REGRESS-1" for u in body["unassigned"])
    covered = {s["order_id"] for r in body["routes"] for s in r["stops"]} | {
        u["order_id"] for u in body["unassigned"]
    }
    assert len(covered) == len(response.json()["scenario"]["orders"])


@pytest.mark.slow
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
        assert all(stop["departure"] <= "13:00" for stop in route["stops"])


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


@pytest.mark.slow
def test_manual_move_to_another_engineer(client):
    created = client.post("/api/plans", json={"scenario_id": "demo", "params": FAST}).json()
    plan_id = created["optimized"]["id"]
    route = next(r for r in created["optimized"]["routes"] if r["stops"])
    order_id = route["stops"][0]["order_id"]
    card = client.get(f"/api/plans/{plan_id}/explain/{order_id}").json()
    feasible = [line for line in card["alternatives"] if "км к его маршруту" in line]
    alternative = next(
        (
            engineer["id"]
            for engineer in created["scenario"]["engineers"]
            if any(line.startswith(f"{engineer['name']}:") for line in feasible)
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


def test_candidates_endpoint_returns_ordered_rows(client, plan):
    plan_id = plan["optimized"]["id"]
    order_id = next(iter(plan["optimized"]["explanations"]))
    response = client.get(f"/api/plans/{plan_id}/candidates/{order_id}")
    assert response.status_code == 200, response.text
    rows = response.json()
    assert len(rows) == len(plan["scenario"]["engineers"])
    assert all("preview_routes" in row and "shifted" in row for row in rows)
    feasible = [row for row in rows if row["feasible"]]
    assert feasible
    assert [row["total_delta_km"] for row in feasible] == sorted(
        row["total_delta_km"] for row in feasible
    )


@pytest.mark.slow
def test_planning_job_stream_and_variant_selection(client):
    response = client.post(
        "/api/plans/jobs",
        json={"scenario_id": "demo", "params": {"objective": "auto", "time_limit_s": 1}},
    )
    assert response.status_code == 200, response.text
    job_id = response.json()["job_id"]
    with client.stream("GET", f"/api/plans/jobs/{job_id}/events") as stream:
        lines = list(stream.iter_lines())
    assert any(line == "event: progress" for line in lines)
    assert "event: done" in lines
    import json

    done_index = lines.index("event: done")
    done = json.loads(lines[done_index + 1].removeprefix("data: "))
    assert len(done["variants"]) == 3
    selected_id = done["variants"][1]["plan_id"]
    selected = client.post(f"/api/plans/{selected_id}/select")
    assert selected.status_code == 200, selected.text
    assert selected.json()["optimized"]["id"] == selected_id


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


@pytest.mark.slow
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
    """Обязательный состав полей результата."""
    plan_id = plan["optimized"]["id"]
    body = client.get(f"/api/plans/{plan_id}/export").json()

    assert body["исполнители"], "по каждому исполнителю нужен упорядоченный список заявок"
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


def test_scenarios_report_the_minimum_brigade_count(client):
    body = {item["id"]: item for item in client.get("/api/scenarios").json()}
    assert body["demo"]["engineers_min"] == 6
    assert body["yugo-vostok"]["engineers_min"] > body["vostok"]["engineers_min"]
    for item in body.values():
        assert item["engineers_min"] <= item["engineers"]


@pytest.mark.slow
def test_plan_with_custom_brigade_count(client):
    response = client.post(
        "/api/plans", json={"scenario_id": "demo", "params": FAST, "engineer_count": 8}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["scenario"]["engineers"]) == 8
    assert body["optimized"]["metrics"]["engineers_total"] == 8
    assert body["baseline"]["metrics"]["engineers_total"] == 8, "сравнение на одном составе"
    assert body["optimized"]["metrics"]["engineers_used"] <= 8


@pytest.mark.slow
def test_custom_brigade_count_does_not_change_the_saved_scenario(client):
    before = client.get("/api/scenarios/demo").json()
    client.post("/api/plans", json={"scenario_id": "demo", "params": FAST, "engineer_count": 7})
    after = client.get("/api/scenarios/demo").json()
    assert len(after["engineers"]) == len(before["engineers"])


def test_too_few_brigades_is_a_readable_error(client):
    response = client.post(
        "/api/plans", json={"scenario_id": "yugo-vostok", "params": FAST, "engineer_count": 7}
    )
    assert response.status_code == 422
    assert "не меньше 9" in response.json()["detail"]


@pytest.mark.slow
def test_reschedule_flag_passes_through_the_api(client):
    response = client.post(
        "/api/plans",
        json={"scenario_id": "demo", "params": {**FAST, "allow_reschedule": True}},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["optimized"]["params"]["allow_reschedule"] is True
    assert body["optimized"]["metrics"]["rescheduled"] == 0, "первичный план окно не двигает"


def test_geometry_legs_for_scenario_sequence(client, monkeypatch):
    from planner.core import geometry

    scenario = scenario_store.load("demo")
    engineer = scenario.engineers[0]
    order_ids = [scenario.orders[0].id, scenario.orders[1].id]
    requested = []

    def fake_fetch(legs, base_url=None, chains=None):
        requested.append(set(legs))
        return {leg: [[leg[0][0], leg[0][1]], [leg[1][0], leg[1][1]]] for leg in legs}

    monkeypatch.setattr(geometry, "fetch_legs", fake_fetch)
    body = client.post(
        "/api/geometry/legs",
        json={"scenario_id": "demo", "routes": {engineer.id: order_ids + ["missing"], "ghost": order_ids}},
    ).json()

    assert body["available"] is True
    legs = body["legs"][engineer.id]
    assert len(legs) == 3
    assert legs[0][0] == list(engineer.start.coords if engineer.start.has_coords else scenario.office.coords)
    assert legs[0][-1] == list(scenario.orders[0].coords)
    assert legs[2] is None
    assert body["legs"]["ghost"] == [None, None]
    assert len(requested[0]) == 2


def test_geometry_legs_unavailable_service_gives_empty_legs(client, monkeypatch):
    from planner.core import geometry

    scenario = scenario_store.load("demo")
    monkeypatch.setattr(geometry, "fetch_legs", lambda legs, base_url=None, chains=None: {leg: None for leg in legs})
    body = client.post(
        "/api/geometry/legs",
        json={"scenario_id": "demo", "routes": {scenario.engineers[0].id: [scenario.orders[0].id]}},
    ).json()
    assert body["available"] is False
    assert body["legs"][scenario.engineers[0].id] == [None]


def test_geometry_legs_need_a_scope(client):
    assert client.post("/api/geometry/legs", json={"routes": {}}).status_code == 422
    assert client.post("/api/geometry/legs", json={"scenario_id": "нет", "routes": {}}).status_code == 404


@pytest.mark.slow
def test_manual_edit_creates_new_plan_and_keeps_source(client):
    created = client.post("/api/plans", json={"scenario_id": "demo", "params": FAST}).json()
    source = created["optimized"]
    order_id = next(r for r in source["routes"] if r["stops"])["stops"][0]["order_id"]

    response = client.post(
        f"/api/plans/{source['id']}/manual", json={"order_id": order_id, "engineer_id": None}
    )
    assert response.status_code == 200, response.text
    edited = response.json()["optimized"]
    assert edited["id"] != source["id"]
    assert edited["origin"] == "manual"
    assert edited["parent_plan_id"] == source["id"]
    assert client.get(f"/api/plans/{edited['id']}").json()["optimized"]["id"] == edited["id"]

    untouched = client.get(f"/api/plans/{source['id']}").json()["optimized"]
    assert untouched["origin"] == "solver"
    assert untouched["metrics"] == source["metrics"]
    assert untouched["routes"] == source["routes"]

    again = client.post(
        f"/api/plans/{edited['id']}/manual", json={"order_id": order_id, "engineer_id": None}
    ).json()["optimized"]
    assert again["id"] not in {source["id"], edited["id"]}
    assert again["parent_plan_id"] == edited["id"]
    assert again["origin"] == "manual"


@pytest.mark.slow
def test_event_returns_variants_each_stored_as_plan(client):
    created = client.post(
        "/api/plans", json={"scenario_id": "demo", "params": {"objective": "auto", "time_limit_s": 3}}
    ).json()
    source = created["optimized"]
    target = next(
        s["order_id"] for r in source["routes"] for s in r["stops"] if s["departure"] > "11:10"
    )
    response = client.post(
        f"/api/plans/{source['id']}/events",
        json={"type": "cancel_order", "time": "11:10", "order_id": target},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    variants = body["variants"]
    assert [v["key"] for v in variants] == [v["key"] for v in created["variants"]]
    assert len(variants) == 3
    assert body["plan"]["id"] in {v["plan_id"] for v in variants}
    for variant in variants:
        fetched = client.get(f"/api/plans/{variant['plan_id']}").json()
        assert fetched["optimized"]["origin"] == "event"
        assert fetched["optimized"]["parent_plan_id"] == source["id"]
        assert fetched["optimized"]["metrics"] == variant["metrics"]
        assert fetched["diff"]["after_plan_id"] == variant["plan_id"]
        assert fetched["diff"]["before_plan_id"] == source["id"]
        assert fetched["diff"]["metrics_after"] == variant["metrics"]
        assert fetched["diff"]["event"]["type"] == "cancel_order"
    assert client.get(f"/api/plans/{source['id']}").json()["diff"] is None


def test_scenario_baseline_is_known_before_planning(client, plan):
    response = client.get("/api/scenarios/demo/baseline")
    assert response.status_code == 200, response.text
    assert response.json()["assigned"] == plan["baseline"]["metrics"]["assigned"]
