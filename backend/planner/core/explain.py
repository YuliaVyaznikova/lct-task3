"""Объяснения решений для диспетчера (DESIGN.md §10, ТЗ §2.1.7, §2.4.2, §8.1).

ТЗ требует объяснять результат «понятным пользователю языком»: почему заявка
назначена конкретному инженеру, какие ограничения учтены и почему выбран
такой маршрут. На сессии вопросов и ответов постановщик отдельно просил
не разворачивать весь алгоритм по каждой заявке — «портянку читать не будут».

Отсюда два уровня: строка для таблицы и карточка по клику. Всё собирается
шаблонами из фактов плана, без языковой модели, — значит, воспроизводимо
и не может соврать про то, чего в плане нет.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from planner.core.models import (
    PRIORITY_RU,
    SKILL_RU,
    TRANSPORT_RU,
    Engineer,
    Order,
    Plan,
    Route,
    Stop,
)
from planner.core.reasons import _plural
from planner.core.timeutil import fmt_minutes, hhmm_to_min
from planner.core.validate import Geo, StartState, best_insertion, first_blocking_violation

#: Сколько инженеров-альтернатив показывать поимённо.
MAX_ALTERNATIVES = 3


@dataclass
class Check:
    ok: bool
    text: str


@dataclass
class OrderExplanation:
    order_id: str
    engineer_id: str
    headline: str
    checks: list[Check] = field(default_factory=list)
    travel: str = ""
    alternatives: list[str] = field(default_factory=list)
    why: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _previous_point(geo: Geo, route: Route, stop: Stop) -> str:
    position = route.stops.index(stop)
    if position == 0:
        return f"от стартовой точки ({geo.scenario.office.address})"
    previous = geo.orders[route.stops[position - 1].order_id]
    return f"от предыдущей точки ({previous.id}, {previous.address})"


def explain_order(
    geo: Geo,
    plan: Plan,
    order_id: str,
    starts: dict[str, StartState] | None = None,
) -> OrderExplanation:
    """Карточка назначенной заявки: проверки ограничений и сравнение с альтернативами."""
    route = next(r for r in plan.routes if any(s.order_id == order_id for s in r.stops))
    stop = next(s for s in route.stops if s.order_id == order_id)
    order = geo.orders[order_id]
    engineer = geo.engineers[route.engineer_id]

    from planner.ingest.equipment import describe_needs

    needs = geo.equipment_needs(order_id)
    position = route.stops.index(stop)
    taken: dict[str, int] = {}
    for earlier in route.stops[: position + 1]:
        for kind, count in geo.equipment_needs(earlier.order_id).items():
            taken[kind] = taken.get(kind, 0) + count
    stock = geo.equipment_stock(engineer.id)

    if needs:
        spent = ", ".join(
            f"{geo.equipment.title(kind)} {taken.get(kind, 0)} из {stock.get(kind, 0)}"
            for kind in sorted(needs)
        )
        equipment_text = f"Оборудование: нужен {describe_needs(needs, geo.equipment)}; израсходовано {spent}"
    else:
        equipment_text = "Оборудование — не требуется"

    checks = [
        Check(True, f"Навык «{SKILL_RU[order.skill]}» — есть (навыки инженера: {engineer.skills_ru})"),
        Check(
            True,
            f"Транспорт — {_transport_check(order, engineer)}",
        ),
        Check(
            True,
            f"Окно {order.window_start}–{order.window_end}: прибытие {stop.arrival}"
            + (f", ожидание {stop.wait_min} мин" if stop.wait_min else "")
            + f", начало {stop.start}",
        ),
        Check(
            True,
            f"Смена {engineer.shift_start}–{engineer.shift_end}: "
            f"маршрут завершается в {route.end_time}",
        ),
        Check(True, equipment_text),
    ]

    headline = (
        f"{engineer.name} ({TRANSPORT_RU[engineer.transport]}) · "
        f"прибытие {stop.arrival}, работа {stop.start}–{stop.finish}"
    )
    travel = (
        f"Переезд {_previous_point(geo, route, stop)}: "
        f"{stop.travel_km:.1f} км, {fmt_minutes(stop.travel_min)}"
    )

    alternatives, why = _alternatives(geo, plan, order, engineer, starts)
    return OrderExplanation(
        order_id=order_id,
        engineer_id=engineer.id,
        headline=headline,
        checks=checks,
        travel=travel,
        alternatives=alternatives,
        why=why,
    )


def _transport_check(order: Order, engineer: Engineer) -> str:
    if order.required_transport is None:
        return f"ограничения нет (инженер: {TRANSPORT_RU[engineer.transport]})"
    return (
        f"заявке нужен «{TRANSPORT_RU[order.required_transport]}», "
        f"у инженера он и есть"
    )


def _alternatives(
    geo: Geo,
    plan: Plan,
    order: Order,
    chosen: Engineer,
    starts: dict[str, StartState] | None,
) -> tuple[list[str], str]:
    """Контрфактическая проверка: во что обошлась бы заявка другим инженерам.

    Это и есть ответ на вопрос ТЗ «почему именно этот инженер»: для каждого
    другого исполнителя ищется самая дешёвая допустимая вставка в его
    итоговый маршрут, и сравнивается прирост пробега.
    """
    routes = {route.engineer_id: route for route in plan.routes}
    cheaper: list[tuple[float, str]] = []
    blocked: list[str] = []
    no_skill = 0

    for engineer in geo.scenario.engineers:
        if engineer.id == chosen.id:
            continue
        if order.skill not in engineer.skills or (
            order.required_transport is not None and order.required_transport != engineer.transport
        ):
            no_skill += 1
            continue

        current = routes.get(engineer.id)
        order_ids = [o for o in (current.order_ids if current else []) if o != order.id]
        start = (starts or {}).get(engineer.id)
        found = best_insertion(geo, engineer, order_ids, order.id, start)
        if found is None:
            violation = first_blocking_violation(geo, engineer, order_ids, order.id, start)
            if violation is not None:
                blocked.append(f"{engineer.name} — {violation.text}")
            continue
        cheaper.append((found[1], f"{engineer.name} — +{found[1]:.1f} км к его маршруту"))

    cheaper.sort(key=lambda item: item[0])
    lines = [text for _, text in cheaper[:MAX_ALTERNATIVES]]
    lines += blocked[: max(0, MAX_ALTERNATIVES - len(lines))]
    if no_skill:
        word = _plural(no_skill, "инженер", "инженера", "инженеров")
        lines.append(f"ещё {no_skill} {word} — не подходят по навыку или транспорту")

    if cheaper:
        best_delta = cheaper[0][0]
        why = (
            f"Выбран как исполнитель с наименьшим приростом маршрута: "
            f"ближайшая альтернатива добавила бы {best_delta:.1f} км."
        )
    elif blocked:
        why = "Выбран как единственный, кто успевает к заявке без нарушения окна и смены."
    else:
        why = "Единственный инженер с нужным навыком и транспортом."
    return lines, why


def explain_route(geo: Geo, route: Route) -> str:
    """Короткая сводка по маршруту инженера."""
    engineer = geo.engineers[route.engineer_id]
    if not route.stops:
        return f"{engineer.name}: заявок нет."

    shift = max(engineer.shift_end_min - engineer.shift_start_min, 1)
    load = round(100 * (route.work_min + route.travel_min) / shift)
    districts: list[str] = []
    for stop in route.stops:
        district = geo.orders[stop.order_id].district
        if district and (not districts or districts[-1] != district):
            districts.append(district)

    count = len(route.stops)
    word = _plural(count, "заявка", "заявки", "заявок")
    text = (
        f"{engineer.name} ({TRANSPORT_RU[engineer.transport]}): {count} {word}, "
        f"{route.distance_km:.1f} км, {fmt_minutes(route.travel_min)} в пути"
    )
    if route.wait_min:
        text += f", {fmt_minutes(route.wait_min)} ожидания"
    text += f", смена загружена на {load}%."
    if districts:
        text += " Порядок задают временные окна: " + " → ".join(districts[:5]) + "."
    return text


def explain_plan(geo: Geo, plan: Plan) -> str:
    """Сводка по плану целиком — то, что диспетчер читает первым."""
    m = plan.metrics
    parts = [
        f"Задействовано {m.engineers_used} из {m.engineers_total} инженеров. "
        f"Назначено {m.assigned} из {m.orders_total} заявок."
    ]
    if m.urgent_total:
        parts.append(f"Срочных выполнено {m.urgent_assigned} из {m.urgent_total}.")

    if plan.unassigned:
        from collections import Counter

        by_reason = Counter(u.reason_code.value for u in plan.unassigned)
        titles = {
            "CAPACITY": "не хватило мощности",
            "NO_SKILL": "нет навыка",
            "NO_TRANSPORT": "нет нужного транспорта",
            "SHIFT_MISMATCH": "окно не попадает в смены",
            "UNREACHABLE": "слишком далеко",
            "NO_COORDS": "нет координат",
        }
        listed = ", ".join(
            f"{count} — {titles.get(code, code)}" for code, count in by_reason.most_common()
        )
        parts.append(f"Не назначено {len(plan.unassigned)}: {listed}.")
        if m.extra_engineers_needed:
            word = _plural(m.extra_engineers_needed, "инженер", "инженера", "инженеров")
            parts.append(
                f"Чтобы выполнить всё, нужно ещё {m.extra_engineers_needed} {word}."
            )
    else:
        parts.append("Все заявки распределены.")

    parts.append(
        f"Суммарный пробег {m.distance_total_km:.0f} км "
        f"({m.distance_per_order_km:.1f} км на заявку)."
    )
    return " ".join(parts)


def attach(geo: Geo, plan: Plan, starts: dict[str, StartState] | None = None) -> Plan:
    """Наполняет план объяснениями всех трёх уровней."""
    plan.explanations = {
        stop.order_id: explain_order(geo, plan, stop.order_id, starts).to_dict()
        for route in plan.routes
        for stop in route.stops
    }
    plan.route_explanations = {
        route.engineer_id: explain_route(geo, route) for route in plan.routes if route.stops
    }
    plan.plan_explanation = explain_plan(geo, plan)
    return plan


def timeline_summary(geo: Geo, route: Route) -> list[str]:
    """Маршрут строками «кто, куда, во сколько» — для таблицы и печати."""
    lines: list[str] = []
    for stop in route.stops:
        order = geo.orders[stop.order_id]
        lines.append(
            f"{stop.seq:>2}. {stop.start}–{stop.finish}  {order.id:<8} "
            f"{SKILL_RU[order.skill]:<24} {order.district:<26} {order.address}"
        )
    return lines


def describe_order(order: Order) -> str:
    return (
        f"{order.id} · {order.work_type} / {order.description} · "
        f"{SKILL_RU[order.skill]} · {PRIORITY_RU[order.priority]} · "
        f"окно {order.window_start}–{order.window_end} · {order.duration_min} мин · "
        f"{order.district}, {order.address}"
    )


def minutes_between(start: str, finish: str) -> int:
    return hhmm_to_min(finish) - hhmm_to_min(start)
