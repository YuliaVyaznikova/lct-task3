"""Тела запросов и ответов HTTP API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from planner.core import solver
from planner.core.metrics import MetricRow
from planner.core.models import Diff, Metrics, Plan, PlanParams, Scenario

VARIANT_KEYS = (*solver.AUTO_OBJECTIVES, "balanced")
VARIANT_TITLES = {
    "min_engineers": "Меньше инженеров",
    "min_distance": "Меньший пробег",
    "balanced": "Ровная загрузка",
}


class ScenarioBrief(BaseModel):
    id: str
    name: str
    date: str
    orders: int
    engineers: int
    engineers_min: int
    events: int
    office: str


class PlanRequest(BaseModel):
    scenario_id: str
    params: PlanParams = Field(default_factory=PlanParams)
    engineer_count: int | None = None


class LegsRequest(BaseModel):
    plan_id: str | None = None
    scenario_id: str | None = None
    engineer_count: int | None = None
    routes: dict[str, list[str]]


class ControlReferenceOut(BaseModel):
    """Справочное сопоставление с фактическим ручным распределением."""

    available: bool
    summary: str = ""
    brigades: int = 0
    covered_orders: int = 0
    late_starts: int = 0
    rows: list[dict] = Field(default_factory=list)


class VariantOut(BaseModel):
    key: Literal["min_engineers", "min_distance", "balanced"]
    title: str
    plan_id: str
    metrics: Metrics


class PlanResponse(BaseModel):
    optimized: Plan
    baseline: Plan
    comparison: list[MetricRow]
    control: ControlReferenceOut
    scenario: Scenario
    variants: list[VariantOut] = Field(default_factory=list)
    diff: Diff | None = None


class SaveRequest(BaseModel):
    plan_id: str
    name: str = Field(min_length=1, max_length=80)


class ReplanResponse(BaseModel):
    plan: Plan
    diff: Diff
    scenario: Scenario
    variants: list[VariantOut] = Field(default_factory=list)


class ManualRequest(BaseModel):
    order_id: str
    engineer_id: str | None = None
    position: int | Literal["best"] = "best"
