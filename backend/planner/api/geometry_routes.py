"""Ломаные маршрутов по дорогам для отрисовки на карте."""

from __future__ import annotations

import functools

from fastapi import APIRouter, HTTPException

from planner.api import lookup
from planner.api.schemas import LegsRequest
from planner.core import geometry as geometry_module
from planner.core import travel
from planner.core.models import Scenario
from planner.ingest import engineers as engineers_module

router = APIRouter()


@router.get("/api/plans/{plan_id}/geometry")
def plan_geometry(plan_id: str) -> dict:
    """Ломаные маршрутов по дорогам только для отрисовки на карте."""
    record = lookup.record(plan_id)
    geometry = geometry_module.build(record.geo, record.plan)
    return {
        "available": geometry.available,
        "source": geometry.source,
        "profile": travel.OSRM_PROFILE,
        "routes": geometry.routes,
        "legs": geometry.legs,
        "errors": geometry.errors[:5],
    }


@router.post("/api/geometry/legs")
def geometry_legs(request: LegsRequest) -> dict:
    scenario = _legs_scenario(request)
    pairs = geometry_module.sequence_legs(scenario, request.routes)
    wanted = {leg for legs in pairs.values() for leg in legs if leg is not None}
    if len(wanted) > geometry_module.MAX_LEGS:
        raise HTTPException(422, f"Слишком много переходов: {len(wanted)}")

    lines = geometry_module.fetch_legs(wanted, chains=geometry_module.leg_chains(pairs))
    legs = {
        engineer_id: [_leg_polyline(leg, lines) for leg in engineer_legs]
        for engineer_id, engineer_legs in pairs.items()
    }

    return {
        "available": any(line is not None for line in lines.values()),
        "profile": travel.OSRM_PROFILE,
        "legs": legs,
    }


def _leg_polyline(leg, lines: dict):
    if leg is None or lines.get(leg) is None:
        return None
    return [[*leg[0]], *lines[leg], [*leg[1]]]


def _legs_scenario(request: LegsRequest) -> Scenario:
    if request.plan_id:
        return lookup.record(request.plan_id).scenario
    if not request.scenario_id:
        raise HTTPException(422, "Нужен plan_id или scenario_id")

    scenario = lookup.load_scenario(request.scenario_id)
    if request.engineer_count and request.engineer_count != len(scenario.engineers):
        return _resized_scenario(request.scenario_id, request.engineer_count)
    return scenario


@functools.lru_cache(maxsize=8)
def _resized_scenario(scenario_id: str, engineer_count: int) -> Scenario:
    working = lookup.load_scenario(scenario_id).model_copy(deep=True)
    try:
        return engineers_module.resize(
            working, engineer_count, region_id=lookup.config_region(working.id)
        )
    except engineers_module.InvariantError as exc:
        raise HTTPException(422, str(exc)) from None
