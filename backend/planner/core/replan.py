"""Перепланирование после события (DESIGN.md §9, ТЗ §2.1.6).

ТЗ требует перестроить план после одного события на выбор: появилась срочная
заявка, заявка отменена, инженер стал недоступен. Реализованы все три.

Схема — «заморозить прошлое, пересчитать будущее». На момент события t всё,
что инженер уже начал или выполнил, остаётся в плане неприкосновенным: диспетчер
не может отменить визит, который уже идёт. Инженер продолжает маршрут из точки,
где он находится, а все ещё не начатые заявки возвращаются в общий пул
и распределяются заново — вместе с теми, что в прошлом плане не поместились.

Чтобы план не «рассыпался» ради нескольких сэкономленных километров, за смену
исполнителя назначается штраф (stability_weight_m): переставлять заявки можно,
но только если это даёт заметный выигрыш.
"""

from __future__ import annotations

from dataclasses import dataclass

from planner.core import explain as explain_module
from planner.core import solver
from planner.core.models import (
    CancelOrderEvent,
    Change,
    Diff,
    EngineerUnavailableEvent,
    Event,
    Order,
    Plan,
    PlanParams,
    Priority,
    Scenario,
    Stop,
    UrgentOrderEvent,
)
from planner.core.timeutil import hhmm_to_min, min_to_hhmm
from planner.core.validate import Geo, StartState

#: Штраф за перевод заявки к другому инженеру при перепланировании, метры.
#: Подобран по данным: при 500 м одно событие перетасовывало 11 заявок и удлиняло
#: маршруты, при 3000 м план остаётся узнаваемым и выходит короче. Величина
#: сопоставима с типичным переездом внутри района, то есть переставлять заявку
#: имеет смысл только ради заметного выигрыша.
DEFAULT_STABILITY_M = 3000


class ReplanError(RuntimeError):
    """Событие невозможно применить к текущему плану."""


@dataclass
class Frozen:
    starts: dict[str, StartState]
    pool: list[str]
    locked_count: int


def freeze(geo: Geo, plan: Plan, at_min: int) -> Frozen:
    """Делит план на неприкосновенное прошлое и пул заявок на пересчёт."""
    starts: dict[str, StartState] = {}
    pool: list[str] = []
    locked_count = 0

    for engineer in geo.scenario.engineers:
        route = next((r for r in plan.routes if r.engineer_id == engineer.id), None)
        locked: list[Stop] = []
        if route is not None:
            for stop in route.stops:
                # Инженер уже на адресе (едет — ещё нет): работа считается начатой.
                if hhmm_to_min(stop.arrival) <= at_min:
                    locked.append(stop.model_copy(update={"locked": True, "seq": len(locked) + 1}))
                else:
                    pool.append(stop.order_id)

        locked_count += len(locked)
        if locked:
            last = locked[-1]
            starts[engineer.id] = StartState(
                node=geo.node(last.order_id),
                available_min=hhmm_to_min(last.finish),
                locked_stops=locked,
                distance_km=round(sum(s.travel_km for s in locked), 3),
                travel_min=sum(s.travel_min for s in locked),
                work_min=sum(geo.orders[s.order_id].duration_min for s in locked),
                wait_min=sum(s.wait_min for s in locked),
            )
        else:
            starts[engineer.id] = StartState(
                node=geo.start_node(engineer),
                available_min=max(at_min, engineer.shift_start_min),
            )

    assigned = {s.order_id for r in plan.routes for s in r.stops}
    pool.extend(u.order_id for u in plan.unassigned if u.order_id not in assigned)
    return Frozen(starts=starts, pool=pool, locked_count=locked_count)


def remap_starts(geo: Geo, frozen: Frozen) -> None:
    """Переводит стартовые узлы заморозки в индексацию переданного `geo`.

    Узлы заявок устойчивы (новые заявки дописываются в конец), а офис
    и выездные базы идут после них, поэтому добавление хотя бы одной заявки
    сдвигает их индексы. Место инженера задаётся не числом, а смыслом:
    точка последнего выполненного визита либо его собственная стартовая точка.
    """
    for engineer_id, state in frozen.starts.items():
        if state.locked_stops:
            state.node = geo.node(state.locked_stops[-1].order_id)
        elif engineer_id in geo.engineers:
            state.node = geo.start_node(geo.engineers[engineer_id])


