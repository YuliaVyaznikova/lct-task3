"""Оборудование бригады: потребность заявки и утренний запас."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from planner.core.models import Order, Scenario
from planner.paths import CONFIG_DIR


@dataclass(frozen=True)
class Rule:
    work_type: str
    hd_match: str
    items: dict[str, int]


@dataclass
class EquipmentConfig:
    rules: tuple[Rule, ...] = ()
    stock: dict[str, int] = field(default_factory=dict)
    titles: dict[str, str] = field(default_factory=dict)

    @property
    def kinds(self) -> list[str]:
        return sorted(self.stock)

    def title(self, kind: str) -> str:
        return self.titles.get(kind, kind)


@lru_cache(maxsize=4)
def load(path: Path | None = None) -> EquipmentConfig:
    path = path or CONFIG_DIR / "equipment.yaml"
    if not path.is_file():
        return EquipmentConfig()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rules = tuple(
        Rule(
            work_type=str(item.get("work_type", "*")).strip().casefold(),
            hd_match=str(item.get("hd_match", "*")).strip().casefold(),
            items={k: int(v) for k, v in (item.get("items") or {}).items()},
        )
        for item in (raw.get("needs") or [])
    )
    return EquipmentConfig(
        rules=rules,
        stock={k: int(v) for k, v in (raw.get("stock") or {}).items()},
        titles={k: str(v) for k, v in (raw.get("titles") or {}).items()},
    )


def needs_for(work_type: str, hd_type: str, config: EquipmentConfig | None = None) -> dict[str, int]:
    """Что нужно взять с собой для этой заявки."""
    config = config or load()
    work = (work_type or "").strip().casefold()
    hd = (hd_type or "").strip().casefold()
    for rule in config.rules:
        if rule.work_type != "*" and rule.work_type != work:
            continue
        if rule.hd_match != "*" and rule.hd_match not in hd:
            continue
        return dict(rule.items)
    return {}


def order_needs(order: Order, config: EquipmentConfig | None = None) -> dict[str, int]:
    """Потребность заявки: из атрибутов, если уже посчитана, иначе по правилам."""
    stored = order.attributes.get("equipment")
    if isinstance(stored, dict):
        return {str(k): int(v) for k, v in stored.items() if int(v) > 0}
    return {k: v for k, v in needs_for(order.work_type, order.description, config).items() if v > 0}


def populate(scenario: Scenario, config: EquipmentConfig | None = None) -> int:
    """Проставляет потребность в оборудовании всем заявкам сценария."""
    config = config or load()
    marked = 0
    for order in scenario.orders:
        items = needs_for(order.work_type, order.description, config)
        items = {k: v for k, v in items.items() if v > 0}
        if items:
            order.attributes["equipment"] = items
            marked += 1
        else:
            order.attributes.pop("equipment", None)
    return marked


def stock_for(engineer_id: str, config: EquipmentConfig | None = None) -> dict[str, int]:
    """Что бригада взяла в офисе утром."""
    config = config or load()
    return dict(config.stock)


def describe_needs(items: dict[str, int], config: EquipmentConfig | None = None) -> str:
    config = config or load()
    if not items:
        return "оборудование не требуется"
    return ", ".join(
        f"{config.title(kind)}" + (f" ×{count}" if count > 1 else "")
        for kind, count in sorted(items.items())
    )


def summary(scenario: Scenario, config: EquipmentConfig | None = None) -> str:
    config = config or load()
    totals: dict[str, int] = {}
    for order in scenario.orders:
        for kind, count in order_needs(order, config).items():
            totals[kind] = totals.get(kind, 0) + count
    if not totals:
        return "оборудование заявкам не требуется"
    need = ", ".join(f"{config.title(k)}: {v}" for k, v in sorted(totals.items()))
    have = ", ".join(f"{config.title(k)}: {v}" for k, v in sorted(config.stock.items()))
    return f"нужно за день: {need}; утренний запас на бригаду: {have}"
