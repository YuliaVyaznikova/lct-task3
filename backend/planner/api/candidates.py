"""Варианты ручного переназначения заявки для диспетчера."""

from __future__ import annotations

import copy

from planner.core.models import Plan, Priority, Route
from planner.core.timeutil import hhmm_to_min
from planner.core.validate import Geo, best_insertion, check_static, evaluate_route, first_blocking_violation

CLIENT_WINDOWS = [(f"{hour:02d}:00", f"{hour + 2:02d}:00") for hour in range(10, 22, 2)]


def _changed_starts(before: list[Route], after: list[Route]) -> list[dict[str, str]]:
    old = {stop.order_id: stop.start for route in before for stop in route.stops}
    return [
        {"order_id": stop.order_id, "from_start": old[stop.order_id], "to_start": stop.start}
        for route in after
        for stop in route.stops
        if stop.order_id in old and stop.start != old[stop.order_id]
    ]


def _without(order_ids: list[str], order_id: str) -> list[str]:
    return [current for current in order_ids if current != order_id]


def _blocked_row(
    geo: Geo, engineer, without_order: list[str], order_id: str, lunch, donor_removed_km: float
) -> dict:
    blocking = first_blocking_violation(geo, engineer, without_order, order_id, lunch=lunch)
    return {
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
    }


def _feasible_row(
    geo: Geo,
    plan: Plan,
    engineer,
    order_id: str,
    position: int,
    without_order: list[str],
    donor_before: Route | None,
    donor_after: Route | None,
    donor_removed_km: float,
) -> dict:
    lunch = plan.params.lunch
    donor_id = plan.assignment.get(order_id)
    receiver_before = plan.routes_by_engineer.get(engineer.id)

    preview_ids = [*without_order[:position], order_id, *without_order[position:]]
    receiver_after, _ = evaluate_route(geo, engineer, preview_ids, lunch=lunch)
    receiver_without_order, _ = evaluate_route(geo, engineer, without_order, lunch=lunch)
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

    return {
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
    }


def list_candidates(geo: Geo, plan: Plan, order_id: str) -> list[dict]:
    """Проверить каждую бригаду и показать результат лучшей вставки."""
    lunch = plan.params.lunch
    routes_by_engineer = plan.routes_by_engineer
    donor_id = plan.assignment.get(order_id)
    donor_before = routes_by_engineer.get(donor_id) if donor_id else None
    donor_after = None
    donor_removed_km = 0.0
    if donor_before is not None:
        without = _without(donor_before.order_ids, order_id)
        donor_after, _ = evaluate_route(geo, geo.engineers[donor_id], without, lunch=lunch)
        donor_removed_km = round(donor_before.distance_km - donor_after.distance_km, 3)

    rows = []
    for engineer in geo.scenario.engineers:
        receiver_before = routes_by_engineer.get(engineer.id)
        receiver_order_ids = receiver_before.order_ids if receiver_before else []
        without_order = _without(receiver_order_ids, order_id)

        found = best_insertion(geo, engineer, without_order, order_id, lunch=lunch)
        if found is None:
            rows.append(_blocked_row(geo, engineer, without_order, order_id, lunch, donor_removed_km))
            continue
        rows.append(_feasible_row(
            geo, plan, engineer, order_id, found[0], without_order,
            donor_before, donor_after, donor_removed_km,
        ))

    rows.sort(key=lambda row: (not row["feasible"], row["total_delta_km"] if row["feasible"] else 0))
    return rows


def _other_windows(order, planned_from: str) -> list[tuple[str, str]]:
    own = order.window_start_min
    earliest = max(hhmm_to_min(planned_from), own if order.priority is Priority.URGENT else 0)
    return sorted(
        (
            window for window in CLIENT_WINDOWS
            if window[0] != order.window_start and hhmm_to_min(window[0]) >= earliest
        ),
        key=lambda window: (abs(hhmm_to_min(window[0]) - own), hhmm_to_min(window[0]) < own),
    )


def nearest_window(geo: Geo, plan: Plan, order_id: str) -> dict:
    """Ближайшее другое окно сегодня, куда заявка встаёт, не сдвигая обещанное другим клиентам."""
    order = geo.orders[order_id]
    engineers = [e for e in geo.scenario.engineers if check_static(e, order) is None]
    empty = {"available": False, "window_start": None, "window_end": None, "engineer_id": None, "start": None}
    if not engineers:
        return {**empty, "text": "Другое окно не поможет: у инженеров нет нужного навыка или транспорта."}

    routes = plan.routes_by_engineer
    for window_start, window_end in _other_windows(order, plan.planned_from):
        shifted = copy.copy(geo)
        shifted.orders = {
            **geo.orders,
            order_id: order.model_copy(update={"window_start": window_start, "window_end": window_end}),
        }
        best = None
        for engineer in engineers:
            current = [item for item in (routes[engineer.id].order_ids if engineer.id in routes else []) if item != order_id]
            found = best_insertion(shifted, engineer, current, order_id, lunch=plan.params.lunch)
            if found is not None and (best is None or found[1] < best[1]):
                best = (engineer, found[1], [*current[:found[0]], order_id, *current[found[0]:]])
        if best is None:
            continue
        engineer, added_km, sequence = best
        route, _ = evaluate_route(shifted, engineer, sequence, lunch=plan.params.lunch)
        stop = next(item for item in route.stops if item.order_id == order_id)
        return {
            "available": True,
            "window_start": window_start,
            "window_end": window_end,
            "engineer_id": engineer.id,
            "start": stop.start,
            "text": (
                f"Ближайшее свободное окно {window_start}–{window_end}: {engineer.name} может начать в {stop.start}, "
                f"остальные визиты остаются в своих окнах."
            ),
        }
    return {**empty, "text": "Сегодня свободного окна для этой заявки нет."}
