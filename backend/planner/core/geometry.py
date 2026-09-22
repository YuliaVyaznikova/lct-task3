"""Геометрия маршрутов для карты: линии по дорогам вместо прямых."""

from __future__ import annotations

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from planner.core.models import Plan
from planner.core.validate import Geo
from planner.paths import CACHE_DIR

PUBLIC_OSRM = "https://router.project-osrm.org"

PROFILE = "driving"

MAX_WAYPOINTS = 25

TIMEOUT_S = 25.0


@dataclass
class PlanGeometry:
    available: bool
    source: str = ""
    routes: dict[str, list[list[float]]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def _cache_path(points: list[tuple[float, float]]) -> Path:
    payload = json.dumps(
        [[round(lat, 6), round(lon, 6)] for lat, lon in points], separators=(",", ":")
    )
    digest = hashlib.sha256(f"{PROFILE}|{payload}".encode()).hexdigest()[:16]
    return CACHE_DIR / "geometry" / f"{digest}.json"


def fetch_line(
    points: list[tuple[float, float]], base_url: str
) -> tuple[list[list[float]] | None, str | None]:
    """Ломаная по дорогам через заданные точки."""
    if len(points) < 2:
        return None, None
    if len(points) > MAX_WAYPOINTS:
        return None, f"слишком много точек в маршруте: {len(points)}"

    path = _cache_path(points)
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8")), None
        except Exception:
            pass

    import httpx

    coordinates = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in points)
    url = f"{base_url.rstrip('/')}/route/v1/{PROFILE}/{coordinates}"
    try:
        response = httpx.get(
            url,
            params={"overview": "full", "geometries": "geojson", "continue_straight": "false"},
            timeout=TIMEOUT_S,
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

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(line), encoding="utf-8")
    except OSError:
        pass

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
        order = geo.orders.get(stop.order_id)
        if order is not None and order.has_coords:
            points.append(order.coords)
    return points


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
        if line:
            result.routes[engineer_id] = line
        elif error:
            result.errors.append(f"{engineer_id}: {error}")

    result.available = bool(result.routes)
    return result
