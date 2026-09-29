"""Геометрия маршрутов для карты: линии по дорогам вместо прямых."""

from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from planner.core.models import Plan, Scenario
from planner.core.travel import OSRM_PROFILE, PUBLIC_OSRM, haversine_km, osrm_cache_key
from planner.core.validate import Geo
from planner.paths import CACHE_DIR

logger = logging.getLogger(__name__)

MAX_WAYPOINTS = 25

TIMEOUT_S = 25.0

LEG_TIMEOUT_S = 6.0

LEG_WORKERS = 4

LEG_DEADLINE_S = 15.0

LEG_COOLDOWN_S = 30.0

MAX_LEGS = 600

Leg = tuple[tuple[float, float], tuple[float, float]]

_service_down_until = 0.0


@dataclass
class PlanGeometry:
    available: bool
    source: str = ""
    routes: dict[str, list[list[float]]] = field(default_factory=dict)
    legs: dict[str, list[list[list[float]]]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def _cache_path(points: list[tuple[float, float]]) -> Path:
    return CACHE_DIR / "geometry" / f"{osrm_cache_key(points)}.json"


def _cached_line(points: list[tuple[float, float]]) -> list[list[float]] | None:
    path = _cache_path(points)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("кэш геометрии %s не прочитан, запрашиваем заново: %s", path, exc)
        return None


def _store_line(points: list[tuple[float, float]], line: list[list[float]]) -> None:
    path = _cache_path(points)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(line), encoding="utf-8")
    except OSError as exc:
        logger.warning("геометрия не сохранена в кэш %s: %s", path, exc)


