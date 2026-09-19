"""Модель времени в пути и расстояний (DESIGN.md §5).

Единая матрица на сценарий и тип транспорта. По умолчанию — офлайн-модель
на расстоянии по прямой с коэффициентом извилистости и кусочно-постоянной
скоростью: в плотной застройке медленнее, на вылетных трассах быстрее.

Почему скорость зависит от расстояния. В выгрузке Юго-Востока есть Домодедово,
Кашира и Ступино — до них 25–91 км от офиса. С единой «городской» скоростью
22 км/ч поездка в Каширу заняла бы четыре часа, и весь кластер стал бы
недостижимым, хотя в контрольном распределении его обслуживают штатно.
Кусочная скорость даёт около 1 ч 50 мин, что близко к реальности.

Все допущения перечислены в README (ТЗ §3.2 требует их описать).
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from planner.core.models import Transport
from planner.paths import CACHE_DIR

EARTH_RADIUS_KM = 6371.0088

#: Дорога всегда длиннее прямой. 1.3 — обычная оценка для плотной городской сети.
DETOUR_FACTOR = 1.3


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
        if remaining > 0:  # хвост за последним порогом идёт по последней скорости
            total += remaining / self.segments[-1].speed_kmh * 60.0
        return total


INF = float("inf")

PROFILES: dict[Transport, TransportProfile] = {
    # Автомобиль: +5 мин на парковку и подход (Q&A: мелочи вроде парковки
    # закладываются во время на дорогу, отдельно их не моделируем).
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
    # Общественный транспорт: подход к остановке и ожидание — 12 мин,
    # дальше наземный транспорт, на длинных плечах — метро и электричка.
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

    name = "haversine"

    def __init__(self, points: list[tuple[float, float]]) -> None:
        self.points = points
        self._distance_km = _haversine_matrix(points) * DETOUR_FACTOR
        np.fill_diagonal(self._distance_km, 0.0)
        self._time_cache: dict[Transport, np.ndarray] = {}

    @property
    def size(self) -> int:
        return len(self.points)

    def distance_m(self) -> np.ndarray:
        """Матрица расстояний в метрах (целые — так их ждёт солвер)."""
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


def build(points: list[tuple[float, float]]) -> TravelModel:
    return TravelModel(points)


def points_hash(points: list[tuple[float, float]], name: str) -> str:
    payload = json.dumps([[round(p[0], 6), round(p[1], 6)] for p in points], separators=(",", ":"))
    return hashlib.sha256(f"{name}|{payload}".encode()).hexdigest()[:16]


def cache_path(points: list[tuple[float, float]], name: str) -> Path:
    return CACHE_DIR / "matrices" / f"{points_hash(points, name)}.npz"


def describe() -> str:
    """Человекочитаемое описание модели — идёт в README и в объяснения плана."""
    lines = [f"Расстояние: по прямой × {DETOUR_FACTOR} (коэффициент извилистости дорог)."]
    for transport, profile in PROFILES.items():
        parts = []
        previous = 0.0
        for segment in profile.segments:
            bound = "далее" if segment.upto_km == INF else f"до {segment.upto_km:g} км"
            parts.append(f"{bound} — {segment.speed_kmh:g} км/ч")
            previous = segment.upto_km
        overhead = f"+{profile.overhead_min:g} мин " if profile.overhead_min else ""
        lines.append(f"  {transport.value}: {overhead}{'; '.join(parts)}")
    return "\n".join(lines)
