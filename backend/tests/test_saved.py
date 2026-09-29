"""Сохранение, список, загрузка и удаление планов диспетчера."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from planner.api import saved as saved_module
from planner.api.app import app
from planner.ingest import store as scenario_store

pytestmark = pytest.mark.slow

FAST = {"objective": "auto", "time_limit_s": 3}


@pytest.fixture(scope="module")
def client():
    if not scenario_store.load_all():
        pytest.skip("сценарии ещё не собраны")
    return TestClient(app)


@pytest.fixture(scope="module")
def created(client):
    response = client.post("/api/plans", json={"scenario_id": "demo", "params": FAST})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture(autouse=True)
def saved_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(saved_module, "SAVED_DIR", tmp_path / "saved")
    return tmp_path / "saved"


def save(client, plan_id, name="План дня"):
    response = client.post("/api/saved", json={"plan_id": plan_id, "name": name})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.slow
def test_save_and_list_carry_name_scenario_and_metrics(client, created):
    brief = save(client, created["optimized"]["id"], "  Утренний  ")
    assert brief["name"] == "Утренний"
    assert brief["scenario_id"] == "demo"
    assert brief["metrics"] == created["optimized"]["metrics"]
    assert brief["saved_at"]
    listed = client.get("/api/saved", params={"scenario_id": "demo"}).json()
    assert [item["id"] for item in listed] == [brief["id"]]
    assert client.get("/api/saved", params={"scenario_id": "vostok"}).json() == []


@pytest.mark.slow
def test_load_restores_plan_under_new_id_with_variants(client, created):
    source_id = created["optimized"]["id"]
    brief = save(client, source_id)
    loaded = client.post(f"/api/saved/{brief['id']}/load")
    assert loaded.status_code == 200, loaded.text
    body = loaded.json()
    assert body["optimized"]["id"] != source_id
    assert body["optimized"]["metrics"] == created["optimized"]["metrics"]
    assert body["scenario"]["id"] == "demo"
    assert [v["key"] for v in body["variants"]] == [v["key"] for v in created["variants"]]
    ids = {v["plan_id"] for v in body["variants"]}
    assert body["optimized"]["id"] in ids or not ids
    for plan_id in ids:
        assert client.get(f"/api/plans/{plan_id}").status_code == 200
    assert client.get(f"/api/plans/{body['optimized']['id']}/geometry").status_code == 200


@pytest.mark.slow
def test_load_keeps_event_diff_pointing_at_new_id(client, created):
    source = created["optimized"]
    target = next(s["order_id"] for r in source["routes"] for s in r["stops"] if s["departure"] > "11:10")
    replanned = client.post(
        f"/api/plans/{source['id']}/events",
        json={"type": "cancel_order", "time": "11:10", "order_id": target},
    ).json()
    brief = save(client, replanned["plan"]["id"])
    body = client.post(f"/api/saved/{brief['id']}/load").json()
    assert body["diff"]["after_plan_id"] == body["optimized"]["id"]
    assert body["diff"]["removed"] == replanned["diff"]["removed"]
    assert body["diff"]["newly_unassigned"] == replanned["diff"]["newly_unassigned"]


def test_delete_removes_entry(client, created):
    brief = save(client, created["optimized"]["id"])
    assert client.delete(f"/api/saved/{brief['id']}").json() == {"deleted": brief["id"]}
    assert client.get("/api/saved").json() == []
    assert client.post(f"/api/saved/{brief['id']}/load").status_code == 404
    assert client.delete(f"/api/saved/{brief['id']}").status_code == 404


def test_save_rejects_blank_name_unknown_plan_and_bad_id(client, created):
    plan_id = created["optimized"]["id"]
    assert client.post("/api/saved", json={"plan_id": plan_id, "name": "   "}).status_code == 422
    assert client.post("/api/saved", json={"plan_id": "p9999", "name": "x"}).status_code == 404
    assert client.post("/api/saved/not-an-id/load").status_code == 404


def test_new_plan_ids_skip_ids_already_in_memory(client, created):
    brief = save(client, created["optimized"]["id"])
    first = client.post(f"/api/saved/{brief['id']}/load").json()["optimized"]["id"]
    second = client.post(f"/api/saved/{brief['id']}/load").json()["optimized"]["id"]
    assert first != second


@pytest.mark.slow
def test_load_onto_a_plan_adds_a_copy_and_keeps_the_variants(client, created):
    onto_id = created["variants"][0]["plan_id"]
    brief = save(client, created["variants"][1]["plan_id"], "Свой")
    loaded = client.post(f"/api/saved/{brief['id']}/load", params={"onto": onto_id})
    assert loaded.status_code == 200, loaded.text
    body = loaded.json()
    assert body["optimized"]["id"] not in {v["plan_id"] for v in created["variants"]}
    assert body["optimized"]["parent_plan_id"] == onto_id
    assert [v["plan_id"] for v in body["variants"]] == [v["plan_id"] for v in created["variants"]]
    assert body["optimized"]["metrics"] == created["variants"][1]["metrics"]
    for variant in created["variants"]:
        assert client.get(f"/api/plans/{variant['plan_id']}").status_code == 200


@pytest.mark.slow
def test_load_onto_an_unknown_plan_is_refused(client, created):
    brief = save(client, created["optimized"]["id"])
    assert client.post(f"/api/saved/{brief['id']}/load", params={"onto": "p9999"}).status_code == 404


@pytest.mark.slow
def test_load_onto_a_plan_of_another_area_is_refused(client, created, saved_dir):
    brief = save(client, created["optimized"]["id"])
    path = saved_dir / f"{brief['id']}.json"
    entry = json.loads(path.read_text(encoding="utf-8"))
    entry["scenario_id"] = "vostok"
    path.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
    refused = client.post(f"/api/saved/{brief['id']}/load", params={"onto": created["optimized"]["id"]})
    assert refused.status_code == 422
    assert "другого участка" in refused.json()["detail"]


@pytest.mark.slow
def test_brief_names_the_variant_a_plan_was_made_from(client, created):
    variant = created["variants"][0]
    brief = save(client, variant["plan_id"])
    assert brief["from_title"] == variant["title"]
