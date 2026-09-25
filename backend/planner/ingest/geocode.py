"""Геокодирование адресов выгрузки офлайн-предобработка."""

from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterable

import httpx

from planner.core.models import GeocodeQuality, Order, Scenario
from planner.ingest.address import NormalizedAddress, normalize
from planner.paths import CACHE_DIR, CONFIG_DIR, read_secret

USER_AGENT = "lct2026-task3-routing/0.1 (hackathon prototype)"

MAX_KM_FROM_OFFICE_MOSCOW = 25.0
MAX_KM_FROM_OFFICE_REGION = 120.0
MAX_KM_FROM_DISTRICT_MOSCOW = 5.0
MAX_KM_FROM_DISTRICT_REGION = 25.0

MOSCOW_BBOX = (54.2, 35.1, 56.95, 40.3)

NOMINATIM_DELAY_S = 1.05
DISTRICT_JITTER_M = 300.0


@dataclass
class GeoResult:
    lat: float
    lon: float
    quality: GeocodeQuality
    provider: str
    step: str
    detail: str = ""


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(h))


class Cache:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or CACHE_DIR / "geocode.json"
        self.data: dict[str, dict] = {}
        if self.path.is_file():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))

    def get(self, key: str) -> GeoResult | None:
        raw = self.data.get(key)
        if not raw:
            return None
        return GeoResult(
            lat=raw["lat"],
            lon=raw["lon"],
            quality=GeocodeQuality(raw["quality"]),
            provider=raw["provider"],
            step=raw.get("step", ""),
            detail=raw.get("detail", ""),
        )

    def put(self, key: str, result: GeoResult) -> None:
        payload = asdict(result)
        payload["quality"] = result.quality.value
        self.data[key] = payload

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
            encoding="utf-8",
        )


