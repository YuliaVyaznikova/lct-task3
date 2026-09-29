"""Сохранённые планы диспетчера: файлы JSON в runtime/saved."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime

from pydantic import BaseModel

from planner.api.store import PlanRecord, next_plan_id, store
from planner.core.models import Diff, Metrics, Plan, Scenario
from planner.paths import SAVED_DIR

_ID = re.compile(r"^s[0-9a-f]{8}$")


class SavedBrief(BaseModel):
    id: str
    name: str
    saved_at: str
    scenario_id: str
    metrics: Metrics
    from_title: str | None = None


def _path(saved_id: str):
    if not _ID.match(saved_id):
        raise KeyError(saved_id)
    return SAVED_DIR / f"{saved_id}.json"


def _read(saved_id: str) -> dict:
    path = _path(saved_id)
    if not path.is_file():
        raise KeyError(saved_id)
    return json.loads(path.read_text(encoding="utf-8"))


def _source_title(entry: dict) -> str | None:
    plan_id = entry["plan"]["id"]
    return next((item.get("title") for item in entry.get("variants", []) if item["plan_id"] == plan_id), None)


def _brief(entry: dict) -> SavedBrief:
    return SavedBrief(
        id=entry["id"],
        name=entry["name"],
        saved_at=entry["saved_at"],
        scenario_id=entry["scenario_id"],
        metrics=Metrics.model_validate(entry["plan"]["metrics"]),
        from_title=_source_title(entry),
    )


def _dump_diff(diff: Diff | None) -> dict | None:
    return diff.model_dump(mode="json") if diff else None


def _sibling_payloads(record: PlanRecord) -> list[dict]:
    siblings = []
    for item in record.variants:
        plan_id = item["plan_id"]
        if plan_id == record.id or not store.has(plan_id):
            continue
        sibling = store.get(plan_id)
        siblings.append({"plan": sibling.plan.model_dump(mode="json"), "diff": _dump_diff(sibling.diff)})
    return siblings


def save(record: PlanRecord, name: str) -> SavedBrief:
    """Записывает текущее рабочее состояние под именем диспетчера."""
    entry = {
        "id": f"s{uuid.uuid4().hex[:8]}",
        "name": name,
        "saved_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "scenario_id": record.scenario.id,
        "plan": record.plan.model_dump(mode="json"),
        "scenario": record.scenario.model_dump(mode="json"),
        "baseline": record.baseline.model_dump(mode="json") if record.baseline else None,
        "variants": record.variants,
        "diff": _dump_diff(record.diff),
        "siblings": _sibling_payloads(record),
    }
    SAVED_DIR.mkdir(parents=True, exist_ok=True)
    _path(entry["id"]).write_text(json.dumps(entry, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return _brief(entry)


def listing(scenario_id: str | None = None) -> list[SavedBrief]:
    """Сохранённые планы, новые первыми."""
    if not SAVED_DIR.is_dir():
        return []
    briefs = []
    for path in SAVED_DIR.glob("s*.json"):
        try:
            briefs.append(_brief(json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, ValueError, KeyError):
            continue
    briefs = [b for b in briefs if scenario_id is None or b.scenario_id == scenario_id]
    return sorted(briefs, key=lambda b: b.saved_at, reverse=True)


def _restored(payload: dict, new_id: str, diff: dict | None) -> tuple[Plan, Diff | None]:
    plan = Plan.model_validate(payload).model_copy(update={"id": new_id})
    restored_diff = Diff.model_validate(diff) if diff else None
    if restored_diff is not None:
        restored_diff = restored_diff.model_copy(update={"after_plan_id": new_id})
    return plan, restored_diff


def load(saved_id: str) -> PlanRecord:
    """Возвращает сохранённый план в память под новым номером и выбирает его."""
    entry = _read(saved_id)
    scenario = Scenario.model_validate(entry["scenario"])
    baseline = Plan.model_validate(entry["baseline"]) if entry.get("baseline") else None
    main_id = next_plan_id()
    id_map = {entry["plan"]["id"]: main_id}
    for sibling in entry.get("siblings", []):
        id_map[sibling["plan"]["id"]] = next_plan_id()
    variants = [{**item, "plan_id": id_map[item["plan_id"]]} for item in entry["variants"] if item["plan_id"] in id_map]
    for sibling in entry.get("siblings", []):
        plan, diff = _restored(sibling["plan"], id_map[sibling["plan"]["id"]], sibling.get("diff"))
        store.put(PlanRecord(
            plan=plan, scenario=scenario, baseline=baseline, diff=diff,
            variants=variants, selected_plan_id=main_id,
        ))
    plan, diff = _restored(entry["plan"], main_id, entry.get("diff"))
    record = PlanRecord(
        plan=plan, scenario=scenario, baseline=baseline, diff=diff,
        variants=variants, selected_plan_id=main_id,
    )
    store.put(record)
    return record


def load_as_copy(saved_id: str, onto: PlanRecord) -> PlanRecord:
    """Добавляет сохранённый план копией поверх вариантов, которые открыты сейчас."""
    entry = _read(saved_id)
    if entry["scenario_id"] != onto.scenario.id:
        raise ValueError("План сохранён для другого участка.")
    scenario = Scenario.model_validate(entry["scenario"])
    baseline = Plan.model_validate(entry["baseline"]) if entry.get("baseline") else onto.baseline
    plan = Plan.model_validate(entry["plan"]).model_copy(update={"id": next_plan_id(), "parent_plan_id": onto.id})
    record = PlanRecord(
        plan=plan, scenario=scenario, baseline=baseline, variants=list(onto.variants), selected_plan_id=plan.id,
    )
    store.put(record)
    store.select(plan.id)
    return record


def delete(saved_id: str) -> None:
    path = _path(saved_id)
    if not path.is_file():
        raise KeyError(saved_id)
    path.unlink()
