"""Хранилище планов в памяти процесса со сбросом на диск."""

from __future__ import annotations

import itertools
import json
import threading
from dataclasses import dataclass, field
from datetime import datetime

from planner.core.models import Diff, Plan, Scenario
from planner.core.validate import Geo
from planner.paths import PLANS_DIR

_counter = itertools.count(1)
_lock = threading.Lock()


def next_plan_id(prefix: str = "p") -> str:
    with _lock:
        number = next(_counter)
    return f"{prefix}{number:04d}"


@dataclass
class PlanRecord:
    plan: Plan
    scenario: Scenario
    baseline: Plan | None = None
    diff: Diff | None = None
    variants: list[dict] = field(default_factory=list)
    selected_plan_id: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    _geo: Geo | None = field(default=None, repr=False)
    _geo_key: tuple[str, ...] = field(default=(), repr=False)

    @property
    def id(self) -> str:
        return self.plan.id

    @property
    def geo(self) -> Geo:
        """Индексация точек, пересобираемая при изменении состава заявок."""
        key = tuple(order.id for order in self.scenario.orders)
        if self._geo is None or self._geo_key != key:
            self._geo = Geo(self.scenario)
            self._geo_key = key
        return self._geo


class PlanStore:
    def __init__(self) -> None:
        self._records: dict[str, PlanRecord] = {}

    def put(self, record: PlanRecord) -> PlanRecord:
        self._records[record.id] = record
        self._dump(record)
        return record

    def get(self, plan_id: str) -> PlanRecord:
        record = self._records.get(plan_id)
        if record is None:
            raise KeyError(plan_id)
        return record

    def has(self, plan_id: str) -> bool:
        return plan_id in self._records

    def all(self) -> list[PlanRecord]:
        return sorted(self._records.values(), key=lambda r: r.created_at, reverse=True)

    def select(self, plan_id: str) -> PlanRecord:
        record = self.get(plan_id)
        related = {item["plan_id"] for item in record.variants}
        for variant_id in related:
            if variant_id in self._records:
                self._records[variant_id].selected_plan_id = plan_id
                self._dump(self._records[variant_id])
        record.selected_plan_id = plan_id
        if not related:
            self._dump(record)
        return record

    def _dump(self, record: PlanRecord) -> None:
        try:
            PLANS_DIR.mkdir(parents=True, exist_ok=True)
            payload = {
                "plan": record.plan.model_dump(mode="json"),
                "baseline": record.baseline.model_dump(mode="json") if record.baseline else None,
                "diff": record.diff.model_dump(mode="json") if record.diff else None,
                "variants": record.variants,
                "selected_plan_id": record.selected_plan_id,
                "created_at": record.created_at,
            }
            (PLANS_DIR / f"{record.id}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
            )
        except OSError:
            pass


store = PlanStore()
