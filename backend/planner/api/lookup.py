"""Поиск плана и сценария для обработчиков, ошибки в виде ответов 404."""

from __future__ import annotations

import re

from fastapi import HTTPException

from planner.api.schemas import ControlReferenceOut, PlanResponse, VariantOut
from planner.api.store import PlanRecord, store
from planner.core import baseline as baseline_module
from planner.core import control as control_module
from planner.core import metrics as metrics_module
from planner.core.models import Plan, Scenario
from planner.ingest import beeline
from planner.ingest import store as scenario_store

DEFAULT_ENGINEER_REGION = "vostok"


def record(plan_id: str) -> PlanRecord:
    """План из хранилища или ответ 404."""
    try:
        return store.get(plan_id)
    except KeyError:
        raise HTTPException(404, f"План {plan_id} не найден. Постройте план заново.") from None


def load_scenario(scenario_id: str) -> Scenario:
    """Сценарий по id или ответ 404 со списком доступных."""
    try:
        return scenario_store.load(scenario_id)
    except FileNotFoundError:
        raise HTTPException(
            404,
            f"Сценарий «{scenario_id}» не найден. Доступные: "
            + ", ".join(s.id for s in scenario_store.load_all()),
        ) from None


def config_region(scenario_id: str) -> str:
    """Участок с настройками бригад для сценария, для чужого набора это DEFAULT_ENGINEER_REGION."""
    base_region_id = re.sub(r"-\d+$", "", scenario_id)
    if base_region_id in beeline.REGION_BY_ID:
        return base_region_id
    return DEFAULT_ENGINEER_REGION


def control_reference(scenario: Scenario, plan: Plan) -> ControlReferenceOut:
    """Как эти же заявки распределили вручную."""
    if not control_module.has_control(scenario):
        return ControlReferenceOut(available=False)

    reference = control_module.build(scenario)
    rows = [
        {"title": title, "ours": ours, "control": fact}
        for title, ours, fact in control_module.comparison_rows(plan.metrics, reference.metrics)
    ]

    return ControlReferenceOut(
        available=True,
        summary=reference.summary(),
        brigades=len(reference.brigades),
        covered_orders=reference.covered_orders,
        late_starts=reference.late_starts,
        rows=rows,
    )


def plan_response(plan_record: PlanRecord) -> PlanResponse:
    """Ответ по сохранённому плану: базовый вариант, сравнение, контроль и варианты."""
    baseline = plan_record.baseline or baseline_module.plan(plan_record.scenario, plan_record.geo)
    shows_diff = plan_record.diff and plan_record.diff.after_plan_id == plan_record.id

    return PlanResponse(
        optimized=plan_record.plan,
        baseline=baseline,
        comparison=metrics_module.compare(plan_record.plan.metrics, baseline.metrics),
        control=control_reference(plan_record.scenario, plan_record.plan),
        scenario=plan_record.scenario,
        variants=[VariantOut.model_validate(item) for item in plan_record.variants],
        diff=plan_record.diff if shows_diff else None,
    )
