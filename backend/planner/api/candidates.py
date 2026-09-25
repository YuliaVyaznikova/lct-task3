"""Варианты ручного переназначения заявки для диспетчера."""

from __future__ import annotations

from planner.core.models import Plan, Route
from planner.core.validate import Geo, best_insertion, evaluate_route, first_blocking_violation


def _changed_starts(before: list[Route], after: list[Route]) -> list[dict[str, str]]:
    old = {stop.order_id: stop.start for route in before for stop in route.stops}
    return [
        {"order_id": stop.order_id, "from_start": old[stop.order_id], "to_start": stop.start}
        for route in after
        for stop in route.stops
        if stop.order_id in old and stop.start != old[stop.order_id]
    ]


def list_candidates(geo: Geo, plan: Plan, order_id: str) -> list[dict]:
    """Проверить каждую бригаду и показать результат лучшей вставки."""
    routes_by_engineer = plan.routes_by_engineer
    donor_id = plan.assignment.get(order_id)
    donor_before = routes_by_engineer.get(donor_id) if donor_id else None
    donor_after = None
    donor_removed_km = 0.0
    if donor_before is not None:
        donor = geo.engineers[donor_id]
        without = [current for current in donor_before.order_ids if current != order_id]
        donor_after, _ = evaluate_route(geo, donor, without, lunch=plan.params.lunch)
        donor_removed_km = round(donor_before.distance_km - donor_after.distance_km, 3)

    rows = []
    for engineer in geo.scenario.engineers:
        receiver_before = routes_by_engineer.get(engineer.id)
        receiver_order_ids = receiver_before.order_ids if receiver_before else []
        without_order = [current for current in receiver_order_ids if current != order_id]
        found = best_insertion(geo, engineer, without_order, order_id, lunch=plan.params.lunch)
        if found is None:
            blocking = first_blocking_violation(
                geo, engineer, without_order, order_id, lunch=plan.params.lunch
            )
            rows.append({
                "engineer_id": engineer.id,
                "feasible": False,
                "reason_code": blocking.code if blocking else "CAPACITY",
                "reason": blocking.text if blocking else "Заявка не помещается в маршрут",
                "position": None,
                "arrival": None,
                "start": None,
                "added_km": None,
                "donor_removed_km": donor_removed_km,
                "total_delta_km": None,
                "shifted": [],
                "preview_routes": {},
            })
            continue

        position, _ = found
        preview_ids = [*without_order[:position], order_id, *without_order[position:]]
        receiver_after, _ = evaluate_route(geo, engineer, preview_ids, lunch=plan.params.lunch)
        receiver_without_order, _ = evaluate_route(
            geo, engineer, without_order, lunch=plan.params.lunch
        )
        added_km = round(receiver_after.distance_km - receiver_without_order.distance_km, 3)
        if engineer.id == donor_id:
            routes_before = [donor_before] if donor_before else []
            routes_after = [receiver_after]
        else:
            routes_before = [route for route in (donor_before, receiver_before) if route is not None]
            routes_after = [route for route in (donor_after, receiver_after) if route is not None]
        stop = next(stop for stop in receiver_after.stops if stop.order_id == order_id)
        preview_routes = {engineer.id: preview_ids}
        if donor_id and donor_id != engineer.id:
            preview_routes[donor_id] = donor_after.order_ids if donor_after else []
        rows.append({
            "engineer_id": engineer.id,
            "feasible": True,
            "reason_code": None,
            "reason": None,
            "position": position,
            "arrival": stop.arrival,
            "start": stop.start,
            "added_km": added_km,
            "donor_removed_km": donor_removed_km,
            "total_delta_km": round(added_km - donor_removed_km, 3),
            "shifted": _changed_starts(routes_before, routes_after),
            "preview_routes": preview_routes,
        })

    rows.sort(key=lambda row: (not row["feasible"], row["total_delta_km"] if row["feasible"] else 0))
    return rows
