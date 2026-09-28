"""Модель времени в пути и расстояний."""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from planner.core.models import Transport
from planner.paths import CACHE_DIR

EARTH_RADIUS_KM = 6371.0088

DETOUR_CALIBRATION: tuple[tuple[float, float], ...] = (
    (0.5, 1.74),
    (2.0, 1.61),
    (6.0, 1.48),
    (20.0, 1.25),
    (60.0, 1.19),
)

_CAL_LOG_KM = np.log10([d for d, _ in DETOUR_CALIBRATION])
_CAL_FACTOR = np.array([f for _, f in DETOUR_CALIBRATION])


def detour_factor(straight_km):
    """Коэффициент извилистости для расстояния по прямой."""
    value = np.asarray(straight_km, dtype=float)
    safe = np.maximum(value, 1e-6)
    return np.interp(np.log10(safe), _CAL_LOG_KM, _CAL_FACTOR)


@dataclass(frozen=True)
class Segment:
    """Участок пути: до `upto_km` едем со скоростью `speed_kmh`."""

    upto_km: float
    speed_kmh: float


@dataclass(frozen=True)
class TransportProfile:
    """Профиль движения: постоянная надбавка и кусочно-постоянная скорость."""

    overhead_min: float
    segments: tuple[Segment, ...]

    def minutes(self, distance_km: float) -> float:
        if distance_km <= 0:
            return 0.0
        total = self.overhead_min
        remaining = distance_km
        previous = 0.0
        for segment in self.segments:
            span = min(remaining, segment.upto_km - previous)
            if span > 0:
                total += span / segment.speed_kmh * 60.0
                remaining -= span
            previous = segment.upto_km
            if remaining <= 0:
                break
        if remaining > 0:
            total += remaining / self.segments[-1].speed_kmh * 60.0
        return total


INF = float("inf")

PROFILES: dict[Transport, TransportProfile] = {
    Transport.CAR: TransportProfile(
        overhead_min=5.0,
        segments=(Segment(3.0, 18.0), Segment(10.0, 28.0), Segment(30.0, 45.0), Segment(INF, 65.0)),
    ),
    Transport.BIKE: TransportProfile(
        overhead_min=2.0,
        segments=(Segment(INF, 14.0),),
    ),
    Transport.FOOT: TransportProfile(
        overhead_min=0.0,
        segments=(Segment(INF, 4.5),),
    ),
    Transport.PUBLIC: TransportProfile(
        overhead_min=12.0,
        segments=(Segment(3.0, 14.0), Segment(15.0, 20.0), Segment(INF, 45.0)),
    ),
}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlambda = math.radians(lon2 - lon1)
    h = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def _haversine_matrix(points: list[tuple[float, float]]) -> np.ndarray:
    lat = np.radians(np.array([p[0] for p in points], dtype=float))
    lon = np.radians(np.array([p[1] for p in points], dtype=float))
    dlat = lat[:, None] - lat[None, :]
    dlon = lon[:, None] - lon[None, :]
    h = np.sin(dlat / 2) ** 2 + np.cos(lat)[:, None] * np.cos(lat)[None, :] * np.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(h, 0.0, 1.0)))


class TravelModel:
    """Расстояния и времена между точками для каждого типа транспорта."""

    def __init__(self, points: list[tuple[float, float]]) -> None:
        self.points = points
        straight = _haversine_matrix(points)
        self._distance_km = straight * detour_factor(straight)
        np.fill_diagonal(self._distance_km, 0.0)
        self._time_cache: dict[Transport, np.ndarray] = {}

    @property
    def name(self) -> str:
        return "haversine"

    @property
    def size(self) -> int:
        return len(self.points)

    def distance_m(self) -> np.ndarray:
        """Матрица расстояний в метрах (целые так их ждёт солвер)."""
        return np.rint(self._distance_km * 1000.0).astype(np.int64)

    def distance_km(self, i: int, j: int) -> float:
        return float(self._distance_km[i, j])

    def time_min(self, transport: Transport) -> np.ndarray:
        """Матрица времён в пути (целые минуты) для одного типа транспорта."""
        cached = self._time_cache.get(transport)
        if cached is not None:
            return cached
        profile = PROFILES[transport]
        flat = self._distance_km.ravel()
        minutes = np.array([profile.minutes(float(d)) for d in flat], dtype=float)
        matrix = np.rint(minutes.reshape(self._distance_km.shape)).astype(np.int64)
        np.fill_diagonal(matrix, 0)
        self._time_cache[transport] = matrix
        return matrix

    def travel(self, transport: Transport, i: int, j: int) -> tuple[float, int]:
        """(километры, минуты) для одного переезда."""
        return round(self.distance_km(i, j), 3), int(self.time_min(transport)[i, j])


