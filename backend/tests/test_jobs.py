"""Фоновые задачи планирования и варианты ответа."""

from __future__ import annotations

from pydantic import BaseModel

from planner.api import app as api
from planner.api.jobs import PlanningJob, jobs
from planner.api.store import store
from planner.core.models import CancelOrderEvent, PlanParams


def test_job_stream_has_progress_and_done_events():
    class Result(BaseModel):
        value: int

    job = PlanningJob()
    job.progress({"assigned": 1})
    job.run(lambda progress: Result(value=3))
    chunks = list(job.stream())
    assert chunks[0].startswith("event: progress\ndata: ")
    assert '"assigned": 1' in chunks[0]
    assert chunks[-1].startswith("event: done\ndata: ")
    assert '"value": 3' in chunks[-1]


def test_auto_plan_stores_three_selectable_variants(toy, monkeypatch):
    monkeypatch.setattr(api, "_load_scenario", lambda _: toy)
    request = api.PlanRequest(
        scenario_id=toy.id,
        params=PlanParams(objective="auto", time_limit_s=1, no_improve_s=1),
    )
    response = api.create_plan(request)
    assert [variant.key for variant in response.variants] == [
        "min_engineers", "min_distance", "balanced"
    ]
    assert len({variant.plan_id for variant in response.variants}) == 3
    assert response.optimized.id in {variant.plan_id for variant in response.variants[:2]}
    chosen = response.variants[1].plan_id
    selected = api.select_plan(chosen)
    assert selected.optimized.id == chosen
    assert all(store.get(variant.plan_id).selected_plan_id == chosen for variant in response.variants)


def test_plan_job_finishes_with_full_response(toy, monkeypatch):
    monkeypatch.setattr(api, "_load_scenario", lambda _: toy)
    request = api.PlanRequest(
        scenario_id=toy.id,
        params=PlanParams(objective="min_engineers", time_limit_s=1, no_improve_s=1),
    )
    job_id = api.create_plan_job(request)["job_id"]
    job = jobs.get(job_id)
    events = []
    while True:
        kind, payload = job.events.get(timeout=10)
        events.append(kind)
        if kind in {"done", "error"}:
            break
    assert events[-1] == "done"
    assert "optimized" in payload and "variants" in payload


def test_event_job_and_selection_routes_are_registered():
    paths = {route.path for route in api.app.routes}
    assert "/api/plans/{plan_id}/events/jobs" in paths
    assert "/api/plans/jobs/{job_id}/events" in paths
    assert "/api/plans/{plan_id}/select" in paths


def test_event_job_returns_replan_response(toy, monkeypatch):
    monkeypatch.setattr(api, "_load_scenario", lambda _: toy)
    created = api.create_plan(api.PlanRequest(
        scenario_id=toy.id,
        params=PlanParams(objective="min_engineers", time_limit_s=1, no_improve_s=1),
    ))
    target = next(iter(created.optimized.assignment))
    job_id = api.apply_event_job(
        created.optimized.id,
        CancelOrderEvent(time="08:00", order_id=target),
    )["job_id"]
    job = jobs.get(job_id)
    while True:
        kind, payload = job.events.get(timeout=15)
        if kind in {"done", "error"}:
            break
    assert kind == "done", payload
    assert target in payload["diff"]["removed"]
    assert payload["plan"]["params"]["time_limit_s"] == 8


def test_progress_is_throttled_per_variant():
    """Параллельные варианты не глушат друг друга."""
    job = PlanningJob()
    for variant in ("min_engineers", "min_distance", "balanced"):
        job.progress({"variant": variant, "assigned": 1})
    job.progress({"variant": "min_distance", "assigned": 2})
    sent = []
    while not job.events.empty():
        kind, payload = job.events.get()
        sent.append((kind, payload["variant"], payload["assigned"]))
    assert sent == [
        ("progress", "min_engineers", 1),
        ("progress", "min_distance", 1),
        ("progress", "balanced", 1),
    ]