class Providers:
    """Обёртки над HTTP-геокодерами."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(
            timeout=20.0, headers={"User-Agent": USER_AGENT}, follow_redirects=True
        )
        self.dadata_key = read_secret("DADATA_KEY", "dadata-key.txt")
        self.dadata_secret = read_secret("DADATA_SECRET", "dadata-secret.txt")
        self.yandex_key = read_secret("YANDEX_GEOCODER_KEY", "yandex-key.txt")
        self._last_nominatim = 0.0
        self.errors: list[str] = []

    def dadata(self, addr: NormalizedAddress) -> GeoResult | None:
        if not self.dadata_key:
            return None
        try:
            response = self.client.post(
                "https://suggestions.dadata.ru/suggestions/api/4_1/rs/suggest/address",
                json={"query": addr.raw, "count": 1},
                headers={
                    "Authorization": f"Token {self.dadata_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            response.raise_for_status()
            suggestions = response.json().get("suggestions") or []
        except Exception as exc:
            self.errors.append(f"dadata: {type(exc).__name__}: {exc}")
            return None
        if not suggestions:
            return None
        data = suggestions[0].get("data") or {}
        lat, lon = data.get("geo_lat"), data.get("geo_lon")
        if lat is None or lon is None:
            return None
        qc = str(data.get("qc_geo", "5"))
        quality = {
            "0": GeocodeQuality.EXACT,
            "1": GeocodeQuality.EXACT,
            "2": GeocodeQuality.STREET,
        }.get(qc)
        if quality is None:
            return None
        return GeoResult(
            float(lat), float(lon), quality, "dadata", "1", f"qc_geo={qc}"
        )

    def yandex(self, addr: NormalizedAddress) -> GeoResult | None:
        if not self.yandex_key:
            return None
        try:
            response = self.client.get(
                "https://geocode-maps.yandex.ru/1.x/",
                params={
                    "apikey": self.yandex_key,
                    "geocode": addr.query,
                    "format": "json",
                    "results": 1,
                },
            )
            response.raise_for_status()
            members = response.json()["response"]["GeoObjectCollection"]["featureMember"]
        except Exception as exc:
            self.errors.append(f"yandex: {type(exc).__name__}: {exc}")
            return None
        if not members:
            return None
        obj = members[0]["GeoObject"]
        lon_s, lat_s = obj["Point"]["pos"].split()
        precision = obj["metaDataProperty"]["GeocoderMetaData"].get("precision", "")
        quality = {
            "exact": GeocodeQuality.EXACT,
            "number": GeocodeQuality.EXACT,
            "near": GeocodeQuality.EXACT,
            "street": GeocodeQuality.STREET,
        }.get(precision)
        if quality is None:
            return None
        return GeoResult(
            float(lat_s), float(lon_s), quality, "yandex", "2", f"precision={precision}"
        )

    def _nominatim(self, params: dict, step: str, quality: GeocodeQuality) -> GeoResult | None:
        wait = NOMINATIM_DELAY_S - (time.monotonic() - self._last_nominatim)
        if wait > 0:
            time.sleep(wait)
        try:
            response = self.client.get(
                "https://nominatim.openstreetmap.org/search",
                params={"format": "jsonv2", "limit": 1, "accept-language": "ru", **params},
            )
            self._last_nominatim = time.monotonic()
            response.raise_for_status()
            found = response.json()
        except Exception as exc:
            self._last_nominatim = time.monotonic()
            self.errors.append(f"nominatim: {type(exc).__name__}: {exc}")
            return None
        if not found:
            return None
        item = found[0]
        return GeoResult(
            float(item["lat"]),
            float(item["lon"]),
            quality,
            "nominatim",
            step,
            item.get("type", ""),
        )

    def nominatim_structured(self, addr: NormalizedAddress) -> GeoResult | None:
        if not addr.street or not addr.house:
            return None
        return self._nominatim(
            {
                "street": f"{addr.house} {addr.street}",
                "city": addr.settlement or addr.city,
                "country": "Россия",
            },
            "3",
            GeocodeQuality.EXACT,
        )

    def nominatim_no_korpus(self, addr: NormalizedAddress) -> GeoResult | None:
        if not addr.street or not addr.house:
            return None
        base = addr.house.split("к")[0].split("с")[0]
        if base == addr.house or not base:
            return None
        return self._nominatim(
            {
                "street": f"{base} {addr.street}",
                "city": addr.settlement or addr.city,
                "country": "Россия",
            },
            "4",
            GeocodeQuality.EXACT,
        )

    def photon(self, addr: NormalizedAddress) -> GeoResult | None:
        try:
            response = self.client.get(
                "https://photon.komoot.io/api/",
                params={"q": addr.query, "lang": "ru", "limit": 1},
            )
            response.raise_for_status()
            features = response.json().get("features") or []
        except Exception as exc:
            self.errors.append(f"photon: {type(exc).__name__}: {exc}")
            return None
        if not features:
            return None
        feature = features[0]
        lon, lat = feature["geometry"]["coordinates"]
        props = feature.get("properties", {})
        quality = GeocodeQuality.EXACT if props.get("housenumber") else GeocodeQuality.STREET
        return GeoResult(float(lat), float(lon), quality, "photon", "5", props.get("osm_key", ""))

    def nominatim_street_only(self, addr: NormalizedAddress) -> GeoResult | None:
        if not addr.street:
            return None
        return self._nominatim(
            {"street": addr.street, "city": addr.settlement or addr.city, "country": "Россия"},
            "6",
            GeocodeQuality.STREET,
        )


class Districts:
    """Центроиды районов последняя ступень лестницы и проверка правдоподобия."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or CONFIG_DIR / "districts.csv"
        self.points: dict[str, tuple[float, float]] = {}
        if self.path.is_file():
            import csv

            with self.path.open(encoding="utf-8", newline="") as fh:
                for row in csv.DictReader(fh, delimiter=";"):
                    if row.get("lat") and row.get("lon"):
                        self.points[row["district"].strip().casefold()] = (
                            float(row["lat"]),
                            float(row["lon"]),
                        )

    def get(self, district: str) -> tuple[float, float] | None:
        return self.points.get((district or "").strip().casefold())

    def put(self, district: str, point: tuple[float, float]) -> None:
        self.points[district.strip().casefold()] = point

    def save(self, names: dict[str, str]) -> None:
        import csv

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh, delimiter=";")
            writer.writerow(["district", "lat", "lon"])
            for key in sorted(self.points):
                lat, lon = self.points[key]
                writer.writerow([names.get(key, key), f"{lat:.6f}", f"{lon:.6f}"])


def _jitter(lat: float, lon: float, key: str) -> tuple[float, float]:
    """Детерминированный сдвиг до 300 м, чтобы заявки одного района не совпадали точь-в-точь."""
    import hashlib

    digest = hashlib.sha256(key.encode("utf-8")).digest()
    angle = (digest[0] / 255.0) * 2 * math.pi
    radius = (digest[1] / 255.0) * DISTRICT_JITTER_M
    dlat = (radius * math.cos(angle)) / 111_320.0
    dlon = (radius * math.sin(angle)) / (111_320.0 * math.cos(math.radians(lat)))
    return lat + dlat, lon + dlon


def _in_moscow_region(lat: float, lon: float) -> bool:
    lat_min, lon_min, lat_max, lon_max = MOSCOW_BBOX
    return lat_min <= lat <= lat_max and lon_min <= lon <= lon_max


def _plausible(
    result: GeoResult,
    addr: NormalizedAddress,
    office: tuple[float, float] | None,
    district_point: tuple[float, float] | None,
) -> str | None:
    """Возвращает причину отбраковки или None, если ответ правдоподобен."""
    if not _in_moscow_region(result.lat, result.lon):
        return "вне Московского региона"
    if office is not None:
        limit = (
            MAX_KM_FROM_OFFICE_MOSCOW if addr.city == "Москва" else MAX_KM_FROM_OFFICE_REGION
        )
        distance = haversine_km((result.lat, result.lon), office)
        if distance > limit:
            return f"{distance:.0f} км от офиса при пределе {limit:.0f}"
    if district_point is not None:
        limit = (
            MAX_KM_FROM_DISTRICT_MOSCOW
            if addr.city == "Москва"
            else MAX_KM_FROM_DISTRICT_REGION
        )
        distance = haversine_km((result.lat, result.lon), district_point)
        if distance > limit:
            return f"{distance:.0f} км от центра района при пределе {limit:.0f}"
    return None


