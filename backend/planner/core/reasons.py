"""Почему заявка не назначена иерархия причин."""

from __future__ import annotations

from planner.core.equipment import describe_needs
from planner.core.models import (
    SKILL_RU,
    TRANSPORT_RU,
    Engineer,
    Order,
    Priority,
    ReasonCode,
    Route,
    Unassigned,
    Violation,
)
from planner.core.text import plural
from planner.core.timeutil import min_to_hhmm
from planner.core.validate import (
    Geo,
    StartState,
    best_insertion,
    check_static,
    first_blocking_violation,
)


def can_serve_alone(geo: Geo, engineer: Engineer, order: Order) -> ReasonCode | None:
    """Может ли инженер выполнить заявку, будь она у него единственной."""
    mismatch = check_static(engineer, order)
    if mismatch is not None:
        return ReasonCode(mismatch.code)

    stock = geo.equipment_stock(engineer.id)
    for kind, count in geo.equipment_needs(order.id).items():
        if count > stock.get(kind, 0):
            return ReasonCode.NO_EQUIPMENT

    _, travel_min = geo.leg(engineer, geo.start_node(engineer), geo.node(order.id))
    earliest = max(order.window_start_min, engineer.shift_start_min + travel_min)
    latest = min(order.window_end_min, engineer.shift_end_min - order.duration_min)
    if earliest <= latest:
        return None
    if engineer.shift_end_min - order.duration_min < order.window_start_min:
        return ReasonCode.SHIFT_MISMATCH
    if engineer.shift_start_min >= order.window_end_min:
        return ReasonCode.SHIFT_MISMATCH
    if engineer.shift_start_min + travel_min > order.window_end_min:
        return ReasonCode.UNREACHABLE
    return ReasonCode.SHIFT_MISMATCH


