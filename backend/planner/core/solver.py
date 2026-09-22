"""Оптимизатор распределения и маршрутов на Google OR-Tools (DESIGN.md §6).

Задача — VRPTW с гетерогенным парком, пропуском узлов и платой за выход
инженера на смену:

    min  Σ drop(o)·[заявка пропущена]          — выполнить как можно больше заявок
       + F·|задействованные инженеры|          — затем занять как можно меньше людей
       + Σ пробег                              — затем сократить километраж
       + Σ w_u·(насколько поздно начата срочная)
       + Σ S·[заявка сменила инженера]         — только при перепланировании

Порядок величин подобран так, чтобы критерии были лексикографическими:
никакая экономия километров не оправдывает лишнего инженера, и никакая
экономия инженеров не оправдывает пропуска заявки (ТЗ §2.3, Q&A блок 11).

Солвер не выставляет времена в плане: он возвращает только порядок посещения,
а все времена и метрики пересчитывает валидатор (DESIGN.md §8).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from planner.core import metrics as metrics_module
from planner.core import reasons
from planner.core.models import (
    Engineer,
    Plan,
    PlanParams,
    Priority,
    Scenario,
    Transport,
)
from planner.core.timeutil import min_to_hhmm
from planner.core.validate import Geo, StartState, check_static, evaluate

#: Штраф за пропуск заявки по ярусу приоритета, метры. Больше любого мыслимого
#: пробега и платы за инженера, поэтому выполнение заявок всегда важнее экономии.
#: Очерёдность задана экспертами (п.15): авария → подключение → ремонт и дозаказ.
DROP_PENALTY_BY_TIER = {
    1: 10_000_000,  # авария
    2: 2_000_000,   # подключение
    3: 1_000_000,   # ремонт, дозаказ, информационные выезды
}

#: Плата за вывод инженера на смену в режиме «меньше инженеров», метры.
ENGINEER_FIXED_COST = 100_000

#: Цена минуты задержки срочной заявки, метры за минуту.
URGENT_LATENESS_WEIGHT = 50

#: Цена минуты переноса за пределы обещанного клиенту окна, метры за минуту.
#: Работает только при `allow_reschedule` (эксперты, п.2). Величина подобрана
#: так, чтобы перенос был дороже любой перестановки маршрута, но дешевле
#: отказа от заявки: 200 минут опоздания стоят столько же, сколько невыполнение.
#: Иначе говоря, сдвинуть время клиенту допустимо только когда альтернатива —
#: вовсе не приехать.
RESCHEDULE_WEIGHT = 5_000

#: Верхняя граница горизонта планирования в минутах (сутки с запасом).
HORIZON_MIN = 1_800


@dataclass
class SolveResult:
    assignment: dict[str, list[str]]
    unassigned_ids: list[str]
    dropped_by_prefilter: list[str] = field(default_factory=list)
    status: str = ""


def _drop_penalty(order) -> int:
    """Цена отказа от заявки: чем выше ярус, тем дороже её не выполнить."""
    tier = getattr(order, "priority_tier", 3)
    if order.priority is Priority.URGENT:
        tier = min(tier, 1)
    return DROP_PENALTY_BY_TIER.get(tier, DROP_PENALTY_BY_TIER[3])


def _capable(scenario: Scenario, order) -> list[Engineer]:
    return [e for e in scenario.engineers if check_static(e, order) is None]


def solve(
    scenario: Scenario,
    geo: Geo | None = None,
    params: PlanParams | None = None,
    starts: dict[str, StartState] | None = None,
    order_ids: list[str] | None = None,
    previous: dict[str, str] | None = None,
) -> SolveResult:
    """Строит распределение. `starts` и `previous` используются при перепланировании."""
    geo = geo or Geo(scenario)
    params = params or PlanParams()
    starts = starts or {}
    previous = previous or {}

    # Пустой список — это «планировать нечего», а не «планировать всё»:
    # при перепланировании пул законно бывает пустым.
    if order_ids is None:
        order_ids = [o.id for o in scenario.orders]
    pool = [geo.orders[order_id] for order_id in order_ids]
    # Инженеры, помеченные closed (например, ставшие недоступными), новых заявок
    # не получают, но их уже начатые визиты валидатор всё равно покажет в плане.
    engineers = [
        e
        for e in scenario.engineers
        if not (e.id in starts and starts[e.id].closed)
    ]

    # Заявки, которые не может взять ни один инженер, в модель не попадают:
    # их причина определяется диагностикой, а не солвером.
    servable = [o for o in pool if _capable(scenario, o)]
    prefiltered = [o.id for o in pool if o not in servable]
    if not servable or not engineers:
        return SolveResult({e.id: [] for e in engineers}, [o.id for o in pool], prefiltered, "EMPTY")

    # ---- узлы модели: заявки, стартовые точки инженеров, фиктивный финиш
    node_of_order = {order.id: i for i, order in enumerate(servable)}
    geo_nodes = [geo.node(order.id) for order in servable]

    start_nodes: list[int] = []
    for engineer in engineers:
        state = starts.get(engineer.id)
        geo_node = state.node if state else geo.start_node(engineer)
        start_nodes.append(len(geo_nodes))
        geo_nodes.append(geo_node)
    depot_offset = len(servable)
    dummy_end = len(geo_nodes)
    total_nodes = dummy_end + 1

    distance_m = np.zeros((total_nodes, total_nodes), dtype=np.int64)
    source = geo.travel.distance_m()
    distance_m[:dummy_end, :dummy_end] = source[np.ix_(geo_nodes, geo_nodes)]

    time_by_transport: dict[Transport, np.ndarray] = {}
    for transport in {e.transport for e in engineers}:
        matrix = np.zeros((total_nodes, total_nodes), dtype=np.int64)
        matrix[:dummy_end, :dummy_end] = geo.travel.time_min(transport)[np.ix_(geo_nodes, geo_nodes)]
        time_by_transport[transport] = matrix

    service_min = np.zeros(total_nodes, dtype=np.int64)
    for order in servable:
        service_min[node_of_order[order.id]] = order.duration_min

    manager = pywrapcp.RoutingIndexManager(
        total_nodes, len(engineers), start_nodes, [dummy_end] * len(engineers)
    )
    routing = pywrapcp.RoutingModel(manager)

    # ---- стоимость дуг: пробег плюс штраф за смену исполнителя при перепланировании
    stability = params.stability_weight_m
    previous_vehicle = {
        node_of_order[order_id]: engineer_id
        for order_id, engineer_id in previous.items()
        if order_id in node_of_order
    }

    def make_distance_callback(vehicle: int):
        engineer_id = engineers[vehicle].id

        def callback(from_index: int, to_index: int) -> int:
            i = manager.IndexToNode(from_index)
            j = manager.IndexToNode(to_index)
            cost = int(distance_m[i, j])
            if stability and j in previous_vehicle and previous_vehicle[j] != engineer_id:
                cost += stability
            return cost

        return callback

    def make_time_callback(vehicle: int):
        matrix = time_by_transport[engineers[vehicle].transport]

        def callback(from_index: int, to_index: int) -> int:
            i = manager.IndexToNode(from_index)
            j = manager.IndexToNode(to_index)
            return int(service_min[i] + matrix[i, j])

        return callback

    time_callback_indices = []
    for vehicle in range(len(engineers)):
        routing.SetArcCostEvaluatorOfVehicle(
            routing.RegisterTransitCallback(make_distance_callback(vehicle)), vehicle
        )
        time_callback_indices.append(routing.RegisterTransitCallback(make_time_callback(vehicle)))

    routing.AddDimensionWithVehicleTransits(
        time_callback_indices,
        HORIZON_MIN,  # ожидание перед окном
        HORIZON_MIN,
        False,  # начало смены задаётся явно, а не нулём
        "Time",
    )
    time_dim = routing.GetDimensionOrDie("Time")

    # ---- временные окна заявок: cumul в узле = время НАЧАЛА работ
    earliest_shift = min(
        (starts[e.id].available_min if e.id in starts else e.shift_start_min) for e in engineers
    )
    allow_reschedule = params.allow_reschedule and bool(starts)
    for order in servable:
        index = manager.NodeToIndex(node_of_order[order.id])
        if allow_reschedule:
            # Перенос разрешён: верхняя граница отодвигается до конца смены,
            # а выход за обещанное окно штрафуется (эксперты, п.2 — время
            # можно скорректировать, клиента предупредит служба поддержки).
            latest = max(order.window_end_min, max(e.shift_end_min for e in engineers))
            time_dim.CumulVar(index).SetRange(order.window_start_min, latest)
            time_dim.SetCumulVarSoftUpperBound(
                index, order.window_end_min, RESCHEDULE_WEIGHT
            )
        else:
            time_dim.CumulVar(index).SetRange(order.window_start_min, order.window_end_min)
        if order.priority is Priority.URGENT:
            # «Аварию нужно выполнить как можно раньше» (Q&A, блок 3).
            bound = max(order.window_start_min, earliest_shift)
            time_dim.SetCumulVarSoftUpperBound(index, bound, URGENT_LATENESS_WEIGHT)

    # ---- смены инженеров
    for vehicle, engineer in enumerate(engineers):
        state = starts.get(engineer.id)
        available = state.available_min if state else engineer.shift_start_min
        start_index = routing.Start(vehicle)
        time_dim.CumulVar(start_index).SetRange(available, available)
        time_dim.CumulVar(routing.End(vehicle)).SetMax(engineer.shift_end_min)

    # ---- квалификация и транспорт: список допустимых исполнителей по заявке.
    # Задаём через VehicleVar, а не SetAllowedVehiclesForIndex: в ortools 9.15
    # обёртка последнего не принимает списки Python. Значение -1 оставляет
    # заявке возможность остаться невыполненной (её цену задаёт дизъюнкция).
    for order in servable:
        allowed = [
            vehicle
            for vehicle, engineer in enumerate(engineers)
            if check_static(engineer, order) is None
        ]
        index = manager.NodeToIndex(node_of_order[order.id])
        routing.VehicleVar(index).SetValues([-1, *allowed])
        routing.AddDisjunction([index], _drop_penalty(order))

    # ---- оборудование: то, что взято утром, нельзя израсходовать дважды
    # (ответ экспертов, п.4). Для модели это обычная вместимость: у каждого
    # вида оборудования своя размерность, потребности заявок складываются
    # вдоль маршрута и не могут превысить утренний запас инженера. При
    # перепланировании запас уменьшается на уже израсходованное до события.
    for kind in geo.equipment.kinds:
        demand = np.zeros(total_nodes, dtype=np.int64)
        for order in servable:
            demand[node_of_order[order.id]] = geo.equipment_needs(order.id).get(kind, 0)
        if not demand.any():
            continue

        def make_demand_callback(row: np.ndarray):
            def callback(index: int) -> int:
                return int(row[manager.IndexToNode(index)])

            return callback

        capacities = []
        for engineer in engineers:
            left = geo.equipment_stock(engineer.id).get(kind, 0)
            state = starts.get(engineer.id)
            if state is not None:
                for stop in state.locked_stops:
                    left -= geo.equipment_needs(stop.order_id).get(kind, 0)
            capacities.append(max(0, left))

        routing.AddDimensionWithVehicleCapacity(
            routing.RegisterUnaryTransitCallback(make_demand_callback(demand)),
            0,
            capacities,
            True,  # запас считается с нуля на старте маршрута
            f"Equipment:{kind}",
        )

    if params.objective == "min_engineers":
        routing.SetFixedCostOfAllVehicles(ENGINEER_FIXED_COST)

    if params.lunch:
        _add_lunch_breaks(routing, manager, time_dim, engineers, service_min, starts)

    search = pywrapcp.DefaultRoutingSearchParameters()
    search.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    search.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    search.time_limit.FromSeconds(max(1, params.time_limit_s))
    search.log_search = False

    solution = None
    if previous:
        initial = _initial_routes(engineers, previous, node_of_order)
        if any(initial):
            candidate = routing.ReadAssignmentFromRoutes(initial, True)
            if candidate is not None:
                solution = routing.SolveFromAssignmentWithParameters(candidate, search)
    if solution is None:
        solution = routing.SolveWithParameters(search)

    assignment: dict[str, list[str]] = {e.id: [] for e in scenario.engineers}
    if solution is None:
        return SolveResult(assignment, [o.id for o in pool], prefiltered, "NO_SOLUTION")

    order_by_node = {index: order.id for order, index in
                     ((o, node_of_order[o.id]) for o in servable)}
    assigned: set[str] = set()
    for vehicle, engineer in enumerate(engineers):
        index = routing.Start(vehicle)
        sequence: list[str] = []
        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            if node < depot_offset:
                sequence.append(order_by_node[node])
            index = solution.Value(routing.NextVar(index))
        assignment[engineer.id] = sequence
        assigned.update(sequence)

    unassigned_ids = [o.id for o in pool if o.id not in assigned]
    return SolveResult(assignment, unassigned_ids, prefiltered, routing.status())


def _initial_routes(
    engineers: list[Engineer], previous: dict[str, str], node_of_order: dict[str, int]
) -> list[list[int]]:
    """Прошлый план как стартовое решение: ускоряет поиск и повышает стабильность."""
    by_engineer: dict[str, list[int]] = {e.id: [] for e in engineers}
    for order_id, engineer_id in previous.items():
        if engineer_id in by_engineer and order_id in node_of_order:
            by_engineer[engineer_id].append(node_of_order[order_id])
    return [by_engineer[e.id] for e in engineers]


def _add_lunch_breaks(routing, manager, time_dim, engineers, service_min, starts) -> None:
    """Необязательный обед: 45 минут в окне 13:00–15:00 (Q&A, блок 5)."""
    node_visit = [int(service_min[manager.IndexToNode(i)]) if i < len(service_min) else 0
                  for i in range(routing.Size())]
    solver = routing.solver()
    for vehicle, engineer in enumerate(engineers):
        if engineer.shift_start_min > 13 * 60 or engineer.shift_end_min < 15 * 60:
            continue
        interval = solver.FixedDurationIntervalVar(
            13 * 60, 15 * 60 - 45, 45, False, f"обед {engineer.id}"
        )
        time_dim.SetBreakIntervalsOfVehicle([interval], vehicle, node_visit)


def plan(
    scenario: Scenario,
    geo: Geo | None = None,
    params: PlanParams | None = None,
    plan_id: str = "optimized",
    starts: dict[str, StartState] | None = None,
    order_ids: list[str] | None = None,
    previous: dict[str, str] | None = None,
) -> Plan:
    """Полный план: решение солвера, пересчитанное валидатором и объяснённое.

    В режиме «auto» задача решается дважды — с платой за выход инженера и без
    неё — и выбирается лучший результат по лексикографической цели. Когда штат
    сократить нельзя, плата за инженера становится константой, но сбивает
    направленный поиск, и вариант без неё даёт заметно более короткие маршруты.
    """
    geo = geo or Geo(scenario)
    params = params or PlanParams()

    if params.objective == "auto":
        budget = max(1, params.time_limit_s // 2)
        best: Plan | None = None
        for objective in ("min_engineers", "min_distance"):
            attempt = plan(
                scenario,
                geo,
                params.model_copy(update={"objective": objective, "time_limit_s": budget}),
                plan_id,
                starts,
                order_ids,
                previous,
            )
            if best is None or metrics_module.is_better(attempt.metrics, best.metrics):
                best = attempt
        assert best is not None
        # В плане остаётся победивший режим и исходный бюджет времени.
        best.params = best.params.model_copy(update={"time_limit_s": params.time_limit_s})
        return best

    result = solve(scenario, geo, params, starts, order_ids, previous)

    routes, violations = evaluate(
        geo, result.assignment, starts, allow_late=params.allow_reschedule and bool(starts)
    )
    if violations:
        raise AssertionError(
            "солвер вернул недопустимый план: " + "; ".join(v.text for v in violations[:3])
        )

    unassigned = reasons.diagnose_all(geo, result.unassigned_ids, routes, starts)
    planned_from = (
        min_to_hhmm(min(s.available_min for s in starts.values()))
        if starts
        else min((e.shift_start for e in scenario.engineers), default="00:00")
    )
    result_plan = Plan(
        id=plan_id,
        scenario_id=scenario.id,
        kind="optimized",
        # Фиксируем, какая модель движения фактически использовалась:
        # при недоступном OSRM сервис молча работает на офлайн-оценке,
        # и это должно быть видно в плане, а не только в логе.
        params=params.model_copy(update={"travel_model": geo.travel.name}),
        planned_from=planned_from,
        routes=routes,
        unassigned=unassigned,
    )
    result_plan.metrics = metrics_module.compute(
        scenario, routes, unassigned, reasons.extra_engineers_needed(geo, unassigned)
    )
    return result_plan
