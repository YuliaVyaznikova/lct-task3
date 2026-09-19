"""Геометрия маршрутов для карты: линии по дорогам вместо прямых.

Чисто оформительская задача. На расчёт плана это не влияет: распределение,
времена и метрики считаются офлайн-моделью (DESIGN.md §5), а здесь
запрашивается только ломаная, по которой маршрут рисуется в интерфейсе.
Поэтому сбой сервиса ничего не ломает — карта просто вернётся к прямым
отрезкам, и в легенде будет написано, как именно она нарисована.

Публичный демонстрационный сервер OSRM держит загруженным только
автомобильный профиль: запросы `walking` и `cycling` возвращают ту же
геометрию, что и `driving`. Поэтому профиль не варьируем и честно
подписываем линии как «по автомобильной сети».
"""

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

#: Публичный сервер OSRM. Используется только для рисования и только если
#: свой экземпляр не задан переменной окружения OSRM_URL.
PUBLIC_OSRM = "https://router.project-osrm.org"

PROFILE = "driving"

#: Больше точек на запрос публичный сервер принимает плохо, а маршруты
#: инженеров заведомо короче.
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
    """Ломаная по дорогам через заданные точки. Возвращает (линия, ошибка)."""
    if len(points) < 2:
        return None, None
    if len(points) > MAX_WAYPOINTS:
        return None, f"слишком много точек в маршруте: {len(points)}"

    path = _cache_path(points)
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8")), None
        except Exception:
            pass  # повреждённый кэш — просто перезапросим

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
        # OSRM отдаёт пары «долгота, широта» — на карте нужен обратный порядок.
        line = [[lat, lon] for lon, lat in payload["routes"][0]["geometry"]["coordinates"]]
    except Exception as exc:
        return None, f"не разобрали геометрию: {exc}"

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(line), encoding="utf-8")
    except OSError:
        pass  # без кэша тоже работает, просто медленнее

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
    """Геометрия всех маршрутов плана. Запросы идут параллельно."""
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