class OsrmTravel(TravelModel):
    """Расстояния по реальной дорожной сети из OSRM."""

    PROFILE = "driving"

    MAX_POINTS = 100

    def __init__(
        self,
        points: list[tuple[float, float]],
        base_url: str,
        timeout_s: float = 60.0,
        cache_dir: "Path | None" = None,
    ) -> None:
        super().__init__(points)
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.cache_dir = cache_dir or (CACHE_DIR / "osrm")
        self.connected = False
        self.errors: list[str] = []
        self._load()

    @property
    def name(self) -> str:
        if not self.connected:
            return "haversine (osrm недоступен)"
        return "osrm (расстояния по дорогам) + профили скоростей"


    def _cache_path(self) -> "Path":
        payload = json.dumps(
            [[round(lat, 6), round(lon, 6)] for lat, lon in self.points],
            separators=(",", ":"),
        )
        digest = hashlib.sha256(f"{self.PROFILE}|{payload}".encode()).hexdigest()[:16]
        return self.cache_dir / f"{digest}.npz"

    def _load(self) -> None:
        if len(self.points) > self.MAX_POINTS:
            self.errors.append(
                f"точек {len(self.points)}, предел запроса {self.MAX_POINTS}"
            )
            return

        path = self._cache_path()
        if path.is_file():
            try:
                self._apply(np.load(path)["distance_km"])
                self.connected = True
                return
            except Exception as exc:
                self.errors.append(f"кэш повреждён ({exc}), запрашиваем заново")

        distances = self._fetch()
        if distances is None:
            return
        self._apply(distances)
        self.connected = True
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(path, distance_km=distances)
        except OSError as exc:
            self.errors.append(f"не удалось сохранить кэш: {exc}")

    def _apply(self, distance_km: np.ndarray) -> None:
        """Подменяет расстояния и сбрасывает уже посчитанные времена."""
        if distance_km.shape != (len(self.points), len(self.points)):
            raise ValueError("размер матрицы не совпадает с числом точек")
        self._distance_km = distance_km
        self._time_cache.clear()

    def _fetch(self) -> "np.ndarray | None":
        import httpx

        coordinates = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in self.points)
        url = f"{self.base_url}/table/v1/{self.PROFILE}/{coordinates}"
        try:
            response = httpx.get(url, params={"annotations": "distance"}, timeout=self.timeout_s)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            self.errors.append(f"{type(exc).__name__}: {exc}")
            return None

        if payload.get("code") != "Ok" or payload.get("distances") is None:
            self.errors.append(f"ответ без матрицы расстояний ({payload.get('code')})")
            return None

        size = len(self.points)
        try:
            kilometres = np.array(payload["distances"], dtype=float) / 1000.0
            if kilometres.shape != (size, size) or not np.isfinite(kilometres).all():
                raise ValueError("матрица неполная")
        except Exception as exc:
            self.errors.append(str(exc))
            return None

        np.fill_diagonal(kilometres, 0.0)
        return kilometres


def build(
    points: list[tuple[float, float]], osrm_url: str | None = None
) -> TravelModel:
    """Модель движения: OSRM, если он задан и отвечает, иначе офлайн-оценка."""
    url = osrm_url or os.environ.get("OSRM_URL")
    if not url:
        return TravelModel(points)
    model = OsrmTravel(points, url)
    return model if model.connected else TravelModel(points)


def describe() -> str:
    """Человекочитаемое описание модели идёт в README и в объяснения плана."""
    factors = ", ".join(f"{d:g} км: ×{f:g}" for d, f in DETOUR_CALIBRATION)
    lines = [
        "Расстояние: по прямой, умноженной на коэффициент извилистости дорог;"
        f" коэффициент откалиброван по реальной сети ({factors})."
    ]
    for transport, profile in PROFILES.items():
        parts = []
        previous = 0.0
        for segment in profile.segments:
            bound = "далее" if segment.upto_km == INF else f"до {segment.upto_km:g} км"
            parts.append(f"{bound}: {segment.speed_kmh:g} км/ч")
            previous = segment.upto_km
        overhead = f"+{profile.overhead_min:g} мин " if profile.overhead_min else ""
        lines.append(f"  {transport.value}: {overhead}{'; '.join(parts)}")
    return "\n".join(lines)
