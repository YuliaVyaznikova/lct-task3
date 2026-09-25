"""Матрицы и промежуточные решения оптимизатора."""

from __future__ import annotations

import numpy as np
from ortools.constraint_solver import pywrapcp
from time import monotonic

from planner.core import solver
from planner.core.models import LunchBreak, PlanParams, Transport
from planner.core.validate import Geo, StartState
from tests.conftest import make_engineer, make_order, make_scenario


def test_registered_transit_matrices_match_old_arc_formulas():
    distance = np.array([
        [0, 100, 200, 0],
        [110, 0, 310, 0],
        [220, 320, 0, 0],
        [0, 0, 0, 0],
    ], dtype=np.int64)
    service = np.array([25, 40, 0, 0], dtype=np.int64)
    zones = [0, 1, 0, 0]
    raw_times = {
        transport: distance // divisor
        for transport, divisor in (
            (Transport.CAR, 10), (Transport.FOOT, 3),
            (Transport.BIKE, 5), (Transport.PUBLIC, 7),
        )
    }
    cost, times = solver.transit_matrices(distance, raw_times, service, zones, 3)

    transports = tuple(Transport)
    manager = pywrapcp.RoutingIndexManager(4, len(transports), [2] * len(transports), [3] * len(transports))
    routing = pywrapcp.RoutingModel(manager)
    cost_index = routing.RegisterTransitMatrix(cost.tolist())
    time_indices = [
        routing.RegisterTransitMatrix(times[transport].tolist())
        for transport in transports
    ]
    for vehicle in range(len(transports)):
        routing.SetArcCostEvaluatorOfVehicle(cost_index, vehicle)
    routing.AddDimensionWithVehicleTransits(time_indices, 0, 1000, True, "Time")
    dimension = routing.GetDimensionOrDie("Time")
    routing.CloseModel()

    for i in range(4):
        for j in range(4):
            old_distance = int(distance[i, j])
            if j != 3 and zones[i] != zones[j]:
                old_distance += solver.ZONE_SWITCH_PENALTY_M
            assert cost[i, j] == old_distance
            for transport in raw_times:
                assert times[transport][i, j] == service[i] + raw_times[transport][i, j]
            for engineer_id in ("E01", "E02"):
                adjusted = solver.vehicle_distance_matrix(cost, {0: "E01", 1: "E02"}, engineer_id, 3000)
                old_with_stability = old_distance + (
                    3000 if j in (0, 1) and ("E01" if j == 0 else "E02") != engineer_id else 0
                )
                assert adjusted[i, j] == old_with_stability

    for vehicle, transport in enumerate(transports):
        start = routing.Start(vehicle)
        for node in (0, 1):
            target = manager.NodeToIndex(node)
            assert routing.GetArcCostForVehicle(start, target, vehicle) == cost[2, node]
            assert dimension.GetTransitValue(start, target, vehicle) == times[transport][2, node]
            assert dimension.GetTransitValue(target, routing.End(vehicle), vehicle) == times[transport][node, 3]


def test_solution_callback_publishes_validator_metrics(toy, toy_geo):
    updates: list[dict] = []
    plan = solver.plan(
        toy, toy_geo,
        PlanParams(objective="min_engineers", time_limit_s=2, no_improve_s=1),
        on_progress=updates.append,
    )
    assert updates
    assert all(update["variant"] == "min_engineers" for update in updates)
    assert all(sum(map(len, update["routes"].values())) == update["assigned"] for update in updates)
    assert all(update["distance_km"] >= 0 for update in updates)
    assert all(update["total"] == len(toy.orders) for update in updates)


def test_idle_search_stops_before_upper_time_limit():
    scenario = make_scenario([make_order("A", 1)], [make_engineer("E01")])
    started = monotonic()
    plan = solver.plan(
        scenario, params=PlanParams(
            objective="min_engineers", time_limit_s=8, no_improve_s=1
        )
    )
    assert plan.metrics.assigned == 1
    assert monotonic() - started < 5


def test_replan_does_not_reserve_a_second_lunch():
    scenario = make_scenario(
        [make_order("A", 0, window=("14:00", "14:00"), duration=60)],
        [make_engineer("E01", shift=("09:00", "15:00"))],
    )
    geo = Geo(scenario)
    state = StartState(
        node=geo.start_node(scenario.engineers[0]),
        available_min=13 * 60 + 45,
        lunch_break=LunchBreak(start="13:00", finish="13:45"),
    )
    plan = solver.plan(
        scenario, geo, PlanParams(objective="min_engineers", time_limit_s=1, lunch=True),
        starts={"E01": state}, order_ids=["A"],
    )
    assert plan.assignment == {"A": "E01"}
    assert plan.routes[0].lunch_break == state.lunch_break
