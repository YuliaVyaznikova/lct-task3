"""Ручное переназначение заявок диспетчером и допустимые варианты перестановки."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from planner.api import candidates as candidates_module
from planner.api import lookup
from planner.api.schemas import ManualRequest, PlanResponse
from planner.api.store import PlanRecord, next_plan_id, store
from planner.core import explain as explain_module
from planner.core import metrics as metrics_module
from planner.core.models import Plan, ReasonCode, Route, Unassigned
from planner.core.reasons import diagnose, extra_engineers_needed
from planner.core.validate import Geo, best_insertion, evaluate, first_blocking_violation

router = APIRouter()


@router.get("/api/plans/{plan_id}/candidates/{order_id}")
def get_candidates(plan_id: str, order_id: str) -> list[dict]:
    """Допустимые перестановки заявки и их влияние на два маршрута."""
    record = lookup.record(plan_id)
    if order_id not in record.geo.orders:
        raise HTTPException(404, f"Заявки {order_id} нет в сценарии")
    return candidates_module.list_candidates(record.geo, record.plan, order_id)


@router.get("/api/plans/{plan_id}/nearest/{order_id}")
def get_nearest_window(plan_id: str, order_id: str) -> dict:
    """Ближайшее другое окно, которое можно предложить клиенту по неназначенной заявке."""
    record = lookup.record(plan_id)
    if order_id not in record.geo.orders:
        raise HTTPException(404, f"Заявки {order_id} нет в сценарии")
    return candidates_module.nearest_window(record.geo, record.plan, order_id)


@router.post("/api/plans/{plan_id}/manual", response_model=PlanResponse)
def manual_assign(plan_id: str, request: ManualRequest) -> PlanResponse:
    """Ручное переназначение заявки."""
    record = lookup.record(plan_id)
    geo = record.geo
    assignment = _manual_assignment(record, request)

    routes, violations = evaluate(geo, assignment, lunch=record.plan.params.lunch)
    if violations:
        raise HTTPException(422, "; ".join(v.text for v in violations[:3]))

    edited = _edited_plan(record, request, routes)
    edited_record = PlanRecord(
        plan=edited, scenario=record.scenario, baseline=record.baseline, diff=record.diff,
        variants=list(record.variants), selected_plan_id=edited.id,
        _geo=record._geo, _geo_key=record._geo_key,
    )
    store.put(edited_record)
    store.select(edited.id)

    return lookup.plan_response(edited_record)


def _manual_assignment(record: PlanRecord, request: ManualRequest) -> dict[str, list[str]]:
    geo = record.geo
    if request.order_id not in geo.orders:
        raise HTTPException(404, f"Заявки {request.order_id} нет в сценарии")

    assignment = {route.engineer_id: list(route.order_ids) for route in record.plan.routes}
    for order_ids in assignment.values():
        if request.order_id in order_ids:
            order_ids.remove(request.order_id)

    if request.engineer_id is not None:
        _insert_order(record, geo, request, assignment)

    return assignment


def _insert_order(
    record: PlanRecord, geo: Geo, request: ManualRequest, assignment: dict[str, list[str]]
) -> None:
    if request.engineer_id not in geo.engineers:
        raise HTTPException(404, f"Инженера {request.engineer_id} нет в сценарии")
    current = assignment.setdefault(request.engineer_id, [])

    if request.position != "best":
        position = max(0, min(int(request.position), len(current)))
        current.insert(position, request.order_id)
        return

    engineer = geo.engineers[request.engineer_id]
    lunch = record.plan.params.lunch
    found = best_insertion(geo, engineer, current, request.order_id, lunch=lunch)
    if found is None:
        blocking = first_blocking_violation(geo, engineer, current, request.order_id, lunch=lunch)
        raise HTTPException(
            422,
            blocking.text if blocking else
            f"{engineer.name} не может взять заявку {request.order_id}",
        )
    current.insert(found[0], request.order_id)


def _manual_unassigned(
    record: PlanRecord, request: ManualRequest, routes: list[Route]
) -> list[Unassigned]:
    geo = record.geo
    assigned = {stop.order_id for route in routes for stop in route.stops}

    unassigned: list[Unassigned] = []
    for order in record.scenario.orders:
        if order.id in assigned:
            continue
        if order.id == request.order_id and request.engineer_id is None:
            unassigned.append(
                Unassigned(
                    order_id=order.id,
                    reason_code=ReasonCode.MANUAL,
                    reason="снята с маршрута вручную диспетчером",
                )
            )
        else:
            unassigned.append(diagnose(geo, order, routes, lunch=record.plan.params.lunch))

    return unassigned


def _edited_plan(record: PlanRecord, request: ManualRequest, routes: list[Route]) -> Plan:
    unassigned = _manual_unassigned(record, request, routes)

    edited = record.plan.model_copy(deep=True)
    edited.id = next_plan_id()
    edited.origin = "manual"
    edited.parent_plan_id = record.plan.id
    edited.routes = routes
    edited.unassigned = unassigned
    edited.metrics = metrics_module.compute(
        record.scenario, routes, unassigned, extra_engineers_needed(record.geo, unassigned)
    )
    explain_module.attach(record.geo, edited)

    return edited
