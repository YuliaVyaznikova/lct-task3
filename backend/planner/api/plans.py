"""Построение планов, фоновые расчёты, события дня и карточки заявок."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import StreamingResponse

from planner.api import lookup
from planner.api.jobs import jobs
from planner.api.schemas import (
    VARIANT_KEYS,
    VARIANT_TITLES,
    PlanRequest,
    PlanResponse,
    ReplanResponse,
    VariantOut,
)
from planner.api.store import PlanRecord, next_plan_id, store
from planner.core import baseline as baseline_module
from planner.core import explain as explain_module
from planner.core import metrics as metrics_module
from planner.core import replan as replan_module
from planner.core import solver
from planner.core.models import Event, Plan, Scenario
from planner.core.validate import Geo
from planner.ingest import engineers as engineers_module

router = APIRouter()


@router.post("/api/plans", response_model=PlanResponse)
def create_plan(request: PlanRequest) -> PlanResponse:
    return _create_plan(request)


@router.post("/api/plans/jobs")
def create_plan_job(request: PlanRequest) -> dict[str, str]:
    lookup.load_scenario(request.scenario_id)
    return {"job_id": jobs.submit(lambda progress: _create_plan(request, progress))}


@router.get("/api/plans/jobs/{job_id}/events")
def plan_job_events(job_id: str) -> StreamingResponse:
    try:
        job = jobs.get(job_id)
    except KeyError:
        raise HTTPException(404, f"Расчёт {job_id} не найден") from None
    return StreamingResponse(
        job.stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
    )


@router.get("/api/plans/{plan_id}", response_model=PlanResponse)
def get_plan(plan_id: str) -> PlanResponse:
    return lookup.plan_response(lookup.record(plan_id))


@router.post("/api/plans/{plan_id}/select", response_model=PlanResponse)
def select_plan(plan_id: str) -> PlanResponse:
    lookup.record(plan_id)
    store.select(plan_id)
    return get_plan(plan_id)


@router.post("/api/plans/{plan_id}/events", response_model=ReplanResponse)
def apply_event(plan_id: str, event: Annotated[Event, Body()]) -> ReplanResponse:
    return _apply_event(plan_id, event)


@router.post("/api/plans/{plan_id}/events/jobs")
def apply_event_job(plan_id: str, event: Annotated[Event, Body()]) -> dict[str, str]:
    lookup.record(plan_id)
    return {"job_id": jobs.submit(lambda progress: _apply_event(plan_id, event, progress))}


@router.get("/api/plans/{plan_id}/explain/{order_id}")
def explain_order(plan_id: str, order_id: str) -> dict:
    record = lookup.record(plan_id)

    card = record.plan.explanations.get(order_id)
    if card is not None:
        return {"assigned": True, **card}

    for unassigned in record.plan.unassigned:
        if unassigned.order_id == order_id:
            return {
                "assigned": False,
                "order_id": order_id,
                "reason_code": unassigned.reason_code.value,
                "reason": unassigned.reason,
                "detail": unassigned.detail,
            }

    raise HTTPException(404, f"Заявки {order_id} нет в плане {plan_id}")


def _resized_working_copy(request: PlanRequest) -> Scenario:
    working = lookup.load_scenario(request.scenario_id).model_copy(deep=True)
    if not request.engineer_count or request.engineer_count == len(working.engineers):
        return working

    try:
        engineers_module.resize(
            working, request.engineer_count, region_id=lookup.config_region(working.id)
        )
    except engineers_module.InvariantError as exc:
        raise HTTPException(422, str(exc)) from None
    return working


def _variants_of(keys: tuple[str, ...], plans: list[Plan]) -> list[VariantOut]:
    return [
        VariantOut(key=key, title=VARIANT_TITLES.get(key, key), plan_id=plan.id, metrics=plan.metrics)
        for key, plan in zip(keys, plans)
    ]


def _create_plan(request: PlanRequest, on_progress=None) -> PlanResponse:
    working = _resized_working_copy(request)
    geo = Geo(working)

    if request.params.objective == "auto":
        keys = VARIANT_KEYS
        attempts = solver.parallel_plans(
            working, request.params, solver.AUTO_OBJECTIVES, "optimized", on_progress=on_progress
        )
        attempts.append(solver.balance(
            working, geo, request.params, attempts[1], "balanced", on_progress=on_progress
        ))
        best = attempts[solver.best_index(attempts[: len(solver.AUTO_OBJECTIVES)])]
    else:
        keys = (request.params.objective,)
        attempts = [solver.plan(working, geo, request.params, on_progress=on_progress)]
        best = attempts[0]

    for attempt in attempts:
        attempt.id = next_plan_id()
        explain_module.attach(geo, attempt)
    variants = _variants_of(keys, attempts)
    base = baseline_module.plan(working, geo, plan_id=f"{best.id}-base")

    encoded_variants = [variant.model_dump(mode="json") for variant in variants]
    for attempt in attempts:
        store.put(PlanRecord(
            plan=attempt, scenario=working, baseline=base, variants=encoded_variants,
            selected_plan_id=best.id,
        ))

    return PlanResponse(
        optimized=best,
        baseline=base,
        comparison=metrics_module.compare(best.metrics, base.metrics),
        control=lookup.control_reference(working, best),
        scenario=working,
        variants=variants,
    )


def _event_objectives(record: PlanRecord) -> tuple[str, ...]:
    """Цели, по которым считались варианты исходного планирования."""
    keys = tuple(item["key"] for item in record.variants)
    if keys:
        return keys
    objective = record.plan.params.objective
    return VARIANT_KEYS if objective == "auto" else (objective,)


def _recommended_index(record: PlanRecord, objectives: tuple[str, ...], plans: list[Plan]) -> int:
    """Вариант с целью исходного плана, иначе лучший по заявкам, инженерам и километрам."""
    source_objective = record.plan.params.objective
    if source_objective in objectives:
        return objectives.index(source_objective)
    return solver.best_index(plans)


def _apply_event(plan_id: str, event: Event, on_progress=None) -> ReplanResponse:
    record = lookup.record(plan_id)
    working = record.scenario.model_copy(deep=True)
    geo = Geo(working)
    objectives = _event_objectives(record)
    plan_ids = [next_plan_id() for _ in objectives]

    try:
        results = replan_module.replan_variants(
            working, record.plan, event, objectives, plan_ids, geo, on_progress=on_progress,
        )
    except replan_module.ReplanError as exc:
        raise HTTPException(409, str(exc)) from None

    plans = [new_plan for new_plan, _ in results]
    best = _recommended_index(record, objectives, plans)
    variants = _variants_of(objectives, plans)

    encoded_variants = [variant.model_dump(mode="json") for variant in variants]
    for new_plan, diff in results:
        store.put(PlanRecord(
            plan=new_plan, scenario=working, baseline=record.baseline, diff=diff,
            variants=encoded_variants, selected_plan_id=plans[best].id,
        ))

    return ReplanResponse(
        plan=plans[best], diff=results[best][1], scenario=working, variants=variants
    )
