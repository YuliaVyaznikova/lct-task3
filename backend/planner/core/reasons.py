"""Почему заявка не назначена — иерархия причин (DESIGN.md §10.2, ТЗ §2.2).

ТЗ требует показать неназначенные заявки «в явном виде» и назвать причину
по каждой понятным диспетчеру языком. Причина ищется от самой общей к самой
частной: сначала «вообще некому», потом «некому в это время», и лишь в конце
«все заняты» — так диспетчер сразу понимает, нанимать ли человека с навыком
или просто добавить смену.
"""

from __future__ import annotations

from planner.core.models import (
    SKILL_RU,
    TRANSPORT_RU,
    Engineer,
    Order,
    ReasonCode,
    Route,
    Unassigned,
)
from planner.core.timeutil import min_to_hhmm
from planner.core.validate import Geo, StartState, first_blocking_violation


def _plural(count: int, one: str, few: str, many: str) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return one
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return few
    return many


def can_serve_alone(geo: Geo, engineer: Engineer, order: Order) -> ReasonCode | None:
    """Может ли инженер выполнить заявку, будь она у него единственной.

    Отделяет «физически невозможно» от «не хватило места в расписании»:
    если и в одиночку не получается, виноваты навык, транспорт, смена
    или расстояние, а не загрузка.
    """
    if order.skill not in engineer.skills:
        return ReasonCode.NO_SKILL
    if order.required_transport is not None and order.required_transport != engineer.transport:
        return ReasonCode.NO_TRANSPORT

    _, travel_min = geo.leg(engineer, geo.start_node(engineer), geo.node(order.id))
    earliest = max(order.window_start_min, engineer.shift_start_min + travel_min)
    latest = min(order.window_end_min, engineer.shift_end_min - order.duration_min)
    if earliest <= latest:
        return None
    # Смена целиком не пересекается с окном либо работа не успевает завершиться.
    if engineer.shift_end_min - order.duration_min < order.window_start_min:
        return ReasonCode.SHIFT_MISMATCH
    if engineer.shift_start_min >= order.window_end_min:
        return ReasonCode.SHIFT_MISMATCH
    # Смена пересекается с окном, но дорога съедает остаток.
    if engineer.shift_start_min + travel_min > order.window_end_min:
        return ReasonCode.UNREACHABLE
    return ReasonCode.SHIFT_MISMATCH


def diagnose(
    geo: Geo,
    order: Order,
    routes: list[Route] | None = None,
    starts: dict[str, StartState] | None = None,
) -> Unassigned:
    """Определяет причину и формулирует её для диспетчера."""
    if not order.has_coords:
        return Unassigned(
            order_id=order.id,
            reason_code=ReasonCode.NO_COORDS,
            reason="не удалось определить координаты адреса — заявку нужно уточнить вручную",
        )

    engineers = geo.scenario.engineers
    skill_ru = SKILL_RU[order.skill]

    verdicts = {e.id: can_serve_alone(geo, e, order) for e in engineers}
    capable = [e for e in engineers if verdicts[e.id] is None]

    if not capable:
        with_skill = [e for e in engineers if order.skill in e.skills]
        if not with_skill:
            return Unassigned(
                order_id=order.id,
                reason_code=ReasonCode.NO_SKILL,
                reason=f"ни у одного инженера нет навыка «{skill_ru}»",
            )

        blocked = [verdicts[e.id] for e in with_skill]
        if all(code is ReasonCode.NO_TRANSPORT for code in blocked):
            required = TRANSPORT_RU[order.required_transport] if order.required_transport else "—"
            have = ", ".join(sorted({TRANSPORT_RU[e.transport] for e in with_skill}))
            return Unassigned(
                order_id=order.id,
                reason_code=ReasonCode.NO_TRANSPORT,
                reason=(
                    f"заявке нужен транспорт «{required}», "
                    f"а инженеры с навыком «{skill_ru}» передвигаются так: {have}"
                ),
            )

        suitable = [e for e in with_skill if verdicts[e.id] is not ReasonCode.NO_TRANSPORT]
        if suitable and all(verdicts[e.id] is ReasonCode.UNREACHABLE for e in suitable):
            nearest = min(
                suitable,
                key=lambda e: geo.leg(e, geo.start_node(e), geo.node(order.id))[1],
            )
            km, minutes = geo.leg(nearest, geo.start_node(nearest), geo.node(order.id))
            return Unassigned(
                order_id=order.id,
                reason_code=ReasonCode.UNREACHABLE,
                reason=(
                    f"до адреса {km:.0f} км: даже самый быстрый инженер с навыком «{skill_ru}» "
                    f"({TRANSPORT_RU[nearest.transport]}) доедет за {minutes} мин "
                    f"и не успеет к концу окна {order.window_end}"
                ),
            )

        shifts = sorted({f"{e.shift_start}–{e.shift_end}" for e in suitable or with_skill})
        return Unassigned(
            order_id=order.id,
            reason_code=ReasonCode.SHIFT_MISMATCH,
            reason=(
                f"окно {order.window_start}–{order.window_end} и {order.duration_min} мин работы "
                f"не помещаются в смены инженеров с навыком «{skill_ru}» ({', '.join(shifts)})"
            ),
        )

    # Навык, транспорт, смена и расстояние позволяют — значит, не хватило места.
    return Unassigned(
        order_id=order.id,
        reason_code=ReasonCode.CAPACITY,
        reason=_capacity_reason(geo, order, capable, routes or [], starts),
    )