def _no_capable_reason(
    geo: Geo, order: Order, verdicts: dict[str, ReasonCode | None]
) -> Unassigned:
    engineers = geo.scenario.engineers
    skill_ru = SKILL_RU[order.skill]
    with_skill = [engineer for engineer in engineers if order.skill in engineer.skills]
    if not with_skill:
        return Unassigned(
            order_id=order.id,
            reason_code=ReasonCode.NO_SKILL,
            reason=f"ни у одного инженера нет навыка «{skill_ru}»",
        )

    blocked = [verdicts[engineer.id] for engineer in with_skill]
    if all(code is ReasonCode.NO_EQUIPMENT for code in blocked):
        return Unassigned(
            order_id=order.id,
            reason_code=ReasonCode.NO_EQUIPMENT,
            reason=(
                f"для заявки нужно {describe_needs(geo.equipment_needs(order.id), geo.equipment)}, "
                "а бригады столько с собой не берут, нужно увеличить утренний запас"
            ),
        )

    if all(code is ReasonCode.NO_TRANSPORT for code in blocked):
        required = TRANSPORT_RU[order.required_transport] if order.required_transport else "не указан"
        have = ", ".join(sorted({TRANSPORT_RU[engineer.transport] for engineer in with_skill}))
        return Unassigned(
            order_id=order.id,
            reason_code=ReasonCode.NO_TRANSPORT,
            reason=(
                f"заявке нужен транспорт «{required}», "
                f"а инженеры с навыком «{skill_ru}» передвигаются так: {have}"
            ),
        )

    suitable = [
        engineer for engineer in with_skill
        if verdicts[engineer.id] is not ReasonCode.NO_TRANSPORT
    ]
    if suitable and all(verdicts[engineer.id] is ReasonCode.UNREACHABLE for engineer in suitable):
        nearest = min(
            suitable,
            key=lambda engineer: geo.leg(
                engineer, geo.start_node(engineer), geo.node(order.id)
            )[1],
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

    by_shift = [
        engineer for engineer in suitable if verdicts[engineer.id] is ReasonCode.SHIFT_MISMATCH
    ] or suitable or with_skill
    shifts = sorted({f"{engineer.shift_start}–{engineer.shift_end}" for engineer in by_shift})
    reason = (
        f"окно {order.window_start}–{order.window_end} и {order.duration_min} мин работы "
        f"не помещаются в смены инженеров с навыком «{skill_ru}» ({', '.join(shifts)})"
    )
    far = [engineer for engineer in suitable if verdicts[engineer.id] is ReasonCode.UNREACHABLE]
    if far:
        nearest = min(far, key=lambda engineer: geo.leg(engineer, geo.start_node(engineer), geo.node(order.id))[1])
        km, minutes = geo.leg(nearest, geo.start_node(nearest), geo.node(order.id))
        reason += (
            f", а {nearest.name} со сменой {nearest.shift_start}–{nearest.shift_end} не успевает доехать: "
            f"{km:.0f} км, {TRANSPORT_RU[nearest.transport]}, {minutes} мин в пути"
        )
    return Unassigned(order_id=order.id, reason_code=ReasonCode.SHIFT_MISMATCH, reason=reason)


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
            reason="не удалось определить координаты адреса, заявку нужно уточнить вручную",
        )

    verdicts = {
        engineer.id: can_serve_alone(geo, engineer, order)
        for engineer in geo.scenario.engineers
    }
    capable = [engineer for engineer in geo.scenario.engineers if verdicts[engineer.id] is None]

    if not capable:
        return _no_capable_reason(geo, order, verdicts)

    return Unassigned(
        order_id=order.id,
        reason_code=ReasonCode.CAPACITY,
        reason=_capacity_reason(geo, order, capable, routes or [], starts),
        detail=_capacity_detail(geo, order, capable, routes or [], starts),
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
        head = (
            f"не удалось разместить в этом расчёте: в маршрут единственного инженера "
            f"с навыком «{skill_ru}» заявка {window} не встаёт"
        )
    else:
        who = plural(count, "инженера", "инженеров", "инженеров")
        head = (
            f"не удалось разместить в этом расчёте: ни в один из текущих маршрутов "
            f"{count} {who} с навыком «{skill_ru}» заявка {window} не встаёт"
        )

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
            details.append(f"{engineer.name} освобождается в {route.end_time}: {blocking.text}")
        else:
            details.append(f"{engineer.name}: {blocking.text}")

    if not details:
        return head
    return head + ": " + "; ".join(details)


def _travel_minutes(geo: Geo, engineer: Engineer, order: Order) -> int:
    return geo.leg(engineer, geo.start_node(engineer), geo.node(order.id))[1]


def _blockers(
    geo: Geo,
    order: Order,
    capable: list[Engineer],
    routes: list[Route],
    starts: dict[str, StartState] | None,
) -> list[tuple[Engineer, Violation]]:
    by_engineer = {route.engineer_id: route for route in routes}
    found: list[tuple[Engineer, Violation]] = []
    for engineer in sorted(capable, key=lambda item: _travel_minutes(geo, item, order)):
        route = by_engineer.get(engineer.id)
        blocking = first_blocking_violation(
            geo, engineer, route.order_ids if route else [], order.id, (starts or {}).get(engineer.id)
        )
        if blocking is not None:
            found.append((engineer, blocking))
    return found


def _nearest_blocker_text(
    order: Order, engineer: Engineer, blocking: Violation, route: Route | None
) -> str:
    if blocking.order_id not in (None, order.id):
        free = f"освобождается в {route.end_time}, " if route and route.stops else ""
        return (
            f"ближайший, {engineer.name}, {free}"
            f"вставка сдвинула бы заявку {blocking.order_id} за конец её окна"
        )
    if blocking.code == "SHIFT":
        return f"ближайший, {engineer.name}, закончит смену раньше, чем выполнит заявку"
    if blocking.code == "WINDOW":
        return f"ближайший, {engineer.name}, не успевает к концу окна клиента"
    return f"ближайший, {engineer.name}: {blocking.text}"


def _displaced_ids(order: Order, blockers: list[tuple[Engineer, Violation]]) -> list[str]:
    ids = [v.order_id for _, v in blockers if v.order_id not in (None, order.id)]
    return list(dict.fromkeys(ids))


def _outranking_ids(geo: Geo, order: Order, displaced: list[str]) -> list[str]:
    def rank(item: Order) -> tuple[int, int]:
        return (item.priority is not Priority.URGENT, item.priority_tier)

    return [other for other in displaced if rank(geo.orders[other]) < rank(order)]


def _capacity_detail(
    geo: Geo,
    order: Order,
    capable: list[Engineer],
    routes: list[Route],
    starts: dict[str, StartState] | None,
) -> str:
    """Короткая конкретная причина для заявки, которую поиск не разместил."""
    count = len(capable)
    who = plural(count, "инженер", "инженера", "инженеров")
    busy = plural(count, "занят", "заняты", "заняты")
    head = (
        f"В этом расчёте {count} {who} с навыком «{SKILL_RU[order.skill]}» "
        f"{busy} в окно клиента {order.window_start}–{order.window_end}"
    )
    blockers = _blockers(geo, order, capable, routes, starts)
    if not blockers:
        return head
    nearest, blocking = blockers[0]
    route = {route.engineer_id: route for route in routes}.get(nearest.id)
    parts = [head + ": " + _nearest_blocker_text(order, nearest, blocking, route)]
    displaced = _displaced_ids(order, blockers)
    outranking = _outranking_ids(geo, order, displaced)
    if outranking:
        shown = ", ".join(outranking[:3])
        rest = len(outranking) - 3
        tail = f" и ещё {rest}" if rest > 0 else ""
        parts.append(f"место освободилось бы только за счёт более приоритетных заявок: {shown}{tail}")
    return "; ".join(parts)


def diagnose_all(
    geo: Geo,
    order_ids: list[str],
    routes: list[Route] | None = None,
    starts: dict[str, StartState] | None = None,
) -> list[Unassigned]:
    return [diagnose(geo, geo.orders[order_id], routes, starts) for order_id in order_ids]


def extra_engineers_needed(geo: Geo, unassigned: list[Unassigned]) -> int:
    """Сколько инженеров не хватило, чтобы выполнить всё."""
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
            found = best_insertion(geo, template, bucket, order_id)
            if found is not None:
                bucket.insert(found[0], order_id)
                break
        else:
            buckets.append([order_id])
    return len(buckets)
