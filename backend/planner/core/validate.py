"""Арифметика маршрута и проверка ограничений (DESIGN.md §8).

Единственный источник истины о допустимости плана. Через него проходят
и солвер, и базовый вариант, и ручное переназначение, и объяснения:
времена и метрики всегда пересчитываются здесь, а не берутся из солвера.
Это защищает от расхождения между тем, что показано пользователю,
и тем, что на самом деле посчитал оптимизатор.

Три группы обязательных ограничений (ТЗ §2.2):
  Квалификация — требуемый навык заявки входит в навыки инженера;
  Время       — начало работ попадает в окно, окончание укладывается в смену;
  Ресурс      — если у заявки задан требуемый транспорт, он совпадает с транспортом инженера.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from planner.core.models import (
    Engineer,
    Order,
    Route,
    Scenario,
    Stop,
    Violation,
)
from planner.core.timeutil import min_to_hhmm
from planner.core.travel import TravelModel


class Geo:
    """Индексация точек сценария: заявки + офис, и доступ к матрицам расстояний."""

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
        self.travel = travel or TravelModel(points)
        self.orders = scenario.orders_by_id
        self.engineers = scenario.engineers_by_id

    def node(self, order_id: str) -> int:
        return self.order_index[order_id]

    def start_node(self, engineer: Engineer) -> int:
        """Стартовая точка инженера. По умолчанию — офис региона (ТЗ §2.4)."""
        if engineer.start.has_coords and engineer.start.coords != self.scenario.office.coords:
            # Персональная точка старта встречается при перепланировании.
            for order_id, index in self.order_index.items():
                if self.orders[order_id].coords == engineer.start.coords:
                    return index
        return self.office_index

    def leg(self, engineer: Engineer, from_node: int, to_node: int) -> tuple[float, int]:
        return self.travel.travel(engineer.transport, from_node, to_node)


@dataclass
class StartState:
    """Откуда и когда инженер готов ехать. При обычном планировании — офис и начало смены.

    `closed` означает, что новых заявок инженер не получит (например, стал
    недоступен), но уже начатые визиты остаются в плане: диспетчер должен
    видеть, что успели сделать до события.
    """

    node: int
    available_min: int
    locked_stops: list[Stop] = field(default_factory=list)
    distance_km: float = 0.0
    travel_min: int = 0
    work_min: int = 0
    wait_min: int = 0
    closed: bool = False


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
                f"заявке нужен транспорт «{order.required_transport.value}», "
                f"у {engineer.name} — «{engineer.transport.value}»"
            ),
        )
    return None


def evaluate_route(
    geo: Geo,
    engineer: Engineer,
    order_ids: list[str],
    start: StartState | None = None,
) -> tuple[Route, list[Violation]]:
    """Считает времена по порядку посещения и собирает нарушения."""
    start = start or StartState(node=geo.start_node(engineer), available_min=engineer.shift_start_min)
    violations: list[Violation] = []

    stops: list[Stop] = list(start.locked_stops)
    node = start.node
    clock = start.available_min
    distance_km = start.distance_km
    travel_min = start.travel_min
    work_min = start.work_min
    wait_min = start.wait_min

    for seq, order_id in enumerate(order_ids, start=len(stops) + 1):
        order = geo.orders[order_id]
        static = check_static(engineer, order)
        if static is not None:
            violations.append(static)

        leg_km, leg_min = geo.leg(engineer, node, geo.node(order_id))
        arrival = clock + leg_min
        # Приехать раньше окна можно, начать работу — нет (Q&A, блок 5).
        begin = max(arrival, order.window_start_min)
        wait = begin - arrival
        finish = begin + order.duration_min

        if begin > order.window_end_min:
            violations.append(
                Violation(
                    engineer_id=engineer.id,
                    order_id=order_id,
                    code="WINDOW",
                    text=(
                        f"начало {min_to_hhmm(begin)} позже конца окна "
                        f"{order.window_end} (опоздание {begin - order.window_end_min} мин)"
                    ),
                )
            )
        if finish > engineer.shift_end_min:
            violations.append(
                Violation(
                    engineer_id=engineer.id,
                    order_id=order_id,
                    code="SHIFT",
                    text=(
                        f"окончание {min_to_hhmm(finish)} выходит за смену "
                        f"{engineer.shift_end} (на {finish - engineer.shift_end_min} мин)"
                    ),
                )
            )

        stops.append(
            Stop(
                order_id=order_id,
                seq=seq,
                travel_km=round(leg_km, 2),
                travel_min=leg_min,
                arrival=min_to_hhmm(arrival),
                wait_min=wait,
                start=min_to_hhmm(begin),
                finish=min_to_hhmm(finish),
                locked=False,
            )
        )

        distance_km += leg_km
        travel_min += leg_min
        wait_min += wait
        work_min += order.duration_min
        node = geo.node(order_id)
        clock = finish

    route = Route(
        engineer_id=engineer.id,
        stops=stops,
        distance_km=round(distance_km, 2),
        travel_min=travel_min,
        work_min=work_min,
        wait_min=wait_min,
        end_time=min_to_hhmm(clock),
    )
    return route, violations


def evaluate(
    geo: Geo,
    assignment: dict[str, list[str]],
    starts: dict[str, StartState] | None = None,
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
        route, route_violations = evaluate_route(geo, engineer, known, starts.get(engineer_id))
        routes.append(route)
        violations.extend(route_violations)

    order_by_id = {r.engineer_id: r for r in routes}
    routes = [order_by_id[e.id] for e in geo.scenario.engineers if e.id in order_by_id]
    return routes, violations


# ------------------------------------------------------------------ вставки


def can_append(
    geo: Geo, engineer: Engineer, order_ids: list[str], candidate: str, start: StartState | None = None
) -> bool:
    """Помещается ли заявка в конец маршрута — быстрая проверка для базового варианта."""
    _, violations = evaluate_route(geo, engineer, [*order_ids, candidate], start)
    return not violations


def best_insertion(
    geo: Geo,
    engineer: Engineer,
    order_ids: list[str],
    candidate: str,
    start: StartState | None = None,
) -> tuple[int, float] | None:
    """Самая дешёвая допустимая позиция вставки: (индекс, прирост пробега в км).

    Используется объяснениями («на сколько дороже было бы у другого инженера»)
    и ручным переназначением в режиме «вставить в лучшую позицию».
    """
    if check_static(engineer, geo.orders[candidate]) is not None:
        return None
    base, base_violations = evaluate_route(geo, engineer, order_ids, start)
    if base_violations:
        return None

    best: tuple[int, float] | None = None
    for position in range(len(order_ids) + 1):
        trial = [*order_ids[:position], candidate, *order_ids[position:]]
        route, violations = evaluate_route(geo, engineer, trial, start)
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
) -> Violation | None:
    """Что именно мешает поставить заявку этому инженеру — для текста причины."""
    static = check_static(engineer, geo.orders[candidate])
    if static is not None:
        return static
    blocking: Violation | None = None
    for position in range(len(order_ids) + 1):
        trial = [*order_ids[:position], candidate, *order_ids[position:]]
        _, violations = evaluate_route(geo, engineer, trial, start)
        if not violations:
            return None
        # Мешать может как сама заявка, так и соседняя, которую сдвинула бы вставка;
        # во втором случае это нужно назвать явно, иначе текст вводит в заблуждение.
        own = [v for v in violations if v.order_id == candidate]
        found = own[0] if own else violations[0]
        if not own and found.order_id:
            found = found.model_copy(
                update={"text": f"вставка сдвинула бы заявку {found.order_id}: {found.text}"}
            )
        if blocking is None:
            blocking = found
    return blocking