def apply_event(
    scenario: Scenario, geo: Geo, frozen: Frozen, event: Event, at_min: int
) -> tuple[Geo, list[str], str]:
    """Меняет сценарий по событию. Возвращает (geo, пул, подпись события)."""
    pool = list(frozen.pool)

    if isinstance(event, UrgentOrderEvent):
        order = event.order.model_copy(update={"priority": Priority.URGENT})
        if order.window_end_min < at_min:
            raise ReplanError(
                f"окно заявки {order.window_start}–{order.window_end} уже закрылось "
                f"к моменту события {event.time}"
            )
        if any(o.id == order.id for o in scenario.orders):
            raise ReplanError(f"заявка {order.id} уже есть в сценарии")
        scenario.orders.append(order)
        geo = Geo(scenario)  # индексы точек изменились — матрицу надо пересобрать
        pool.append(order.id)
        return geo, pool, f"срочная заявка {order.id} ({order.address})"

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
        # Начатую заявку инженер доводит до конца, всё остальное уже в пуле.
        # Инженер остаётся в плане как «закрытый»: новых заявок не получит,
        # но выполненные визиты обязаны остаться видимыми диспетчеру.
        state = frozen.starts.get(event.engineer_id)
        if state is not None:
            state.closed = True
        name = geo.engineers[event.engineer_id].name
        return geo, pool, f"{name} недоступен с {event.time}"

    raise ReplanError(f"неизвестный тип события: {event!r}")


def replan(
    scenario: Scenario,
    plan: Plan,
    event: Event,
    geo: Geo | None = None,
    params: PlanParams | None = None,
    plan_id: str | None = None,
) -> tuple[Plan, Diff]:
    """Пересчитывает план после события. Сценарий может быть дополнен новой заявкой."""
    geo = geo or Geo(scenario)
    params = (params or plan.params).model_copy(
        update={"stability_weight_m": DEFAULT_STABILITY_M}
    )
    at_min = hhmm_to_min(event.time)

    frozen = freeze(geo, plan, at_min)
    geo, pool, caption = apply_event(scenario, geo, frozen, event, at_min)
    # Срочная заявка добавляет сценарию точку, и нумерация узлов сдвигается:
    # индекс офиса, вычисленный при заморозке, после этого указывал бы
    # на новую заявку. Пересчитываем стартовые узлы по свежей индексации.
    remap_starts(geo, frozen)

    previous = plan.assignment
    new_plan = solver.plan(
        scenario,
        geo,
        params,
        plan_id=plan_id or f"{plan.id}+{event.type}",
        starts=frozen.starts,
        order_ids=pool,
        previous=previous,
    )
    new_plan.parent_plan_id = plan.id
    new_plan.event = event
    new_plan.planned_from = min_to_hhmm(at_min)
    explain_module.attach(geo, new_plan, frozen.starts)

    diff = build_diff(plan, new_plan, event, frozen.locked_count, caption)
    new_plan.plan_explanation = f"{diff.summary} {new_plan.plan_explanation}"
    return new_plan, diff


def build_diff(before: Plan, after: Plan, event: Event, locked: int, caption: str) -> Diff:
    """Что именно изменилось — ТЗ §2.4.2 требует показать это наглядно."""
    before_assignment = before.assignment
    after_assignment = after.assignment
    before_stops = {s.order_id: s for r in before.routes for s in r.stops}
    after_stops = {s.order_id: s for r in after.routes for s in r.stops}

    added = [order_id for order_id in after_assignment if order_id not in before_stops]
    removed = [
        order_id
        for order_id in before_assignment
        if order_id not in after_assignment
        and order_id not in {u.order_id for u in after.unassigned}
    ]

    changed: list[Change] = []
    for order_id, engineer_id in after_assignment.items():
        old_engineer = before_assignment.get(order_id)
        old_stop = before_stops.get(order_id)
        new_stop = after_stops[order_id]
        if old_engineer is None:
            continue
        if old_engineer != engineer_id or (old_stop and old_stop.start != new_stop.start):
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

    before_unassigned = {u.order_id for u in before.unassigned}
    after_unassigned = {u.order_id for u in after.unassigned}
    newly_assigned = sorted(before_unassigned - after_unassigned - set(removed))
    newly_unassigned = sorted(after_unassigned - before_unassigned)

    routes_changed = sorted(
        {change.from_engineer for change in changed if change.from_engineer}
        | {change.to_engineer for change in changed if change.to_engineer}
        | {after_assignment[o] for o in added if o in after_assignment}
        | {before_assignment[o] for o in removed if o in before_assignment}
    )

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
        f"{_plural(locked, 'визит', 'визита', 'визитов')}, начатых до события."
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
