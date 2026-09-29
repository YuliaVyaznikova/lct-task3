"""Сохранённые планы: запись, список, открытие и удаление."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from planner.api import lookup
from planner.api import saved as saved_module
from planner.api.schemas import PlanResponse, SaveRequest

router = APIRouter()


@router.post("/api/saved", response_model=saved_module.SavedBrief)
def save_plan(request: SaveRequest) -> saved_module.SavedBrief:
    name = request.name.strip()
    if not name:
        raise HTTPException(422, "Укажите название плана.")
    return saved_module.save(lookup.record(request.plan_id), name)


@router.get("/api/saved", response_model=list[saved_module.SavedBrief])
def list_saved(scenario_id: str | None = None) -> list[saved_module.SavedBrief]:
    return saved_module.listing(scenario_id)


@router.post("/api/saved/{saved_id}/load", response_model=PlanResponse)
def load_saved(saved_id: str, onto: str | None = None) -> PlanResponse:
    try:
        if onto:
            return lookup.plan_response(saved_module.load_as_copy(saved_id, lookup.record(onto)))
        return lookup.plan_response(saved_module.load(saved_id))
    except KeyError:
        raise HTTPException(404, "Сохранённый план не найден.") from None
    except ValueError as error:
        raise HTTPException(422, str(error)) from None


@router.delete("/api/saved/{saved_id}")
def delete_saved(saved_id: str) -> dict[str, str]:
    try:
        saved_module.delete(saved_id)
    except KeyError:
        raise HTTPException(404, "Сохранённый план не найден.") from None
    return {"deleted": saved_id}
