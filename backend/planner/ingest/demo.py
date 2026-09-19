"""Демонстрационный сценарий для защиты (ТЗ §4, §6; DESIGN.md §4.6).

ТЗ рекомендует набор на один рабочий день из 10–15 инженеров и не более
100 заявок, на котором можно проверить все обязательные ограничения:
в данных должны встречаться все три навыка, разные комбинации навыков,
все типы транспорта, пересекающиеся окна и «хотя бы один конфликт, при
котором простое последовательное распределение даёт менее эффективный план».

Организаторы такой набор не выдали — выгрузка содержит только заявки.
Поэтому собираем его сами из реального региона: адреса, окна и типы работ
настоящие, синтетические — справочник инженеров и события. Подбор seed
автоматический: перебираем, пока набор не начнёт удовлетворять всем
требованиям выше, и фиксируем первый подходящий.
"""

from __future__ import annotations

from dataclasses import dataclass

from planner.core import baseline as baseline_module
from planner.core import solver
from planner.core.models import (
    CancelOrderEvent,
    EngineerUnavailableEvent,
    PlanParams,
    Scenario,
    Skill,
    Transport,
    UrgentOrderEvent,
)
from planner.core.replan import make_urgent_order
from planner.core.validate import Geo
from planner.ingest import beeline, engineers as engineers_module
from planner.ingest import equipment as equipment_module

#: Регион-основа: компактный, целиком в городе — на карте читается лучше,
#: чем Юго-Восток с вылетами в Каширу за 90 км.
BASE_REGION = "vostok"

DEMO_ID = "demo"
DEMO_NAME = "Демонстрационный день"

#: Бюджет солвера при подборе seed. На защите лимит больше — план только лучше.
PROBE_PARAMS = PlanParams(objective="min_engineers", time_limit_s=4)


@dataclass
class Requirement:
    title: str
    ok: bool
    detail: str = ""


def _max_concurrent(scenario: Scenario) -> int:
    """Наибольшее число заявок, окна которых накрывают один и тот же момент."""
    events: list[tuple[int, int]] = []
    for order in scenario.orders:
        events.append((order.window_start_min, 1))
        events.append((order.window_end_min, -1))
    events.sort()
    current = peak = 0
    for _, delta in events:
        current += delta
        peak = max(peak, current)
    return peak


def check_dataset(scenario: Scenario) -> list[Requirement]:
    """Требования ТЗ §6 к тестовому набору."""
    skills = {order.skill for order in scenario.orders}
    transports = {engineer.transport for engineer in scenario.engineers}
    combinations = {tuple(engineer.skills) for engineer in scenario.engineers}
    # Окна считаются пересекающимися по заявкам, а не по различным слотам:
    # две заявки в одном слоте 10:00–12:00 пересекаются полностью, а соседние
    # слоты 10–12 и 12–14 лишь соприкасаются.
    peak = _max_concurrent(scenario)
    required_transport = [o for o in scenario.orders if o.required_transport is not None]

    return [
        Requirement("встречаются все три навыка", skills == set(Skill), ", ".join(sorted(s.value for s in skills))),
        Requirement("разные комбинации навыков", len(combinations) >= 3, f"{len(combinations)} комбинации"),
        Requirement("встречаются все типы транспорта", transports == set(Transport), ", ".join(sorted(t.value for t in transports))),
        Requirement(
            "есть пересекающиеся временные окна",
            peak >= 2,
            f"до {peak} заявок с общим интервалом",
        ),
        Requirement("есть заявки с требуемым транспортом", bool(required_transport), f"{len(required_transport)} шт."),
    ]


def check_conflict(scenario: Scenario, params: PlanParams | None = None) -> Requirement:
    """Последовательное распределение должно давать заметно худший план."""
    geo = Geo(scenario)
    ours = solver.plan(scenario, geo, params or PROBE_PARAMS)
    base = baseline_module.plan(scenario, geo)
    better = (
        ours.metrics.assigned > base.metrics.assigned
        or ours.metrics.engineers_used < base.metrics.engineers_used
    )
    return Requirement(
        "базовый вариант заметно хуже",
        better,
        f"назначено {ours.metrics.assigned} против {base.metrics.assigned}, "
        f"инженеров {ours.metrics.engineers_used} против {base.metrics.engineers_used}",
    )