def fetch_line(
    points: list[tuple[float, float]], base_url: str, timeout: float = TIMEOUT_S
) -> tuple[list[list[float]] | None, str | None]:
    """Ломаная по дорогам через заданные точки."""
    if len(points) < 2:
        return None, None
    if len(points) > MAX_WAYPOINTS:
        return None, f"слишком много точек в маршруте: {len(points)}"

    cached = _cached_line(points)
    if cached is not None:
        return cached, None

    import httpx

    coordinates = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in points)
    url = f"{base_url.rstrip('/')}/route/v1/{OSRM_PROFILE}/{coordinates}"
    try:
        response = httpx.get(
            url,
            params={"overview": "full", "geometries": "geojson", "continue_straight": "false"},
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"

    if payload.get("code") != "Ok" or not payload.get("routes"):
        return None, f"ответ без маршрута ({payload.get('code')})"

    try:
        line = [[lat, lon] for lon, lat in payload["routes"][0]["geometry"]["coordinates"]]
    except Exception as exc:
        return None, f"не разобрали геометрию: {exc}"

    _store_line(points, line)
    return line, None


def route_points(geo: Geo, plan: Plan, engineer_id: str) -> list[tuple[float, float]]:
    """Точки маршрута: старт инженера, затем адреса визитов по порядку."""
    route = next((r for r in plan.routes if r.engineer_id == engineer_id), None)
    if route is None or not route.stops:
        return []
    engineer = geo.engineers[engineer_id]
    start = engineer.start if engineer.start.has_coords else geo.scenario.office
    points = [start.coords]
    for stop in route.stops:
        points.append(geo.orders[stop.order_id].coords)
    return points


def split_legs(
    points: list[tuple[float, float]], line: list[list[float]] | None
) -> list[list[list[float]]]:
    """Делит дорожную линию по визитам; ненадёжные участки заменяет прямыми."""
    direct = [
        [[*start], [*finish]] for start, finish in zip(points, points[1:])
    ]
    if not line or len(line) < 2:
        return direct

    cuts = [0]
    for point in points[1:-1]:
        prior = cuts[-1]
        cut = min(
            range(prior, len(line)),
            key=lambda index: haversine_km(*point, *line[index]),
        )
        cuts.append(cut)
    cuts.append(len(line) - 1)

    legs = []
    for index, (start, finish) in enumerate(zip(points, points[1:])):
        left, right = cuts[index : index + 2]
        if (
            right <= left
            or haversine_km(*start, *line[left]) > 0.5
            or haversine_km(*finish, *line[right]) > 0.5
        ):
            legs.append(direct[index])
            continue
        leg = [[*start], *line[left + 1 : right], [*finish]]
        legs.append(leg)
    return legs


def build(geo: Geo, plan: Plan, base_url: str | None = None) -> PlanGeometry:
    """Геометрия всех маршрутов плана."""
    url = base_url or os.environ.get("OSRM_URL") or PUBLIC_OSRM
    tasks = {
        route.engineer_id: route_points(geo, plan, route.engineer_id)
        for route in plan.routes
        if route.stops
    }
    tasks = {engineer_id: points for engineer_id, points in tasks.items() if len(points) >= 2}
    if not tasks:
        return PlanGeometry(available=False, errors=["в плане нет маршрутов"])

    result = PlanGeometry(available=False, source=url)
    with ThreadPoolExecutor(max_workers=6) as pool:
        fetched = dict(
            zip(
                tasks,
                pool.map(lambda points: fetch_line(points, url), tasks.values()),
            )
        )

    for engineer_id, (line, error) in fetched.items():
        result.legs[engineer_id] = split_legs(tasks[engineer_id], line)
        if line:
            result.routes[engineer_id] = line
        elif error:
            result.errors.append(f"{engineer_id}: {error}")

    result.available = bool(result.routes)
    return result


def sequence_legs(
    scenario: Scenario, sequences: dict[str, list[str]]
) -> dict[str, list[Leg | None]]:
    """Пары точек для каждого перехода маршрута; None там, где координат нет."""
    engineers = scenario.engineers_by_id
    orders = scenario.orders_by_id
    result: dict[str, list[Leg | None]] = {}
    for engineer_id, order_ids in sequences.items():
        engineer = engineers.get(engineer_id)
        if engineer is None:
            result[engineer_id] = [None] * len(order_ids)
            continue
        start = engineer.start if engineer.start.has_coords else scenario.office
        previous = start.coords if start.has_coords else None
        legs: list[Leg | None] = []
        for order_id in order_ids:
            order = orders.get(order_id)
            current = order.coords if order is not None and order.has_coords else None
            legs.append((previous, current) if previous and current else None)
            previous = current
        result[engineer_id] = legs
    return result


def leg_chains(pairs: dict[str, list[Leg | None]]) -> list[list[Leg]]:
    """Непрерывные цепочки переходов каждого маршрута без пропусков координат."""
    chains: list[list[Leg]] = []
    for legs in pairs.values():
        chain: list[Leg] = []
        for leg in [*legs, None]:
            if leg is not None:
                chain.append(leg)
                continue
            if chain:
                chains.append(chain)
            chain = []
    return chains


def _fetch_leg(leg: Leg, base_url: str) -> tuple[dict[Leg, list[list[float]]], bool]:
    line, error = fetch_line([*leg], base_url, LEG_TIMEOUT_S)
    return ({leg: line} if line else {}), error is not None


def _fetch_chain(chain: list[Leg], base_url: str) -> tuple[dict[Leg, list[list[float]]], bool]:
    points = [chain[0][0], *(leg[1] for leg in chain)]
    line, error = fetch_line(points, base_url, LEG_TIMEOUT_S)
    lines: dict[Leg, list[list[float]]] = {}
    for leg, piece in zip(chain, split_legs(points, line)):
        if len(piece) < 3:
            continue
        lines[leg] = piece[1:-1]
        _store_line([*leg], lines[leg])
    return lines, error is not None


def _run(tasks: list, base_url: str, found: dict, deadline: float) -> int:
    if not tasks:
        return 0
    pool = ThreadPoolExecutor(max_workers=LEG_WORKERS)
    futures = [pool.submit(task, item, base_url) for task, item in tasks]
    failures = 0
    try:
        for future in as_completed(futures, timeout=max(deadline - time.monotonic(), 0.1)):
            lines, failed = future.result()
            found.update(lines)
            failures += failed
    except TimeoutError:
        failures = len(tasks)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return failures


def fetch_legs(
    legs: set[Leg], base_url: str | None = None, chains: list[list[Leg]] | None = None
) -> dict[Leg, list[list[float]] | None]:
    """Дорожная линия для каждого перехода; недоступные участки остаются None."""
    global _service_down_until

    url = base_url or os.environ.get("OSRM_URL") or PUBLIC_OSRM
    found: dict[Leg, list[list[float]] | None] = {leg: _cached_line([*leg]) for leg in legs}
    missing = {leg for leg, line in found.items() if line is None}
    if not missing or time.monotonic() < _service_down_until:
        return found

    deadline = time.monotonic() + LEG_DEADLINE_S
    whole = [
        chain
        for chain in chains or []
        if len(chain) < MAX_WAYPOINTS and sum(leg in missing for leg in chain) >= 2
    ]
    failures = _run([(_fetch_chain, chain) for chain in whole], url, found, deadline)
    tasks = len(whole)
    rest = [leg for leg in missing if found[leg] is None]
    failures += _run([(_fetch_leg, leg) for leg in rest], url, found, deadline)
    tasks += len(rest)

    if failures == tasks:
        _service_down_until = time.monotonic() + LEG_COOLDOWN_S
    return found
