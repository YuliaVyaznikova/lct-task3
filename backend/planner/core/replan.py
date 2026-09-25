"""Перепланирование после события."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from planner.core import explain as explain_module
from planner.core import solver
from planner.core.models import (
    CancelOrderEvent,
    Change,
    Diff,
    Engineer,
    EngineerDelayedEvent,
    EngineerUnavailableEvent,
    Event,
    LunchBreak,
    NewOrderEvent,
    Order,
    Plan,
    PlanParams,
    Priority,
    Route,
    Scenario,
    Stop,
    UrgentOrderEvent,
)
from planner.core.timeutil import hhmm_to_min, min_to_hhmm
from planner.core.validate import Geo, StartState

DEFAULT_STABILITY_M = 3000
DEFAULT_EVENT_BUDGET_S = 8

QUIET_STABILITY_M = 30_000


def _stability_for(event: Event) -> int:
    """Обычная заявка вписывается в свободное время, аварии позволено перестроить остаток дня."""
    if isinstance(event, NewOrderEvent) and event.order.priority is not Priority.URGENT:
        return QUIET_STABILITY_M
    return DEFAULT_STABILITY_M


class ReplanError(RuntimeError):
    """Событие невозможно применить к текущему плану."""


@dataclass
class Frozen:
    starts: dict[str, StartState]
    pool: list[str]
    locked_count: int


def _departure_min(stop: Stop, previous_finish: int | None) -> int:
    if stop.departure is not None:
        return hhmm_to_min(stop.departure)
    if previous_finish is not None:
        return previous_finish
    return hhmm_to_min(stop.arrival) - stop.travel_min


def _split_route(route: Route | None, at_min: int) -> tuple[list[Stop], list[str], LunchBreak | None]:
    if route is None:
        return [], [], None

    locked: list[Stop] = []
    pending: list[str] = []
    previous_finish: int | None = None
    for stop in route.stops:
        if _departure_min(stop, previous_finish) <= at_min:
            locked.append(stop.model_copy(update={"locked": True, "seq": len(locked) + 1}))
        else:
            pending.append(stop.order_id)
        previous_finish = hhmm_to_min(stop.finish)

    started_lunch = None
    if route.lunch_break is not None:
        break_start = hhmm_to_min(route.lunch_break.start)
        if break_start <= at_min or (locked and break_start < hhmm_to_min(locked[-1].finish)):
            started_lunch = route.lunch_break
    return locked, pending, started_lunch


def _frozen_start(
    geo: Geo,
    engineer: Engineer,
    locked: list[Stop],
    started_lunch: LunchBreak | None,
    at_min: int,
) -> StartState:
    lunch_finish = hhmm_to_min(started_lunch.finish) if started_lunch else at_min
    if locked:
        last = locked[-1]
        return StartState(
            node=geo.node(last.order_id),
            available_min=max(hhmm_to_min(last.finish), at_min, lunch_finish),
            locked_stops=locked,
            distance_km=round(sum(stop.travel_km for stop in locked), 3),
            travel_min=sum(stop.travel_min for stop in locked),
            work_min=sum(geo.orders[stop.order_id].duration_min for stop in locked),
            wait_min=sum(stop.wait_min for stop in locked),
            lunch_break=started_lunch,
        )
    return StartState(
        node=geo.start_node(engineer),
        available_min=max(at_min, engineer.shift_start_min, lunch_finish),
        lunch_break=started_lunch,
    )


def freeze(geo: Geo, plan: Plan, at_min: int) -> Frozen:
    """Делит план на неприкосновенное прошлое и пул заявок на пересчёт."""
    starts: dict[str, StartState] = {}
    pool: list[str] = []
    locked_count = 0

    for engineer in geo.scenario.engineers:
        route = next((r for r in plan.routes if r.engineer_id == engineer.id), None)
        locked, pending, started_lunch = _split_route(route, at_min)
        pool.extend(pending)
        locked_count += len(locked)
        starts[engineer.id] = _frozen_start(geo, engineer, locked, started_lunch, at_min)

    assigned = {s.order_id for r in plan.routes for s in r.stops}
    pool.extend(u.order_id for u in plan.unassigned if u.order_id not in assigned)
    return Frozen(starts=starts, pool=pool, locked_count=locked_count)


def remap_starts(geo: Geo, frozen: Frozen) -> None:
    """Переводит стартовые узлы заморозки в индексацию переданного `geo`."""
    for engineer_id, state in frozen.starts.items():
        if state.locked_stops:
            state.node = geo.node(state.locked_stops[-1].order_id)
        elif engineer_id in geo.engineers:
            state.node = geo.start_node(geo.engineers[engineer_id])


def _add_event_order(
    scenario: Scenario,
    pool: list[str],
    event: UrgentOrderEvent | NewOrderEvent,
    at_min: int,
) -> tuple[Geo, list[str], str]:
    order = event.order
    if isinstance(event, UrgentOrderEvent):
        order = order.model_copy(update={"priority": Priority.URGENT})
    if order.window_end_min < at_min:
        raise ReplanError(
            f"окно заявки {order.window_start}–{order.window_end} уже закрылось "
            f"к моменту события {event.time}"
        )
    if any(existing.id == order.id for existing in scenario.orders):
        raise ReplanError(f"заявка {order.id} уже есть в сценарии")
    if order.priority is Priority.URGENT and not order.attributes.get("reported_at"):
        order.attributes["reported_at"] = event.time
    scenario.orders.append(order)
    geo = Geo(scenario)
    pool.append(order.id)
    kind = "срочная заявка" if order.priority is Priority.URGENT else "новая заявка"
    return geo, pool, f"{kind} {order.id} ({order.address})"


def apply_event(
    scenario: Scenario, geo: Geo, frozen: Frozen, event: Event, at_min: int
) -> tuple[Geo, list[str], str]:
    """Меняет сценарий по событию."""
    pool = list(frozen.pool)

    if isinstance(event, (UrgentOrderEvent, NewOrderEvent)):
        return _add_event_order(scenario, pool, event, at_min)

    if isinstance(event, CancelOrderEvent):
        if event.order_id not in geo.orders:
            raise ReplanError(f"в сценарии нет заявки {event.order_id}")
        locked_ids = {
            stop.order_id for state in frozen.starts.values() for stop in state.locked_stops
        }
        if event.order_id in locked_ids:
            raise ReplanError(
                f"заявка {event.order_id} к {event.time} уже выполняется или выполнена — "
                "отменять нечего"
            )
        pool = [order_id for order_id in pool if order_id != event.order_id]
        return geo, pool, f"отмена заявки {event.order_id}"

    if isinstance(event, EngineerUnavailableEvent):
        if event.engineer_id not in geo.engineers:
            raise ReplanError(f"в сценарии нет инженера {event.engineer_id}")
        state = frozen.starts.get(event.engineer_id)
        if state is not None:
            state.closed = True
        name = geo.engineers[event.engineer_id].name
        return geo, pool, f"{name} недоступен с {event.time}"

    if isinstance(event, EngineerDelayedEvent):
        if event.engineer_id not in geo.engineers:
            raise ReplanError(f"в сценарии нет инженера {event.engineer_id}")
        state = frozen.starts[event.engineer_id]
        state.available_min = max(state.available_min, at_min + event.minutes)
        name = geo.engineers[event.engineer_id].name
        return geo, pool, f"{name} задержан с {event.time} на {event.minutes} мин"

    raise ReplanError(f"неизвестный тип события: {event!r}")


def replan(
    scenario: Scenario,
    plan: Plan,
    event: Event,
    geo: Geo | None = None,
    params: PlanParams | None = None,
    plan_id: str | None = None,
    on_progress: Callable[[dict], None] | None = None,
) -> tuple[Plan, Diff]:
    """Пересчитывает план после события."""
    geo = geo or Geo(scenario)
    search_params = params or plan.params.model_copy(update={"time_limit_s": DEFAULT_EVENT_BUDGET_S})
    search_params = search_params.model_copy(update={"stability_weight_m": _stability_for(event)})
    at_min = hhmm_to_min(event.time)

    frozen = freeze(geo, plan, at_min)
    geo, pool, caption = apply_event(scenario, geo, frozen, event, at_min)
    remap_starts(geo, frozen)

    new_plan = solver.plan(
        scenario,
        geo,
        search_params,
        plan_id=plan_id or f"{plan.id}+{event.type}",
        starts=frozen.starts,
        order_ids=pool,
        previous=plan.assignment,
        on_progress=on_progress,
    )
    new_plan.parent_plan_id = plan.id
    new_plan.event = event
    new_plan.planned_from = min_to_hhmm(at_min)
    explain_module.attach(geo, new_plan, frozen.starts)

    diff = build_diff(plan, new_plan, event, frozen.locked_count, caption)
    new_plan.plan_explanation = f"{diff.summary} {new_plan.plan_explanation}"
    return new_plan, diff


def _visit_changes(
    before_assignment: dict[str, str],
    after_assignment: dict[str, str],
    before_stops: dict[str, Stop],
    after_stops: dict[str, Stop],
) -> list[Change]:
    changed: list[Change] = []
    for order_id, engineer_id in after_assignment.items():
        old_engineer = before_assignment.get(order_id)
        old_stop = before_stops.get(order_id)
        new_stop = after_stops[order_id]
        if old_engineer is None:
            continue
        if (
            old_engineer != engineer_id
            or (old_stop and old_stop.start != new_stop.start)
            or (old_stop and old_stop.seq != new_stop.seq)
        ):
            changed.append(
                Change(
                    order_id=order_id,
                    from_engineer=old_engineer,
                    to_engineer=engineer_id,
                    from_seq=old_stop.seq if old_stop else None,
                    to_seq=new_stop.seq,
                    from_start=old_stop.start if old_stop else None,
                    to_start=new_stop.start,
                )
            )
    return changed


def _changed_routes(
    changed: list[Change],
    added: list[str],
    removed: list[str],
    before_assignment: dict[str, str],
    after_assignment: dict[str, str],
) -> list[str]:
    return sorted(
        {change.from_engineer for change in changed if change.from_engineer}
        | {change.to_engineer for change in changed if change.to_engineer}
        | {after_assignment[o] for o in added if o in after_assignment}
        | {before_assignment[o] for o in removed if o in before_assignment}
    )


def build_diff(before: Plan, after: Plan, event: Event, locked: int, caption: str) -> Diff:
    """Что именно изменилось."""
    before_assignment = before.assignment
    after_assignment = after.assignment
    before_stops = {s.order_id: s for r in before.routes for s in r.stops}
    after_stops = {s.order_id: s for r in after.routes for s in r.stops}

    before_unassigned = {u.order_id for u in before.unassigned}
    after_unassigned = {u.order_id for u in after.unassigned}
    added = [order_id for order_id in after_assignment if order_id not in before_stops]
    removed = [
        order_id
        for order_id in before_assignment
        if order_id not in after_assignment
        and order_id not in after_unassigned
    ]

    changed = _visit_changes(before_assignment, after_assignment, before_stops, after_stops)
    newly_assigned = sorted(before_unassigned - after_unassigned - set(removed))
    newly_unassigned = sorted(after_unassigned - before_unassigned)
    routes_changed = _changed_routes(changed, added, removed, before_assignment, after_assignment)

    return Diff(
        event=event,
        before_plan_id=before.id,
        after_plan_id=after.id,
        changed=changed,
        newly_assigned=newly_assigned,
        newly_unassigned=newly_unassigned,
        removed=removed,
        added=added,
        routes_changed=routes_changed,
        locked_stops=locked,
        metrics_before=before.metrics,
        metrics_after=after.metrics,
        summary=_summary(before, after, changed, newly_assigned, newly_unassigned, locked, caption),
    )


def _summary(
    before: Plan,
    after: Plan,
    changed: list[Change],
    newly_assigned: list[str],
    newly_unassigned: list[str],
    locked: int,
    caption: str,
) -> str:
    from planner.core.reasons import _plural

    parts = [f"Событие: {caption}."]
    parts.append(
        f"Зафиксировано {locked} "
        f"{_plural(locked, 'визит', 'визита', 'визитов')}, к которым выехали до события."
    )

    moved = [c for c in changed if c.from_engineer != c.to_engineer]
    shifted = [c for c in changed if c.from_engineer == c.to_engineer]
    if moved:
        first = moved[0]
        parts.append(
            f"Переназначено {len(moved)} "
            f"{_plural(len(moved), 'заявка', 'заявки', 'заявок')} "
            f"(например, {first.order_id}: {first.from_engineer} → {first.to_engineer}, "
            f"начало {first.from_start} → {first.to_start})."
        )
    if shifted:
        parts.append(
            f"У {len(shifted)} {_plural(len(shifted), 'заявки', 'заявок', 'заявок')} "
            "сдвинулось время начала."
        )
    if newly_assigned:
        parts.append(
            f"Удалось разместить ранее неназначенные: {', '.join(newly_assigned[:3])}"
            + ("…" if len(newly_assigned) > 3 else "") + "."
        )
    if newly_unassigned:
        parts.append(
            f"Выпали из плана: {', '.join(newly_unassigned[:3])}"
            + ("…" if len(newly_unassigned) > 3 else "") + "."
        )
    if not moved and not shifted and not newly_assigned and not newly_unassigned:
        parts.append("Остальной план не изменился.")

    if after.metrics.rescheduled:
        count = after.metrics.rescheduled
        word = _plural(count, "заявке", "заявкам", "заявкам")
        parts.append(
            f"По {count} {word} пришлось сдвинуть обещанное клиенту время — "
            "службе поддержки нужно предупредить."
        )

    delta_distance = round(after.metrics.distance_total_km - before.metrics.distance_total_km, 1)
    delta_engineers = after.metrics.engineers_used - before.metrics.engineers_used
    parts.append(
        f"Пробег {delta_distance:+.1f} км, инженеров {delta_engineers:+d} "
        f"(стало {after.metrics.engineers_used})."
    )
    return " ".join(parts)


def make_urgent_order(
    scenario: Scenario,
    address: str,
    lat: float,
    lon: float,
    skill,
    window: tuple[str, str],
    duration_min: int,
    district: str = "",
    order_id: str | None = None,
) -> Order:
    """Заготовка срочной заявки для формы диспетчера."""
    from planner.core.models import GeocodeQuality

    existing = {o.id for o in scenario.orders}
    index = len(scenario.orders) + 1
    candidate = order_id or f"SOS-{index:03d}"
    while candidate in existing:
        index += 1
        candidate = f"SOS-{index:03d}"

    return Order(
        id=candidate,
        address=address,
        district=district,
        lat=lat,
        lon=lon,
        geocode_quality=GeocodeQuality.MANUAL,
        skill=skill,
        work_type="Глобальная проблема",
        description="Авария",
        duration_min=duration_min,
        window_start=window[0],
        window_end=window[1],
        priority=Priority.URGENT,
    )
