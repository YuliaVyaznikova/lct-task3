"""Справочник нормативов: «Тип заявки BK» + «Тип заявки HD» -> навык, длительность, приоритет."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from planner.core.models import Priority, Skill
from planner.paths import CONFIG_DIR


@dataclass(frozen=True)
class Norm:
    skill: Skill
    tech_min: int
    docs_min: int
    priority: Priority
    priority_tier: int
    name: str

    @property
    def duration_min(self) -> int:
        return self.tech_min + self.docs_min


@dataclass(frozen=True)
class _Rule:
    work_type: str
    hd_match: str
    norm: Norm


@lru_cache(maxsize=4)
def load_rules(path: Path | None = None) -> tuple[_Rule, ...]:
    path = path or CONFIG_DIR / "normatives.csv"
    rules: list[_Rule] = []
    with path.open(encoding="utf-8", newline="") as fh:
        rows = [line for line in fh if not line.lstrip().startswith("#")]
    for row in csv.DictReader(rows, delimiter=";"):
        rules.append(
            _Rule(
                work_type=row["work_type"].strip().casefold(),
                hd_match=row["hd_match"].strip().casefold(),
                norm=Norm(
                    skill=Skill(row["skill"].strip()),
                    tech_min=int(row["tech_min"]),
                    docs_min=int(row["docs_min"]),
                    priority=Priority(row["priority"].strip()),
                    priority_tier=int(row["priority_tier"]),
                    name=row["normative_name"].strip(),
                ),
            )
        )
    if not rules:
        raise ValueError(f"пустой справочник нормативов: {path}")
    return tuple(rules)


def classify(work_type: str, hd_type: str, path: Path | None = None) -> Norm:
    """Первое сверху правило, у которого совпали оба поля (* любое значение)."""
    wt = (work_type or "").strip().casefold()
    hd = (hd_type or "").strip().casefold()
    for rule in load_rules(path):
        if rule.work_type != "*" and rule.work_type != wt:
            continue
        if rule.hd_match != "*" and rule.hd_match not in hd:
            continue
        return rule.norm
    raise ValueError(f"нет правила для ({work_type!r}, {hd_type!r}) — в справочнике должна быть строка *;*")