def _first_plausible_provider_result(
    address: NormalizedAddress,
    providers: Providers,
    office: tuple[float, float] | None,
    district_point: tuple[float, float] | None,
) -> tuple[GeoResult | None, list[str]]:
    rejected: list[str] = []
    sources: tuple[tuple[str, Callable[[NormalizedAddress], GeoResult | None]], ...] = (
        ("dadata", providers.dadata),
        ("yandex", providers.yandex),
        ("nominatim/дом", providers.nominatim_structured),
        ("nominatim/без корпуса", providers.nominatim_no_korpus),
        ("photon", providers.photon),
        ("nominatim/улица", providers.nominatim_street_only),
    )
    for name, geocode in sources:
        result = geocode(address)
        if result is None:
            continue
        reason = _plausible(result, address, office, district_point)
        if reason:
            rejected.append(f"{name}: отброшен ({reason})")
            continue
        return result, rejected
    return None, rejected


def geocode_one(
    raw_address: str,
    district: str,
    providers: Providers,
    districts: Districts,
    cache: Cache,
    office: tuple[float, float] | None = None,
    overrides: dict[str, tuple[float, float]] | None = None,
) -> tuple[GeoResult, list[str]]:
    """Прогоняет один адрес по лестнице."""
    address = normalize(raw_address)

    key = raw_address.strip()
    if overrides and key in overrides:
        lat, lon = overrides[key]
        return GeoResult(lat, lon, GeocodeQuality.MANUAL, "override", "0"), []

    cached = cache.get(key)
    if cached is not None:
        return cached, []

    district_point = districts.get(district)
    result, rejected = _first_plausible_provider_result(
        address, providers, office, district_point
    )
    if result is None and district_point is not None:
        lat, lon = _jitter(district_point[0], district_point[1], key)
        result = GeoResult(lat, lon, GeocodeQuality.DISTRICT, "district", "7", district)
    if result is None:
        raise RuntimeError(f"не удалось определить координаты и нет центроида района: {raw_address!r}")
    cache.put(key, result)
    return result, rejected


def _find_district_point(
    district: str, address: str, providers: Providers
) -> tuple[float, float] | None:
    city = normalize(address).city
    query_name = district.replace("GPON", "").strip()
    for query in (
        {"q": f"{query_name}, {city}, Россия"},
        {"q": f"{query_name}, Россия"},
    ):
        found = providers._nominatim(query, "district", GeocodeQuality.DISTRICT)
        if found is not None and _in_moscow_region(found.lat, found.lon):
            return found.lat, found.lon
    return None


def resolve_districts(
    scenarios: Iterable[Scenario], providers: Providers, districts: Districts
) -> dict[str, str]:
    """Заполняет центроиды районов, которых ещё нет в справочнике."""
    names: dict[str, str] = {}
    for scenario in scenarios:
        for order in scenario.orders:
            district = (order.district or "").strip()
            if not district:
                continue
            key = district.casefold()
            names[key] = district
            if districts.get(district) is not None:
                continue
            point = _find_district_point(district, order.address, providers)
            if point is not None:
                districts.put(district, point)
    return names


def apply_to_scenario(
    scenario: Scenario,
    providers: Providers,
    districts: Districts,
    cache: Cache,
    overrides: dict[str, tuple[float, float]] | None = None,
    progress: Callable[[str], None] | None = None,
) -> list[tuple[Order, GeoResult, list[str]]]:
    """Проставляет координаты офису и всем заявкам сценария."""
    office_result, _ = geocode_one(
        scenario.office.address, "", providers, districts, cache, None, overrides
    )
    scenario.office.lat, scenario.office.lon = office_result.lat, office_result.lon
    office = (office_result.lat, office_result.lon)

    report: list[tuple[Order, GeoResult, list[str]]] = []
    for index, order in enumerate(scenario.orders, start=1):
        result, log = geocode_one(
            order.address, order.district, providers, districts, cache, office, overrides
        )
        order.lat, order.lon = result.lat, result.lon
        order.geocode_quality = result.quality
        order.address_normalized = normalize(order.address).query
        report.append((order, result, log))
        if progress:
            progress(f"  [{index:>3}/{len(scenario.orders)}] {result.quality.value:<8} {order.address}")
    providers_used = {r.provider for _, r, _ in report}
    scenario.meta.geocoder = "+".join(sorted(providers_used))
    return report


def load_overrides(path: Path | None = None) -> dict[str, tuple[float, float]]:
    path = path or CONFIG_DIR / "geocode_overrides.csv"
    if not path.is_file():
        return {}
    import csv

    result: dict[str, tuple[float, float]] = {}
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter=";"):
            if row.get("address") and row.get("lat") and row.get("lon"):
                result[row["address"].strip()] = (float(row["lat"]), float(row["lon"]))
    return result
