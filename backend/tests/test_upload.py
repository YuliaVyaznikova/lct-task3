"""Загрузка своих данных через api: csv выгрузки и готовый json-сценарий."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from planner.api.app import app
from planner.ingest import store as scenario_store
from planner.paths import ROOT, SCENARIOS_DIR

RAW_EXPORT = ROOT / "data" / "raw" / "Восток Синтетические данные.csv"


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(scenario_store, "SCENARIOS_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def small_scenario():
    if not (SCENARIOS_DIR / "demo.json").is_file():
        pytest.skip("демо-сценарий ещё не собран")
    source = scenario_store.load("demo", directory=SCENARIOS_DIR)
    trimmed = source.model_copy(deep=True)
    trimmed.id = "uploaded"
    trimmed.name = "Загруженный набор"
    trimmed.orders = trimmed.orders[:12]
    trimmed.engineers = trimmed.engineers[:4]
    trimmed.events = []
    return trimmed


def upload(client, name: str, payload: bytes, content_type: str):
    return client.post(
        "/api/scenarios/upload",
        files={"synthetic": (name, payload, content_type)},
    )


def test_json_scenario_is_accepted(client, isolated_store, small_scenario):
    body = small_scenario.model_dump_json().encode("utf-8")
    response = upload(client, "scenario.json", body, "application/json")

    assert response.status_code == 200, response.text
    loaded = response.json()
    assert loaded["id"] == "uploaded"
    assert len(loaded["orders"]) == 12


@pytest.mark.slow
def test_uploaded_scenario_can_be_planned(client, isolated_store, small_scenario):
    body = small_scenario.model_dump_json().encode("utf-8")
    assert upload(client, "scenario.json", body, "application/json").status_code == 200

    response = client.post(
        "/api/plans",
        json={"scenario_id": "uploaded", "params": {"time_limit_s": 3}},
    )

    assert response.status_code == 200, response.text
    plan = response.json()["optimized"]
    assigned = sum(len(route["stops"]) for route in plan["routes"])
    assert assigned + len(plan["unassigned"]) == 12


def test_upload_with_taken_id_gets_a_new_one(client, isolated_store, small_scenario):
    body = small_scenario.model_dump_json().encode("utf-8")
    assert upload(client, "scenario.json", body, "application/json").status_code == 200
    first = (isolated_store / "uploaded.json").read_bytes()

    response = upload(client, "scenario.json", body, "application/json")

    assert response.status_code == 200, response.text
    again = response.json()
    assert again["id"] == "uploaded-2"
    assert again["name"] == "Загруженный набор (2)"
    assert (isolated_store / "uploaded.json").read_bytes() == first
    assert upload(client, "scenario.json", body, "application/json").json()["id"] == "uploaded-3"


def test_numbered_copy_keeps_region_settings():
    from planner.api.lookup import config_region

    assert config_region("yugo-vostok-2") == "yugo-vostok"
    assert config_region("yugocentr") == "yugocentr"
    assert config_region("uploaded-2") == "vostok"


def test_broken_json_is_refused_in_russian(client, isolated_store):
    response = upload(client, "scenario.json", b"{\"id\": ", "application/json")

    assert response.status_code == 422
    assert "JSON" in response.json()["detail"]


@pytest.mark.skipif(not RAW_EXPORT.is_file(), reason="нет data/raw с выгрузкой")
def test_beeline_export_is_read_from_csv(client, isolated_store):
    response = upload(client, RAW_EXPORT.name, RAW_EXPORT.read_bytes(), "text/csv")

    assert response.status_code == 200, response.text
    scenario = response.json()
    assert len(scenario["orders"]) == 66
    assert scenario["office"]["address"]
    assert scenario["engineers"], "инженеры достраиваются при загрузке"
    assert all(order["lat"] and order["lon"] for order in scenario["orders"])


@pytest.mark.skipif(not RAW_EXPORT.is_file(), reason="нет data/raw с выгрузкой")
def test_beeline_export_does_not_replace_shipped_region(client, isolated_store):
    shipped = isolated_store / "vostok.json"
    shipped.write_text("{}", encoding="utf-8")

    response = upload(client, RAW_EXPORT.name, RAW_EXPORT.read_bytes(), "text/csv")

    assert response.status_code == 200, response.text
    assert response.json()["id"] == "vostok-2"
    assert shipped.read_text(encoding="utf-8") == "{}"


def test_broken_csv_is_refused_in_russian(client, isolated_store):
    response = upload(client, "export.csv", "не;таблица;совсем\n".encode("cp1251"), "text/csv")

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail
    assert any(word in detail.lower() for word in ("выгрузк", "координат", "формат"))


def test_upload_does_not_touch_the_repository(client, isolated_store, small_scenario):
    body = small_scenario.model_dump_json().encode("utf-8")
    assert upload(client, "scenario.json", body, "application/json").status_code == 200

    written = {path.name for path in isolated_store.glob("*.json")}
    assert written == {"uploaded.json"}
    saved = json.loads((isolated_store / "uploaded.json").read_text(encoding="utf-8"))
    assert saved["id"] == "uploaded"


@pytest.mark.skipif(not RAW_EXPORT.is_file(), reason="нет data/raw с выгрузкой")
def test_ungeocodable_addresses_are_refused_in_russian(client, isolated_store, monkeypatch):
    from planner.ingest import geocode

    def fail(*args, **kwargs):
        raise geocode.GeocodeError("не удалось определить координаты")

    monkeypatch.setattr(geocode, "apply_to_scenario", fail)
    response = upload(client, RAW_EXPORT.name, RAW_EXPORT.read_bytes(), "text/csv")
    assert response.status_code == 422
    assert "координаты" in response.json()["detail"]


@pytest.mark.skipif(not RAW_EXPORT.is_file(), reason="нет data/raw с выгрузкой")
def test_a_geocoding_bug_is_not_blamed_on_the_file(client, isolated_store, monkeypatch):
    """Раньше любая ошибка геокодера превращалась в 422 «проверьте формат файла»."""
    from planner.ingest import geocode

    def bug(*args, **kwargs):
        raise KeyError("lat")

    monkeypatch.setattr(geocode, "apply_to_scenario", bug)
    with pytest.raises(KeyError):
        upload(client, RAW_EXPORT.name, RAW_EXPORT.read_bytes(), "text/csv")