def _capacity_reason(
    geo: Geo,
    order: Order,
    capable: list[Engineer],
    routes: list[Route],
    starts: dict[str, StartState] | None,
) -> str:
    by_engineer = {route.engineer_id: route for route in routes}
    count = len(capable)
    skill_ru = SKILL_RU[order.skill]
    window = f"в окно {order.window_start}–{order.window_end}"
    if count == 1:
        head = f"единственный инженер с навыком «{skill_ru}» занят {window}"
    else:
        who = _plural(count, "инженер", "инженера", "инженеров")
        head = f"все {count} {who} с навыком «{skill_ru}» заняты {window}"

    details: list[str] = []
    for engineer in capable[:3]:
        route = by_engineer.get(engineer.id)
        order_ids = route.order_ids if route else []
        blocking = first_blocking_violation(
            geo, engineer, order_ids, order.id, (starts or {}).get(engineer.id)
        )
        if blocking is None:
            continue
        if route and route.stops:
            details.append(f"{engineer.name} освобождается в {route.end_time} — {blocking.text}")
        else:
            details.append(f"{engineer.name}: {blocking.text}")

    if not details:
        return head
    return head + ": " + "; ".join(details)


def diagnose_all(
    geo: Geo,
    order_ids: list[str],
    routes: list[Route] | None = None,
    starts: dict[str, StartState] | None = None,
) -> list[Unassigned]:
    return [diagnose(geo, geo.orders[order_id], routes, starts) for order_id in order_ids]


def extra_engineers_needed(geo: Geo, unassigned: list[Unassigned]) -> int:
    """Сколько инженеров не хватило, чтобы выполнить всё (DESIGN.md §10.3).

    Жадно укладываем неназначенные заявки на виртуальных универсалов
    с автомобилем и широкой сменой. Постановщик на сессии вопросов и ответов
    прямо назвал такую формулировку желаемой: «нужно ещё плюс N исполнителей».
    """
    pending = [
        u.order_id
        for u in unassigned
        if u.reason_code in (ReasonCode.CAPACITY, ReasonCode.SHIFT_MISMATCH, ReasonCode.UNREACHABLE)
    ]
    if not pending:
        return 0

    from planner.core.models import Engineer, Point, Skill, Transport

    shift_start = min((e.shift_start_min for e in geo.scenario.engineers), default=540)
    shift_end = max((e.shift_end_min for e in geo.scenario.engineers), default=1380)
    template = Engineer(
        id="virtual",
        name="дополнительный инженер",
        skills=list(Skill),
        transport=Transport.CAR,
        shift_start=min_to_hhmm(shift_start),
        shift_end=min_to_hhmm(shift_end),
        start=Point(
            address=geo.scenario.office.address,
            lat=geo.scenario.office.lat,
            lon=geo.scenario.office.lon,
        ),
    )

    pending.sort(key=lambda order_id: geo.orders[order_id].window_start_min)
    buckets: list[list[str]] = []
    for order_id in pending:
        for bucket in buckets:
            placed = best_insertion_position(geo, template, bucket, order_id)
            if placed is not None:
                bucket.insert(placed, order_id)
                break
        else:
            buckets.append([order_id])
    return len(buckets)


def best_insertion_position(geo: Geo, engineer: Engineer, order_ids: list[str], candidate: str):
    from planner.core.validate import best_insertion

    found = best_insertion(geo, engineer, order_ids, candidate)
    return None if found is None else found[0]
