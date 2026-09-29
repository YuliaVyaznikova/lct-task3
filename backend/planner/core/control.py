"""Справочное сопоставление с фактическим ручным распределением."""

from __future__ import annotations

from dataclasses import dataclass

from planner.core import metrics as metrics_module
from planner.core.models import (
    Engineer,
    Metrics,
    Plan,
    PlanParams,
    Point,
    Scenario,
    Skill,
    Transport,
    Violation,
)
from planner.core.text import decimal, plural
from planner.core.validate import Geo, evaluate

CONTROL_ATTRIBUTE = "control_engineer"

CONTROL_SHIFT = ("06:00", "23:59")


@dataclass
class ControlReference:
    plan: Plan
    metrics: Metrics
    violations: list[Violation]
    brigades: list[str]
    covered_orders: int

    @property
    def late_starts(self) -> int:
        return sum(1 for violation in self.violations if violation.code == "WINDOW")

    def summary(self) -> str:
        if not self.brigades:
            return "В выгрузке нет контрольного распределения для этого участка."

        count = len(self.brigades)
        word = plural(count, "бригада", "бригады", "бригад")
        text = (
            f"Фактически заявки выполняли {count} {word}, "
            f"суммарный пробег около {self.metrics.distance_total_km:.0f} км "
            f"({decimal(self.metrics.distance_per_order_km)} км на заявку)."
        )
        if self.late_starts:
            visits = plural(self.late_starts, "визит", "визита", "визитов")
            started = plural(self.late_starts, "начался", "начались", "начались")
            text += f" При этом {self.late_starts} {visits} {started} позже окна, обещанного клиенту."
        return text


def has_control(scenario: Scenario) -> bool:
    return any(order.attributes.get(CONTROL_ATTRIBUTE) for order in scenario.orders)


def control_brigades(scenario: Scenario) -> list[str]:
    """Бригады из контроля в порядке появления ориентир для числа инженеров."""
    seen: list[str] = []
    for order in scenario.orders:
        brigade = order.attributes.get(CONTROL_ATTRIBUTE)
        if isinstance(brigade, str) and brigade and brigade not in seen:
            seen.append(brigade)
    return seen


def brigade_engineers(scenario: Scenario, names: list[str]) -> list[Engineer]:
    """Синтетические профили для реальных бригад щедрые, чтобы не завышать нарушения."""
    return [
        Engineer(
            id=f"C{index + 1:02d}",
            name=name,
            skills=list(Skill),
            transport=Transport.CAR,
            shift_start=CONTROL_SHIFT[0],
            shift_end=CONTROL_SHIFT[1],
            start=Point(
                address=scenario.office.address,
                lat=scenario.office.lat,
                lon=scenario.office.lon,
            ),
        )
        for index, name in enumerate(names)
    ]


def build(scenario: Scenario) -> ControlReference:
    """Восстанавливает фактические маршруты бригад и считает их метрики."""
    names = control_brigades(scenario)
    if not names:
        empty = Plan(id="control", scenario_id=scenario.id, kind="baseline")
        return ControlReference(empty, Metrics(), [], [], 0)

    engineers = brigade_engineers(scenario, names)
    by_name = {engineer.name: engineer.id for engineer in engineers}

    reference_scenario = scenario.model_copy(update={"engineers": engineers})
    geo = Geo(reference_scenario)

    assignment: dict[str, list[str]] = {engineer.id: [] for engineer in engineers}
    covered = 0
    for order in scenario.orders:
        brigade = order.attributes.get(CONTROL_ATTRIBUTE)
        if isinstance(brigade, str) and brigade in by_name:
            assignment[by_name[brigade]].append(order.id)
            covered += 1

    for engineer_id, order_ids in assignment.items():
        assignment[engineer_id] = sorted(
            order_ids, key=lambda oid: (geo.orders[oid].window_start_min, oid)
        )

    routes, violations = evaluate(geo, assignment)
    plan = Plan(
        id="control",
        scenario_id=scenario.id,
        kind="baseline",
        params=PlanParams(objective="min_engineers", time_limit_s=0),
        routes=routes,
        unassigned=[],
        plan_explanation="Фактическое распределение из контрольного файла выгрузки.",
    )
    plan.metrics = metrics_module.compute(reference_scenario, routes, [])
    return ControlReference(
        plan=plan,
        metrics=plan.metrics,
        violations=violations,
        brigades=names,
        covered_orders=covered,
    )


def comparison_rows(ours: Metrics, control: Metrics) -> list[tuple[str, float, float]]:
    """Три сопоставимых показателя."""
    return [
        ("Задействовано исполнителей", float(ours.engineers_used), float(control.engineers_used)),
        ("Суммарный пробег, км", ours.distance_total_km, control.distance_total_km),
        ("Пробег на заявку, км", ours.distance_per_order_km, control.distance_per_order_km),
    ]
