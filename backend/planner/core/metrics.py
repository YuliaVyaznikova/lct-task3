"""Метрики плана и сравнение с базовым вариантом (DESIGN.md §8, ТЗ §2.3).

Две метрики обязательны по ТЗ:
  * выполнение всех заявок наименьшим количеством персонала — число уникальных
    исполнителей, которым назначена хотя бы одна заявка;
  * пробег по маршруту каждого исполнителя — отдельно и суммарно по плану.

Остальные считаем дополнительно: ТЗ §2.3 это прямо разрешает, а диспетчеру
они нужны, чтобы понять, почему план именно такой.
"""

from __future__ import annotations

from dataclasses import dataclass

from planner.core.models import Metrics, Plan, Priority, Route, Scenario, Unassigned
from planner.core.timeutil import hhmm_to_min

#: Запас до конца окна, ниже которого визит считаем рискованным по опозданию.
LATE_RISK_MARGIN_MIN = 15


def compute(
    scenario: Scenario,
    routes: list[Route],
    unassigned: list[Unassigned],
    extra_engineers_needed: int = 0,
) -> Metrics:
    orders = scenario.orders_by_id
    engineers = scenario.engineers_by_id
    assigned_ids = {stop.order_id for route in routes for stop in route.stops}

    used = [route for route in routes if route.stops]
    distance_by_engineer = {route.engineer_id: round(route.distance_km, 2) for route in used}

    utilization: dict[str, float] = {}
    for route in used:
        engineer = engineers.get(route.engineer_id)
        if engineer is None:
            continue
        shift = max(engineer.shift_end_min - engineer.shift_start_min, 1)
        utilization[route.engineer_id] = round((route.work_min + route.travel_min) / shift, 3)

    late_risk = 0
    for route in routes:
        for stop in route.stops:
            order = orders.get(stop.order_id)
            if order is None:
                continue
            if order.window_end_min - hhmm_to_min(stop.start) < LATE_RISK_MARGIN_MIN:
                late_risk += 1

    urgent = [o for o in scenario.orders if o.priority is Priority.URGENT]
    total_km = sum(route.distance_km for route in used)
    per_order = round(total_km / len(assigned_ids), 2) if assigned_ids else 0.0

    return Metrics(
        orders_total=len(scenario.orders),
        assigned=len(assigned_ids),
        unassigned=len(unassigned),
        urgent_total=len(urgent),
        urgent_assigned=sum(1 for o in urgent if o.id in assigned_ids),
        engineers_total=len(scenario.engineers),
        engineers_used=len(used),
        distance_total_km=round(total_km, 2),
        distance_per_order_km=per_order,
        distance_by_engineer=distance_by_engineer,
        travel_min_total=sum(route.travel_min for route in used),
        work_min_total=sum(route.work_min for route in used),
        wait_min_total=sum(route.wait_min for route in used),
        utilization_by_engineer=utilization,
        extra_engineers_needed=extra_engineers_needed,
        late_risk=late_risk,
    )


@dataclass(frozen=True)
class MetricRow:
    key: str
    title: str
    ours: float
    baseline: float
    delta: float
    better: bool | None
    higher_is_better: bool


#: Порядок строк в таблице сравнения; первые две — обязательные метрики ТЗ.
COMPARISON_ROWS: tuple[tuple[str, str, bool], ...] = (
    ("engineers_used", "Задействовано инженеров", False),
    ("distance_total_km", "Суммарный пробег, км", False),
    ("distance_per_order_km", "Пробег на заявку, км", False),
    ("assigned", "Назначено заявок", True),
    ("unassigned", "Не назначено заявок", False),
    ("urgent_assigned", "Назначено срочных", True),
    ("travel_min_total", "Время в пути, мин", False),
    ("wait_min_total", "Ожидание, мин", False),
    ("late_risk", "Визитов с риском опоздания", False),
)


def compare(ours: Metrics, baseline: Metrics) -> list[MetricRow]:
    """Таблица «наш план / базовый вариант / разница» (ТЗ §4 п.7, §8.1)."""
    rows: list[MetricRow] = []
    for key, title, higher_is_better in COMPARISON_ROWS:
        a = float(getattr(ours, key))
        b = float(getattr(baseline, key))
        delta = round(a - b, 2)
        if delta == 0:
            better: bool | None = None
        else:
            better = (delta > 0) if higher_is_better else (delta < 0)
        rows.append(
            MetricRow(
                key=key,
                title=title,
                ours=a,
                baseline=b,
                delta=delta,
                better=better,
                higher_is_better=higher_is_better,
            )
        )
    return rows


def comparison_table(ours: Metrics, baseline: Metrics) -> str:
    """Тот же расчёт для вывода в консоль."""
    rows = compare(ours, baseline)
    width = max(len(row.title) for row in rows)
    lines = [f"{'показатель':<{width}}  {'наш план':>10} {'базовый':>10} {'разница':>10}"]
    lines.append("-" * (width + 34))
    for row in rows:
        mark = "" if row.better is None else ("  лучше" if row.better else "  хуже")
        lines.append(
            f"{row.title:<{width}}  {row.ours:>10.2f} {row.baseline:>10.2f} {row.delta:>+10.2f}{mark}"
        )
    return "\n".join(lines)


def is_better(ours: Metrics, baseline: Metrics) -> bool:
    """Лексикографика целевой функции (DESIGN.md §6.1): заявки → инженеры → пробег."""
    if ours.assigned != baseline.assigned:
        return ours.assigned > baseline.assigned
    if ours.engineers_used != baseline.engineers_used:
        return ours.engineers_used < baseline.engineers_used
    return ours.distance_total_km < baseline.distance_total_km


def attach(plan: Plan, scenario: Scenario, extra_engineers_needed: int = 0) -> Plan:
    plan.metrics = compute(scenario, plan.routes, plan.unassigned, extra_engineers_needed)
    return plan
