"""Хранилище планов в памяти процесса со сбросом на диск (DESIGN.md §12).

Полноценная база данных задаче не нужна: горизонт — один рабочий день,
пользователь один (диспетчер), а ТЗ §3.2 прямо относит СУБД к необязательному.
План живёт в памяти, копия пишется в runtime/plans — чтобы можно было
воспроизвести демонстрацию и приложить план к отчёту.

Каждый план хранится вместе со своей рабочей копией сценария: перепланирование
по срочной заявке дополняет сценарий новой заявкой, и эта правка не должна
протекать в исходные данные других планов.
"""

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
    geo: Geo
    baseline: Plan | None = None
    diff: Diff | None = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    @property
    def id(self) -> str:
        return self.plan.id


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

    def _dump(self, record: PlanRecord) -> None:
        try:
            PLANS_DIR.mkdir(parents=True, exist_ok=True)
            payload = {
                "plan": record.plan.model_dump(mode="json"),
                "baseline": record.baseline.model_dump(mode="json") if record.baseline else None,
                "diff": record.diff.model_dump(mode="json") if record.diff else None,
                "created_at": record.created_at,
            }
            (PLANS_DIR / f"{record.id}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
            )
        except OSError:
            # Диск недоступен — сервис обязан продолжать работать: план уже в памяти.
            pass


store = PlanStore()