def build_events(scenario: Scenario, plan) -> list:
    """Три заготовки событий — ровно те, что показываются на защите (ТЗ §4)."""
    events: list = []

    # 1. Срочная авария в разгар дня, рядом с плотным кластером заявок.
    hotspot = max(
        plan.routes,
        key=lambda route: len(route.stops),
        default=None,
    )
    anchor = (
        scenario.order(hotspot.stops[len(hotspot.stops) // 2].order_id)
        if hotspot and hotspot.stops
        else scenario.orders[0]
    )
    urgent = make_urgent_order(
        scenario,
        address=f"{anchor.address} (авария на ТКД)",
        lat=anchor.lat,
        lon=anchor.lon,
        skill=Skill.EMERGENCY,
        window=("12:30", "23:59"),
        duration_min=80,
        district=anchor.district,
    )
    events.append(UrgentOrderEvent(time="12:30", order=urgent))

    # 2. Отмена заявки — берём ту, что и в реальности была отменена,
    #    и обязательно ещё не начатую к моменту события.
    cancelled = [
        order
        for order in beeline.cancelled_orders(scenario)
        if any(
            stop.order_id == order.id and stop.arrival > "11:10"
            for route in plan.routes
            for stop in route.stops
        )
    ]
    if not cancelled:
        cancelled = [
            scenario.order(stop.order_id)
            for route in plan.routes
            for stop in route.stops
            if stop.arrival > "11:10"
        ]
    if cancelled:
        events.append(CancelOrderEvent(time="11:10", order_id=cancelled[0].id))

    # 3. Недоступность инженера с самым длинным маршрутом — так перестроение заметнее.
    if plan.routes:
        longest = max(plan.routes, key=lambda route: route.distance_km)
        events.append(EngineerUnavailableEvent(time="13:00", engineer_id=longest.engineer_id))

    return events


def build(
    base_region: str = BASE_REGION,
    seeds: range = range(1, 51),
    params: PlanParams | None = None,
    verbose: bool = False,
) -> tuple[Scenario, list[Requirement]]:
    """Собирает демо-сценарий и подбирает seed, при котором он показателен."""
    from planner.ingest import store

    source = store.load(base_region)
    config = engineers_module.load_config(base_region)

    chosen: Scenario | None = None
    report: list[Requirement] = []
    for seed in seeds:
        candidate = source.model_copy(deep=True)
        candidate.id = DEMO_ID
        candidate.name = DEMO_NAME
        engineers_module.populate(candidate, seed=seed, region_id=base_region)
        equipment_module.populate(candidate)

        checks = check_dataset(candidate)
        if not all(check.ok for check in checks):
            if verbose:
                failed = [c.title for c in checks if not c.ok]
                print(f"  seed {seed}: не подошёл ({', '.join(failed)})")
            continue

        conflict = check_conflict(candidate, params)
        checks.append(conflict)
        if verbose:
            print(f"  seed {seed}: {conflict.detail}" + ("" if conflict.ok else " — недостаточно"))
        if conflict.ok:
            chosen, report = candidate, checks
            break

    if chosen is None:
        raise RuntimeError(
            f"не удалось подобрать демо-набор за {len(seeds)} попыток; "
            "проверьте data/config/engineers.yaml"
        )

    geo = Geo(chosen)
    plan = solver.plan(chosen, geo, params or PROBE_PARAMS)
    chosen.events = build_events(chosen, plan)
    chosen.meta.notes = (
        f"демо-набор на основе региона «{source.name}»: адреса, окна и типы работ — "
        f"из выгрузки, справочник инженеров и события — синтетические "
        f"(seed {chosen.meta.generator_seed})"
    )
    _ = config  # конфиг читается ради ранней ошибки, если региона нет в engineers.yaml
    return chosen, report
