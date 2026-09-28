"""Оптимизатор распределения и маршрутов на Google OR-Tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from multiprocessing import get_context
from queue import Empty
from time import monotonic
from typing import Callable

import numpy as np
from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from planner.core import metrics as metrics_module
from planner.core import reasons
from planner.core import zones
from planner.core.models import (
    Engineer,
    Order,
    Plan,
    PlanParams,
    Priority,
    ReasonCode,
    Scenario,
    Transport,
    Unassigned,
)
from planner.core.timeutil import min_to_hhmm
from planner.core.validate import Geo, StartState, check_static, evaluate

DROP_PENALTY_BY_TIER = {
    1: 10_000_000,
    2: 2_000_000,
    3: 1_000_000,
}

ENGINEER_FIXED_COST = 100_000

URGENT_LATENESS_WEIGHT = 50

LIVE_URGENT_LATENESS_WEIGHT = 1_000

RESCHEDULE_WEIGHT = 5_000

ZONE_SWITCH_PENALTY_M = 30_000

BALANCE_WEIGHT = 300

BALANCE_PHASE_S = 6

HORIZON_MIN = 1_800


@dataclass
class SolveResult:
    assignment: dict[str, list[str]]
    unassigned_ids: list[str]
    dropped_by_prefilter: list[str] = field(default_factory=list)
    status: str = ""


ProgressCallback = Callable[[dict], None]


def transit_matrices(
    distance_m: np.ndarray,
    time_by_transport: dict[Transport, np.ndarray],
    service_min: np.ndarray,
    zone_of_node: list[int],
    dummy_end: int,
) -> tuple[np.ndarray, dict[Transport, np.ndarray]]:
    """Матрицы содержат ровно те же слагаемые, что прежние дуговые callbacks."""
    distance = distance_m.copy()
    for i in range(len(zone_of_node)):
        for j in range(dummy_end):
            if zone_of_node[i] != zone_of_node[j]:
                distance[i, j] += ZONE_SWITCH_PENALTY_M
    times = {
        transport: matrix + service_min[:, np.newaxis]
        for transport, matrix in time_by_transport.items()
    }
    return distance, times


def vehicle_distance_matrix(
    distance: np.ndarray,
    previous_vehicle: dict[int, str],
    engineer_id: str,
    stability: int,
) -> np.ndarray:
    """Доплата за передачу заявки другому инженеру при перепланировании."""
    adjusted = distance.copy()
    for node, previous_engineer in previous_vehicle.items():
        if previous_engineer != engineer_id:
            adjusted[:, node] += stability
    return adjusted


def _drop_penalty(order) -> int:
    """Цена отказа от заявки: чем выше ярус, тем дороже её не выполнить."""
    tier = getattr(order, "priority_tier", 3)
    if order.priority is Priority.URGENT:
        tier = min(tier, 1)
    return DROP_PENALTY_BY_TIER.get(tier, DROP_PENALTY_BY_TIER[3])


def _lateness_weight(order: Order) -> int:
    """Авария, пришедшая в течение дня, ждёт дороже аварии из утренней выгрузки."""
    if order.attributes.get("reported_live"):
        return LIVE_URGENT_LATENESS_WEIGHT
    return URGENT_LATENESS_WEIGHT


def _capable(scenario: Scenario, order) -> list[Engineer]:
    return [e for e in scenario.engineers if check_static(e, order) is None]


def _travel_nodes(
    geo: Geo, orders: list[Order], engineers: list[Engineer], starts: dict[str, StartState]
) -> tuple[list[int], list[int]]:
    geo_nodes = [geo.node(order.id) for order in orders]
    start_nodes: list[int] = []
    for engineer in engineers:
        state = starts.get(engineer.id)
        geo_node = state.node if state else geo.start_node(engineer)
        start_nodes.append(len(geo_nodes))
        geo_nodes.append(geo_node)
    return geo_nodes, start_nodes


def _register_travel(
    routing,
    geo: Geo,
    geo_nodes: list[int],
    engineers: list[Engineer],
    service_min: np.ndarray,
    previous_vehicle: dict[int, str],
    stability: int,
) -> list[int]:
    dummy_end = len(geo_nodes)
    total_nodes = dummy_end + 1
    distance_m = np.zeros((total_nodes, total_nodes), dtype=np.int64)
    distance_m[:dummy_end, :dummy_end] = geo.travel.distance_m()[np.ix_(geo_nodes, geo_nodes)]

    time_by_transport: dict[Transport, np.ndarray] = {}
    for transport in {engineer.transport for engineer in engineers}:
        matrix = np.zeros((total_nodes, total_nodes), dtype=np.int64)
        matrix[:dummy_end, :dummy_end] = geo.travel.time_min(transport)[np.ix_(geo_nodes, geo_nodes)]
        time_by_transport[transport] = matrix

    zone_of_node = [geo.zone(node) for node in geo_nodes] + [zones.BASE_ZONE]
    distance_matrix, time_matrices = transit_matrices(
        distance_m, time_by_transport, service_min, zone_of_node, dummy_end
    )
    time_indices = {
        transport: routing.RegisterTransitMatrix(matrix.tolist())
        for transport, matrix in time_matrices.items()
    }
    distance_index = routing.RegisterTransitMatrix(distance_matrix.tolist())
    stability_indices: dict[str, int] = {}
    time_callback_indices = []
    for vehicle, engineer in enumerate(engineers):
        cost_index = distance_index
        if stability and previous_vehicle:
            if engineer.id not in stability_indices:
                adjusted = vehicle_distance_matrix(
                    distance_matrix, previous_vehicle, engineer.id, stability
                )
                stability_indices[engineer.id] = routing.RegisterTransitMatrix(adjusted.tolist())
            cost_index = stability_indices[engineer.id]
        routing.SetArcCostEvaluatorOfVehicle(cost_index, vehicle)
        time_callback_indices.append(time_indices[engineer.transport])
    return time_callback_indices


def _add_time_constraints(
    routing,
    manager,
    engineers: list[Engineer],
    orders: list[Order],
    node_of_order: dict[str, int],
    starts: dict[str, StartState],
    params: PlanParams,
    time_callback_indices: list[int],
):
    routing.AddDimensionWithVehicleTransits(
        time_callback_indices, HORIZON_MIN, HORIZON_MIN, False, "Time"
    )
    time_dim = routing.GetDimensionOrDie("Time")
    earliest_shift = min(
        (starts[e.id].available_min if e.id in starts else e.shift_start_min) for e in engineers
    )
    allow_reschedule = params.allow_reschedule and bool(starts)
    for order in orders:
        index = manager.NodeToIndex(node_of_order[order.id])
        if allow_reschedule:
            latest = max(order.window_end_min, max(e.shift_end_min for e in engineers))
            time_dim.CumulVar(index).SetRange(order.window_start_min, latest)
            time_dim.SetCumulVarSoftUpperBound(index, order.window_end_min, RESCHEDULE_WEIGHT)
        else:
            time_dim.CumulVar(index).SetRange(order.window_start_min, order.window_end_min)
        if order.priority is Priority.URGENT:
            bound = max(order.window_start_min, earliest_shift)
            time_dim.SetCumulVarSoftUpperBound(index, bound, _lateness_weight(order))

    for vehicle, engineer in enumerate(engineers):
        state = starts.get(engineer.id)
        available = state.available_min if state else engineer.shift_start_min
        start_index = routing.Start(vehicle)
        time_dim.CumulVar(start_index).SetRange(available, available)
        time_dim.CumulVar(routing.End(vehicle)).SetMax(engineer.shift_end_min)
    return time_dim


def _add_load_balance(
    routing, engineers: list[Engineer], starts: dict[str, StartState], time_callback_indices: list[int]
) -> None:
    """Штраф за самую большую загрузку: работа расходится по инженерам ровнее."""
    routing.AddDimensionWithVehicleTransits(time_callback_indices, 0, HORIZON_MIN, False, "Load")
    load_dim = routing.GetDimensionOrDie("Load")
    for vehicle, engineer in enumerate(engineers):
        state = starts.get(engineer.id)
        done = state.work_min + state.travel_min if state else 0
        load_dim.CumulVar(routing.Start(vehicle)).SetValue(done)
    load_dim.SetGlobalSpanCostCoefficient(BALANCE_WEIGHT)


def _add_order_constraints(
    routing, manager, engineers: list[Engineer], orders: list[Order], node_of_order: dict[str, int]
) -> None:
    for order in orders:
        allowed = [
            vehicle for vehicle, engineer in enumerate(engineers)
            if check_static(engineer, order) is None
        ]
        index = manager.NodeToIndex(node_of_order[order.id])
        routing.VehicleVar(index).SetValues([-1, *allowed])
        routing.AddDisjunction([index], _drop_penalty(order))


def _add_equipment_constraints(
    routing,
    manager,
    geo: Geo,
    engineers: list[Engineer],
    orders: list[Order],
    node_of_order: dict[str, int],
    starts: dict[str, StartState],
    total_nodes: int,
) -> None:
    for kind in geo.equipment.kinds:
        demand = np.zeros(total_nodes, dtype=np.int64)
        for order in orders:
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
            0, capacities, True, f"Equipment:{kind}",
        )


def _search_parameters(params: PlanParams):
    search = pywrapcp.DefaultRoutingSearchParameters()
    search.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    search.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    search.time_limit.FromSeconds(max(1, params.time_limit_s))
    search.log_search = False
    return search


def _route_sequences(
    routing,
    manager,
    engineers: list[Engineer],
    orders: list[Order],
    next_index: Callable[[int], int],
) -> dict[str, list[str]]:
    sequences: dict[str, list[str]] = {}
    for vehicle, engineer in enumerate(engineers):
        index = routing.Start(vehicle)
        sequence: list[str] = []
        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            if node < len(orders):
                sequence.append(orders[node].id)
            index = next_index(index)
        sequences[engineer.id] = sequence
    return sequences


def _solve_model(routing, search, engineers, previous, node_of_order, seed=None):
    candidates = []
    if seed:
        candidates.append(_seed_routes(engineers, seed, node_of_order))
    if previous:
        candidates.append(_initial_routes(engineers, previous, node_of_order))
    for initial in candidates:
        if any(initial):
            candidate = routing.ReadAssignmentFromRoutes(initial, True)
            if candidate is not None:
                solution = routing.SolveFromAssignmentWithParameters(candidate, search)
                if solution is not None:
                    return solution
    return routing.SolveWithParameters(search)


def solve(
    scenario: Scenario,
    geo: Geo | None = None,
    params: PlanParams | None = None,
    starts: dict[str, StartState] | None = None,
    order_ids: list[str] | None = None,
    previous: dict[str, str] | None = None,
    on_progress: ProgressCallback | None = None,
    seed: dict[str, list[str]] | None = None,
) -> SolveResult:
    """Строит распределение."""
    geo = geo or Geo(scenario)
    params = params or PlanParams()
    starts = starts or {}
    previous = previous or {}

    if order_ids is None:
        order_ids = [o.id for o in scenario.orders]
    pool = [geo.orders[order_id] for order_id in order_ids]
    engineers = [
        e
        for e in scenario.engineers
        if not (e.id in starts and starts[e.id].closed)
    ]

    servable = [o for o in pool if _capable(scenario, o)]
    prefiltered = [o.id for o in pool if o not in servable]
    if not servable or not engineers:
        return SolveResult({e.id: [] for e in engineers}, [o.id for o in pool], prefiltered, "EMPTY")

    node_of_order = {order.id: i for i, order in enumerate(servable)}
    geo_nodes, start_nodes = _travel_nodes(geo, servable, engineers, starts)
    dummy_end = len(geo_nodes)
    total_nodes = dummy_end + 1

    service_min = np.zeros(total_nodes, dtype=np.int64)
    for order in servable:
        service_min[node_of_order[order.id]] = order.duration_min

    manager = pywrapcp.RoutingIndexManager(
        total_nodes, len(engineers), start_nodes, [dummy_end] * len(engineers)
    )
    routing = pywrapcp.RoutingModel(manager)

    previous_vehicle = {
        node_of_order[order_id]: engineer_id
        for order_id, engineer_id in previous.items()
        if order_id in node_of_order
    }
    time_callback_indices = _register_travel(
        routing, geo, geo_nodes, engineers, service_min,
        previous_vehicle, params.stability_weight_m,
    )
    time_dim = _add_time_constraints(
        routing, manager, engineers, servable, node_of_order, starts, params, time_callback_indices
    )
    _add_order_constraints(routing, manager, engineers, servable, node_of_order)
    _add_equipment_constraints(
        routing, manager, geo, engineers, servable, node_of_order, starts, total_nodes
    )

    if params.objective == "min_engineers":
        routing.SetFixedCostOfAllVehicles(ENGINEER_FIXED_COST)

    if params.objective == "balanced":
        _add_load_balance(routing, engineers, starts, time_callback_indices)

    if params.lunch:
        _add_lunch_breaks(routing, manager, time_dim, engineers, service_min, starts)

    search = _search_parameters(params)

    started = monotonic()
    last_improvement = started
    best_cost: int | None = None
    last_published = float("-inf")
    best_metrics = None

    def at_solution() -> None:
        nonlocal last_improvement, best_cost, last_published, best_metrics
        now = monotonic()
        cost = routing.CostVar().Value()
        if best_cost is not None and cost >= best_cost:
            return
        best_cost = cost
        last_improvement = now
        if on_progress is None or now - last_published < 0.25:
            return

        snapshot = _route_sequences(
            routing, manager, engineers, servable,
            lambda index: routing.NextVar(index).Value(),
        )
        routes, violations = evaluate(
            geo, snapshot, starts,
            allow_late=params.allow_reschedule and bool(starts),
            lunch=params.lunch,
        )
        if violations:
            return
        assigned = {stop.order_id for route in routes for stop in route.stops}
        missing = [
            Unassigned(order_id=o.id, reason_code=ReasonCode.CAPACITY, reason="")
            for o in pool if o.id not in assigned
        ]
        current = metrics_module.compute(scenario, routes, missing)
        if best_metrics is not None and not metrics_module.is_better(current, best_metrics):
            return
        best_metrics = current
        last_published = now
        on_progress({
            "elapsed_s": round(now - started, 3),
            "variant": params.objective,
            "assigned": current.assigned,
            "total": len(scenario.orders),
            "engineers_used": current.engineers_used,
            "distance_km": current.distance_total_km,
            "routes": {route.engineer_id: route.order_ids for route in routes},
        })
    routing.AddAtSolutionCallback(at_solution)

    class IdleLimit(pywrapcp.SearchMonitor):
        def __init__(self):
            super().__init__(routing.solver())

        def BeginNextDecision(self, decision) -> None:
            if best_cost is not None and monotonic() - last_improvement >= params.no_improve_s:
                self.solver().FinishCurrentSearch()

    idle_limit = IdleLimit()
    routing.AddSearchMonitor(idle_limit)

    solution = _solve_model(routing, search, engineers, previous, node_of_order, seed)

    assignment: dict[str, list[str]] = {e.id: [] for e in scenario.engineers}
    if solution is None:
        return SolveResult(assignment, [o.id for o in pool], prefiltered, "NO_SOLUTION")

    assignment.update(_route_sequences(
        routing, manager, engineers, servable,
        lambda index: solution.Value(routing.NextVar(index)),
    ))
    assigned = {order_id for sequence in assignment.values() for order_id in sequence}
    unassigned_ids = [o.id for o in pool if o.id not in assigned]
    return SolveResult(assignment, unassigned_ids, prefiltered, routing.status())


def _seed_routes(
    engineers: list[Engineer], seed: dict[str, list[str]], node_of_order: dict[str, int]
) -> list[list[int]]:
    """Готовое стартовое решение в порядке, который задал вызывающий."""
    return [
        [node_of_order[order_id] for order_id in seed.get(e.id, []) if order_id in node_of_order]
        for e in engineers
    ]


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
    """Необязательный обед: 45 минут в окне 13:00–15:00."""
    node_visit = [int(service_min[manager.IndexToNode(i)]) if i < len(service_min) else 0
                  for i in range(routing.Size())]
    solver = routing.solver()
    for vehicle, engineer in enumerate(engineers):
        state = starts.get(engineer.id)
        if state is not None and state.lunch_break is not None:
            continue
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
    on_progress: ProgressCallback | None = None,
    seed: dict[str, list[str]] | None = None,
) -> Plan:
    """Полный план: решение солвера, пересчитанное валидатором и объяснённое."""
    geo = geo or Geo(scenario)
    params = params or PlanParams()

    if params.objective == "auto":
        attempts = parallel_plans(
            scenario, params, ("min_engineers", "min_distance"), plan_id,
            starts, order_ids, previous, on_progress, seed,
        )
        best = attempts[0]
        for attempt in attempts[1:]:
            if metrics_module.is_better(attempt.metrics, best.metrics):
                best = attempt
        return best

    if params.objective == "balanced" and seed is None:
        first = solve(
            scenario, geo, params.model_copy(update={"objective": "min_distance"}),
            starts, order_ids, previous, on_progress,
        )
        seed = first.assignment
        params = params.model_copy(update={"time_limit_s": BALANCE_PHASE_S})

    result = solve(scenario, geo, params, starts, order_ids, previous, on_progress, seed)

    routes, violations = evaluate(
        geo, result.assignment, starts, allow_late=params.allow_reschedule and bool(starts),
        lunch=params.lunch,
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
        params=params.model_copy(update={"travel_model": geo.travel.name}),
        planned_from=planned_from,
        routes=routes,
        unassigned=unassigned,
    )
    result_plan.metrics = metrics_module.compute(
        scenario, routes, unassigned, reasons.extra_engineers_needed(geo, unassigned)
    )
    return result_plan


def balance(
    scenario: Scenario,
    geo: Geo,
    params: PlanParams,
    start_from: Plan,
    plan_id: str = "balanced",
    on_progress: ProgressCallback | None = None,
) -> Plan:
    """Выравнивает загрузку готового плана, не теряя его заявок."""
    return plan(
        scenario, geo,
        params.model_copy(update={"objective": "balanced", "time_limit_s": BALANCE_PHASE_S}),
        plan_id=plan_id,
        on_progress=on_progress,
        seed={route.engineer_id: route.order_ids for route in start_from.routes},
    )


def _plan_worker(queue, scenario, params, objective, plan_id, starts, order_ids, previous, seed) -> None:
    """Отдельный процесс для одного варианта поиска."""
    try:
        attempt = plan(
            scenario, params=params.model_copy(update={"objective": objective}),
            plan_id=plan_id, starts=starts, order_ids=order_ids, previous=previous,
            on_progress=lambda snapshot: queue.put(("progress", objective, snapshot)), seed=seed,
        )
        queue.put(("done", objective, attempt.model_dump(mode="json")))
    except Exception as exc:
        queue.put(("error", objective, f"{type(exc).__name__}: {exc}"))


def parallel_plans(
    scenario: Scenario,
    params: PlanParams,
    objectives: tuple[str, ...],
    plan_id: str,
    starts: dict[str, StartState] | None = None,
    order_ids: list[str] | None = None,
    previous: dict[str, str] | None = None,
    on_progress: ProgressCallback | None = None,
    seed: dict[str, list[str]] | None = None,
) -> list[Plan]:
    """Считает независимые цели одновременно и возвращает их в заданном порядке."""
    context = get_context("spawn")
    queue = context.Queue()
    workers = [
        context.Process(
            target=_plan_worker,
            args=(queue, scenario, params, objective, plan_id, starts, order_ids, previous, seed),
        )
        for objective in objectives
    ]
    results: dict[str, Plan] = {}
    errors: list[str] = []
    try:
        for worker in workers:
            worker.start()
        while len(results) + len(errors) < len(workers):
            try:
                kind, objective, payload = queue.get(timeout=0.2)
            except Empty:
                if not any(worker.is_alive() for worker in workers):
                    break
                continue
            if kind == "progress" and on_progress is not None:
                on_progress(payload)
            elif kind == "done":
                results[objective] = Plan.model_validate(payload)
            elif kind == "error":
                errors.append(f"{objective}: {payload}")
        for worker in workers:
            worker.join()
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join()
        queue.close()
    if errors or len(results) != len(workers):
        raise RuntimeError("не удалось построить варианты: " + "; ".join(errors))
    return [results[objective] for objective in objectives]
