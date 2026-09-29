"""Арифметика маршрута и проверка ограничений."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import NamedTuple

from planner.core.models import (
    TRANSPORT_RU,
    Engineer,
    LunchBreak,
    Order,
    Route,
    Scenario,
    Stop,
    Violation,
)
from planner.core import equipment as equipment_module
from planner.core import zones as zones_module
from planner.core.timeutil import min_to_hhmm
from planner.core.travel import TravelModel
from planner.core.travel import build as build_travel

LUNCH_FROM_MIN = 13 * 60
LUNCH_UNTIL_MIN = 15 * 60
LUNCH_DURATION_MIN = 45
LUNCH_MIN_SHIFT_MIN = 6 * 60
LUNCH_HALF_WINDOW_MIN = 60


def lunch_window(engineer: Engineer) -> tuple[int, int] | None:
    """Окно обеда: 13:00–15:00, если смена его накрывает, иначе середина смены ± 1 час."""
    if engineer.shift_start_min <= LUNCH_FROM_MIN and engineer.shift_end_min >= LUNCH_UNTIL_MIN:
        return LUNCH_FROM_MIN, LUNCH_UNTIL_MIN
    if engineer.shift_end_min - engineer.shift_start_min < LUNCH_MIN_SHIFT_MIN:
        return None
    middle = (engineer.shift_start_min + engineer.shift_end_min) // 2
    return middle - LUNCH_HALF_WINDOW_MIN, middle + LUNCH_HALF_WINDOW_MIN


def lunch_starts(engineer: Engineer, available_min: int) -> tuple[int, int] | None:
    """Допустимые начала обеда для инженера, свободного с available_min, или None."""
    window = lunch_window(engineer)
    if window is None:
        return None
    earliest = max(window[0], available_min)
    latest = window[1] - LUNCH_DURATION_MIN
    return (earliest, latest) if earliest <= latest else None


class Geo:
    """Индексация точек сценария и доступ к матрицам расстояний."""

    def __init__(self, scenario: Scenario, travel: TravelModel | None = None) -> None:
        self.scenario = scenario
        missing = [o.id for o in scenario.orders if not o.has_coords]
        if missing:
            raise ValueError(f"нет координат у заявок: {', '.join(missing[:5])}")
        if not scenario.office.has_coords:
            raise ValueError("нет координат у офиса")

        self.order_ids = [o.id for o in scenario.orders]
        self.order_index = {order_id: i for i, order_id in enumerate(self.order_ids)}
        points = [o.coords for o in scenario.orders]

        self.office_index = len(points)
        points.append(scenario.office.coords)

        self._start_index: dict[str, int] = {}
        extra: dict[tuple[float, float], int] = {scenario.office.coords: self.office_index}
        for engineer in scenario.engineers:
            if not engineer.start.has_coords:
                self._start_index[engineer.id] = self.office_index
                continue
            coords = engineer.start.coords
            index = extra.get(coords)
            if index is None:
                index = len(points)
                points.append(coords)
                extra[coords] = index
            self._start_index[engineer.id] = index

        self.travel = travel or build_travel(points)
        self.orders = scenario.orders_by_id
        self.engineers = scenario.engineers_by_id
        self.equipment = equipment_module.load()
        self.zones = zones_module.split_into_zones(self.travel.distance_m(), self.office_index)

    def node(self, order_id: str) -> int:
        return self.order_index[order_id]

    def start_node(self, engineer: Engineer) -> int:
        """Стартовая точка инженера: его собственная либо офис участка."""
        return self._start_index.get(engineer.id, self.office_index)

    def zone(self, node: int) -> int:
        """Зона обслуживания: ноль это окрестность офиса, дальше удалённые кластеры."""
        return self.zones[node]

    def leg(self, engineer: Engineer, from_node: int, to_node: int) -> tuple[float, int]:
        return self.travel.travel(engineer.transport, from_node, to_node)

    def equipment_needs(self, order_id: str) -> dict[str, int]:
        """Что нужно везти к этой заявке (ответ экспертов, п.4)."""
        return equipment_module.order_needs(self.orders[order_id], self.equipment)

    def equipment_stock(self, engineer_id: str) -> dict[str, int]:
        """Что бригада взяла в офисе утром на весь день, без пополнения."""
        return equipment_module.stock_for(engineer_id, self.equipment)


@dataclass
class StartState:
    """Откуда и когда инженер готов ехать."""

    node: int
    available_min: int
    locked_stops: list[Stop] = field(default_factory=list)
    distance_km: float = 0.0
    travel_min: int = 0
    work_min: int = 0
    wait_min: int = 0
    closed: bool = False
    lunch_break: LunchBreak | None = None


class _VisitTimes(NamedTuple):
    departure: int
    arrival: int
    begin: int
    finish: int
    wait: int


@dataclass(frozen=True)
class _LunchSchedule:
    lunch_break: LunchBreak
    visits: list[_VisitTimes]
    end_min: int


def _schedule_with_lunch(
    geo: Geo,
    engineer: Engineer,
    order_ids: list[str],
    start: StartState,
    allow_late: bool,
) -> _LunchSchedule | None:
    """Подбирает допустимый обед в пути, ожидании или после последнего визита."""
    choices: list[tuple[int, int, int, _LunchSchedule]] = []
    for slot in range(2 * len(order_ids) + 1):
        candidate = _schedule_lunch_in_slot(geo, engineer, order_ids, start, allow_late, slot)
        if candidate is None:
            continue
        break_start, schedule = candidate
        choices.append((schedule.end_min, break_start, slot, schedule))
    if not choices:
        return None

    return min(choices, key=lambda item: item[:3])[3]


def _schedule_lunch_in_slot(
    geo: Geo,
    engineer: Engineer,
    order_ids: list[str],
    start: StartState,
    allow_late: bool,
    slot: int,
) -> tuple[int, _LunchSchedule] | None:
    """Расписание с обедом в заданном слоте: перед поездкой, после неё или в конце дня."""
    earliest, latest = lunch_starts(engineer, start.available_min)
    duration = LUNCH_DURATION_MIN
    node, clock = start.node, start.available_min
    visits: list[_VisitTimes] = []
    break_start: int | None = None

    for index, order_id in enumerate(order_ids):
        order = geo.orders[order_id]
        _, travel_min = geo.leg(engineer, node, geo.node(order_id))
        departure = clock
        arrival = clock + travel_min
        if slot == 2 * index:
            candidate = max(clock, earliest)
            if candidate > latest or candidate >= arrival:
                return None
            break_start = candidate
            arrival += duration
            if candidate == clock:
                departure += duration
        if slot == 2 * index + 1:
            candidate = max(arrival, earliest)
            if candidate > latest:
                return None
            break_start = candidate
            begin = max(arrival, order.window_start_min, candidate + duration)
            wait = begin - arrival - duration
        else:
            begin = max(arrival, order.window_start_min)
            wait = begin - arrival
        finish = begin + order.duration_min
        if (begin > order.window_end_min and not allow_late) or finish > engineer.shift_end_min:
            return None
        visits.append(_VisitTimes(departure, arrival, begin, finish, wait))
        node, clock = geo.node(order_id), finish

    if slot == 2 * len(order_ids):
        candidate = max(clock, earliest)
        if candidate > latest:
            return None
        break_start = candidate
        clock = candidate + duration
    if break_start is None or clock > engineer.shift_end_min:
        return None

    lunch_break = LunchBreak(
        start=min_to_hhmm(break_start), finish=min_to_hhmm(break_start + duration)
    )
    return break_start, _LunchSchedule(lunch_break, visits, clock)


def check_static(engineer: Engineer, order: Order) -> Violation | None:
    """Ограничения, не зависящие от времени: квалификация и ресурс."""
    if order.skill not in engineer.skills:
        return Violation(
            engineer_id=engineer.id,
            order_id=order.id,
            code="NO_SKILL",
            text=f"{engineer.name} не владеет навыком «{order.skill.value}»",
        )
    if order.required_transport is not None and order.required_transport != engineer.transport:
        return Violation(
            engineer_id=engineer.id,
            order_id=order.id,
            code="NO_TRANSPORT",
            text=(
                f"заявке нужен транспорт «{TRANSPORT_RU[order.required_transport]}», "
                f"а у {engineer.name} «{TRANSPORT_RU[engineer.transport]}»"
            ),
        )
    return None


def _equipment_used(geo: Geo, locked_stops: list[Stop]) -> dict[str, int]:
    used: dict[str, int] = {}
    for stop in locked_stops:
        for kind, count in geo.equipment_needs(stop.order_id).items():
            used[kind] = used.get(kind, 0) + count
    return used


def _consume_equipment(
    geo: Geo,
    engineer: Engineer,
    order_id: str,
    stock: dict[str, int],
    used: dict[str, int],
) -> list[Violation]:
    violations: list[Violation] = []
    for kind, count in geo.equipment_needs(order_id).items():
        used[kind] = used.get(kind, 0) + count
        if used[kind] > stock.get(kind, 0):
            violations.append(
                Violation(
                    engineer_id=engineer.id,
                    order_id=order_id,
                    code="NO_EQUIPMENT",
                    text=(
                        f"не хватает оборудования: "
                        f"«{geo.equipment.title(kind)}» нужен {used[kind]}-й раз, "
                        f"а утром взято {stock.get(kind, 0)}"
                    ),
                )
            )
    return violations


def _visit_times(
    order: Order,
    clock: int,
    leg_min: int,
    lunch_schedule: _LunchSchedule | None,
    visit_index: int,
) -> _VisitTimes:
    if lunch_schedule is not None:
        return lunch_schedule.visits[visit_index]
    arrival = clock + leg_min
    begin = max(arrival, order.window_start_min)
    return _VisitTimes(clock, arrival, begin, begin + order.duration_min, begin - arrival)


def _time_violations(
    engineer: Engineer, order: Order, begin: int, finish: int, late: int, allow_late: bool
) -> list[Violation]:
    violations: list[Violation] = []
    if late and not allow_late:
        violations.append(
            Violation(
                engineer_id=engineer.id,
                order_id=order.id,
                code="WINDOW",
                text=(
                    f"начало {min_to_hhmm(begin)} позже конца окна "
                    f"{order.window_end} (опоздание {late} мин)"
                ),
            )
        )
    if finish > engineer.shift_end_min:
        violations.append(
            Violation(
                engineer_id=engineer.id,
                order_id=order.id,
                code="SHIFT",
                text=(
                    f"окончание {min_to_hhmm(finish)} выходит за смену "
                    f"{engineer.shift_end} (на {finish - engineer.shift_end_min} мин)"
                ),
            )
        )
    return violations


def _lunch_violation(engineer: Engineer) -> Violation:
    """Нарушение: обед не помещается в окно обеда."""
    earliest, until = lunch_window(engineer)
    return Violation(
        engineer_id=engineer.id,
        order_id=None,
        code="LUNCH",
        text=(
            "не удалось разместить обед с "
            f"{min_to_hhmm(earliest)} до {min_to_hhmm(until)}"
        ),
    )


def _planned_stop(
    order_id: str,
    seq: int,
    leg_km: float,
    leg_min: int,
    times: _VisitTimes,
    late: int,
    allow_late: bool,
) -> Stop:
    """Остановка маршрута по рассчитанным временам визита."""
    return Stop(
        order_id=order_id,
        seq=seq,
        travel_km=round(leg_km, 2),
        travel_min=leg_min,
        departure=min_to_hhmm(times.departure),
        arrival=min_to_hhmm(times.arrival),
        wait_min=times.wait,
        start=min_to_hhmm(times.begin),
        finish=min_to_hhmm(times.finish),
        locked=False,
        late_min=late if allow_late else 0,
    )


def evaluate_route(
    geo: Geo,
    engineer: Engineer,
    order_ids: list[str],
    start: StartState | None = None,
    allow_late: bool = False,
    lunch: bool = False,
) -> tuple[Route, list[Violation]]:
    """Считает времена по порядку посещения и собирает нарушения."""
    start = start or StartState(node=geo.start_node(engineer), available_min=engineer.shift_start_min)
    violations: list[Violation] = []

    stops: list[Stop] = list(start.locked_stops)
    node = start.node
    clock = start.available_min
    stock = geo.equipment_stock(engineer.id)
    used = _equipment_used(geo, start.locked_stops)
    distance_km = start.distance_km
    travel_min = start.travel_min
    work_min = start.work_min
    wait_min = start.wait_min
    lunch_break = start.lunch_break
    lunch_schedule = None
    if lunch and order_ids and lunch_break is None and lunch_starts(engineer, start.available_min):
        lunch_schedule = _schedule_with_lunch(geo, engineer, order_ids, start, allow_late)
        if lunch_schedule is None:
            violations.append(_lunch_violation(engineer))
        else:
            lunch_break = lunch_schedule.lunch_break

    for visit_index, order_id in enumerate(order_ids):
        order = geo.orders[order_id]
        static = check_static(engineer, order)
        if static is not None:
            violations.append(static)
        violations.extend(_consume_equipment(geo, engineer, order_id, stock, used))

        leg_km, leg_min = geo.leg(engineer, node, geo.node(order_id))
        times = _visit_times(order, clock, leg_min, lunch_schedule, visit_index)
        late = max(0, times.begin - order.window_end_min)
        violations.extend(
            _time_violations(engineer, order, times.begin, times.finish, late, allow_late)
        )

        stops.append(_planned_stop(order_id, len(stops) + 1, leg_km, leg_min, times, late, allow_late))

        distance_km += leg_km
        travel_min += leg_min
        wait_min += times.wait
        work_min += order.duration_min
        node = geo.node(order_id)
        clock = times.finish

    if lunch_schedule is not None:
        clock = lunch_schedule.end_min

    route = Route(
        engineer_id=engineer.id,
        stops=stops,
        distance_km=round(distance_km, 2),
        travel_min=travel_min,
        work_min=work_min,
        wait_min=wait_min,
        end_time=min_to_hhmm(clock),
        lunch_break=lunch_break,
    )
    return route, violations


def evaluate(
    geo: Geo,
    assignment: dict[str, list[str]],
    starts: dict[str, StartState] | None = None,
    allow_late: bool = False,
    lunch: bool = False,
) -> tuple[list[Route], list[Violation]]:
    """Пересчитывает все маршруты плана и собирает нарушения по всему плану."""
    starts = starts or {}
    routes: list[Route] = []
    violations: list[Violation] = []

    seen: dict[str, str] = {}
    for engineer_id, order_ids in assignment.items():
        if engineer_id not in geo.engineers:
            violations.append(
                Violation(
                    engineer_id=engineer_id,
                    order_id=None,
                    code="NO_ENGINEER",
                    text=f"в сценарии нет инженера {engineer_id}",
                )
            )
            continue
        engineer = geo.engineers[engineer_id]
        for order_id in order_ids:
            if order_id not in geo.orders:
                violations.append(
                    Violation(
                        engineer_id=engineer_id,
                        order_id=order_id,
                        code="NO_ORDER",
                        text=f"в сценарии нет заявки {order_id}",
                    )
                )
            elif order_id in seen:
                violations.append(
                    Violation(
                        engineer_id=engineer_id,
                        order_id=order_id,
                        code="DUPLICATE",
                        text=f"заявка {order_id} назначена дважды: {seen[order_id]} и {engineer_id}",
                    )
                )
            else:
                seen[order_id] = engineer_id

        known = [o for o in order_ids if o in geo.orders]
        route, route_violations = evaluate_route(
            geo, engineer, known, starts.get(engineer_id), allow_late, lunch
        )
        routes.append(route)
        violations.extend(route_violations)

    order_by_id = {r.engineer_id: r for r in routes}
    routes = [order_by_id[e.id] for e in geo.scenario.engineers if e.id in order_by_id]
    return routes, violations


def can_append(
    geo: Geo, engineer: Engineer, order_ids: list[str], candidate: str, start: StartState | None = None
) -> bool:
    """Помещается ли заявка в конец маршрута быстрая проверка для базового варианта."""
    _, violations = evaluate_route(geo, engineer, [*order_ids, candidate], start)
    return not violations


def best_insertion(
    geo: Geo,
    engineer: Engineer,
    order_ids: list[str],
    candidate: str,
    start: StartState | None = None,
    lunch: bool = False,
) -> tuple[int, float] | None:
    """Самая дешёвая допустимая позиция вставки: (индекс, прирост пробега в км)."""
    if check_static(engineer, geo.orders[candidate]) is not None:
        return None
    base, base_violations = evaluate_route(geo, engineer, order_ids, start, lunch=lunch)
    if base_violations:
        return None

    best: tuple[int, float] | None = None
    for position in range(len(order_ids) + 1):
        trial = [*order_ids[:position], candidate, *order_ids[position:]]
        route, violations = evaluate_route(geo, engineer, trial, start, lunch=lunch)
        if violations:
            continue
        delta = round(route.distance_km - base.distance_km, 3)
        if best is None or delta < best[1]:
            best = (position, delta)
    return best


def first_blocking_violation(
    geo: Geo,
    engineer: Engineer,
    order_ids: list[str],
    candidate: str,
    start: StartState | None = None,
    lunch: bool = False,
) -> Violation | None:
    """Что именно мешает поставить заявку этому инженеру для текста причины."""
    static = check_static(engineer, geo.orders[candidate])
    if static is not None:
        return static
    blocking: Violation | None = None
    for position in range(len(order_ids) + 1):
        trial = [*order_ids[:position], candidate, *order_ids[position:]]
        _, violations = evaluate_route(geo, engineer, trial, start, lunch=lunch)
        if not violations:
            return None
        own = [v for v in violations if v.order_id == candidate]
        found = own[0] if own else violations[0]
        if not own and found.order_id:
            found = found.model_copy(
                update={"text": f"вставка сдвинула бы заявку {found.order_id}: {found.text}"}
            )
        if blocking is None:
            blocking = found
    return blocking
