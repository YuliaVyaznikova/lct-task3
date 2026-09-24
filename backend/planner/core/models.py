"""Канонические модели предметной области."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .timeutil import hhmm_to_min

HHMM = Annotated[str, Field(pattern=r"^\d{1,2}:\d{2}$")]


class Skill(StrEnum):
    """Справочник навыков."""

    LOCAL = "local"
    CONNECTION = "connection"
    EMERGENCY = "emergency"


class Transport(StrEnum):
    """Справочник типов транспорта."""

    CAR = "car"
    FOOT = "foot"
    BIKE = "bike"
    PUBLIC = "public"


class Priority(StrEnum):
    """Приоритет заявки."""

    NORMAL = "normal"
    URGENT = "urgent"


class GeocodeQuality(StrEnum):
    EXACT = "exact"
    STREET = "street"
    DISTRICT = "district"
    MANUAL = "manual"
    NONE = "none"


class ReasonCode(StrEnum):
    """Причины, по которым заявка не назначена."""

    NO_SKILL = "NO_SKILL"
    NO_TRANSPORT = "NO_TRANSPORT"
    NO_EQUIPMENT = "NO_EQUIPMENT"
    SHIFT_MISMATCH = "SHIFT_MISMATCH"
    UNREACHABLE = "UNREACHABLE"
    CAPACITY = "CAPACITY"
    NO_COORDS = "NO_COORDS"
    CANCELLED = "CANCELLED"
    ENGINEER_UNAVAILABLE = "ENGINEER_UNAVAILABLE"
    MANUAL = "MANUAL"


SKILL_RU: dict[Skill, str] = {
    Skill.LOCAL: "Локальные работы",
    Skill.CONNECTION: "Подключение и дозаказы",
    Skill.EMERGENCY: "Аварийные работы",
}

TRANSPORT_RU: dict[Transport, str] = {
    Transport.CAR: "автомобиль",
    Transport.FOOT: "пешком",
    Transport.BIKE: "велосипед",
    Transport.PUBLIC: "общественный транспорт",
}

PRIORITY_RU: dict[Priority, str] = {
    Priority.NORMAL: "обычная",
    Priority.URGENT: "срочная",
}


class Base(BaseModel):
    model_config = ConfigDict(use_enum_values=False, extra="forbid")


class Point(Base):
    address: str
    lat: float | None = None
    lon: float | None = None

    @property
    def has_coords(self) -> bool:
        return self.lat is not None and self.lon is not None

    @property
    def coords(self) -> tuple[float, float]:
        if self.lat is None or self.lon is None:
            raise ValueError(f"нет координат у точки {self.address!r}")
        return self.lat, self.lon


class Order(Base):
    """Заявка на выезд."""

    id: str
    external_id: str = ""
    address: str
    address_normalized: str = ""
    district: str = ""
    lat: float | None = None
    lon: float | None = None
    geocode_quality: GeocodeQuality = GeocodeQuality.NONE

    skill: Skill
    work_type: str = ""
    description: str = ""
    duration_min: int = Field(gt=0)
    window_start: HHMM
    window_end: HHMM
    priority: Priority = Priority.NORMAL
    priority_tier: int = 3
    required_transport: Transport | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)

    @property
    def window_start_min(self) -> int:
        return hhmm_to_min(self.window_start)

    @property
    def window_end_min(self) -> int:
        return hhmm_to_min(self.window_end)

    @property
    def has_coords(self) -> bool:
        return self.lat is not None and self.lon is not None

    @property
    def coords(self) -> tuple[float, float]:
        if self.lat is None or self.lon is None:
            raise ValueError(f"нет координат у заявки {self.id}")
        return self.lat, self.lon

    @property
    def label(self) -> str:
        return f"{self.id} ({self.address})"


class Engineer(Base):
    """Исполнитель."""

    id: str
    name: str
    skills: list[Skill] = Field(min_length=1, max_length=3)
    transport: Transport
    shift_start: HHMM
    shift_end: HHMM
    start: Point

    @property
    def shift_start_min(self) -> int:
        return hhmm_to_min(self.shift_start)

    @property
    def shift_end_min(self) -> int:
        return hhmm_to_min(self.shift_end)

    def can_do(self, order: Order) -> bool:
        if order.skill not in self.skills:
            return False
        if order.required_transport is not None and order.required_transport != self.transport:
            return False
        return True

    @property
    def skills_ru(self) -> str:
        return ", ".join(SKILL_RU[s].lower() for s in self.skills)


class UrgentOrderEvent(Base):
    type: Literal["urgent_order"] = "urgent_order"
    time: HHMM
    order: Order


class CancelOrderEvent(Base):
    type: Literal["cancel_order"] = "cancel_order"
    time: HHMM
    order_id: str


class NewOrderEvent(Base):
    """Заявка, поступившая в течение дня. Приоритет берётся из самой заявки."""

    type: Literal["new_order"] = "new_order"
    time: HHMM
    order: Order


class EngineerUnavailableEvent(Base):
    type: Literal["engineer_unavailable"] = "engineer_unavailable"
    time: HHMM
    engineer_id: str


Event = Annotated[
    UrgentOrderEvent | NewOrderEvent | CancelOrderEvent | EngineerUnavailableEvent,
    Field(discriminator="type"),
]


class ScenarioMeta(Base):
    source: str = "beeline"
    generator_seed: int | None = None
    geocoder: str = ""
    notes: str = ""


class Scenario(Base):
    """Входные данные одного рабочего дня одного региона."""

    id: str
    name: str
    date: str
    office: Point
    orders: list[Order] = Field(default_factory=list)
    engineers: list[Engineer] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)
    meta: ScenarioMeta = Field(default_factory=ScenarioMeta)

    def order(self, order_id: str) -> Order:
        for o in self.orders:
            if o.id == order_id:
                return o
        raise KeyError(f"нет заявки {order_id}")

    def engineer(self, engineer_id: str) -> Engineer:
        for e in self.engineers:
            if e.id == engineer_id:
                return e
        raise KeyError(f"нет инженера {engineer_id}")

    @property
    def orders_by_id(self) -> dict[str, Order]:
        return {o.id: o for o in self.orders}

    @property
    def engineers_by_id(self) -> dict[str, Engineer]:
        return {e.id: e for e in self.engineers}


class Stop(Base):
    """Одна остановка маршрута: заявка с рассчитанными временами."""

    order_id: str
    seq: int
    travel_km: float
    travel_min: int
    arrival: HHMM
    wait_min: int
    start: HHMM
    finish: HHMM
    locked: bool = False
    late_min: int = 0


class Route(Base):
    engineer_id: str
    stops: list[Stop] = Field(default_factory=list)
    distance_km: float = 0.0
    travel_min: int = 0
    work_min: int = 0
    wait_min: int = 0
    end_time: HHMM = "00:00"

    @property
    def order_ids(self) -> list[str]:
        return [s.order_id for s in self.stops]


class Unassigned(Base):
    order_id: str
    reason_code: ReasonCode
    reason: str


class Metrics(Base):
    orders_total: int = 0
    assigned: int = 0
    unassigned: int = 0
    urgent_total: int = 0
    urgent_assigned: int = 0
    engineers_total: int = 0
    engineers_used: int = 0
    distance_total_km: float = 0.0
    distance_per_order_km: float = 0.0
    distance_by_engineer: dict[str, float] = Field(default_factory=dict)
    travel_min_total: int = 0
    work_min_total: int = 0
    wait_min_total: int = 0
    utilization_by_engineer: dict[str, float] = Field(default_factory=dict)
    extra_engineers_needed: int = 0
    late_risk: int = 0
    rescheduled: int = 0
    response_measured: int = 0
    response_median_min: int = 0
    response_max_min: int = 0
    response_over_norm: int = 0


class PlanParams(Base):
    objective: Literal["auto", "min_engineers", "min_distance"] = "auto"
    time_limit_s: int = 20
    seed: int = 42
    stability_weight_m: int = 0
    lunch: bool = False
    allow_reschedule: bool = False
    travel_model: str = "haversine"


class Plan(Base):
    id: str
    scenario_id: str
    kind: Literal["optimized", "baseline"] = "optimized"
    params: PlanParams = Field(default_factory=PlanParams)
    planned_from: HHMM = "00:00"
    parent_plan_id: str | None = None
    event: Event | None = None
    routes: list[Route] = Field(default_factory=list)
    unassigned: list[Unassigned] = Field(default_factory=list)
    metrics: Metrics = Field(default_factory=Metrics)
    explanations: dict[str, Any] = Field(default_factory=dict)
    route_explanations: dict[str, str] = Field(default_factory=dict)
    plan_explanation: str = ""

    @property
    def routes_by_engineer(self) -> dict[str, Route]:
        return {r.engineer_id: r for r in self.routes}

    @property
    def assignment(self) -> dict[str, str]:
        """order_id -> engineer_id для всех назначенных заявок."""
        return {s.order_id: r.engineer_id for r in self.routes for s in r.stops}


class Violation(Base):
    """Нарушение ограничения, найденное валидатором."""

    engineer_id: str | None
    order_id: str | None
    code: str
    text: str


class Change(Base):
    order_id: str
    from_engineer: str | None
    to_engineer: str | None
    from_seq: int | None = None
    to_seq: int | None = None
    from_start: HHMM | None = None
    to_start: HHMM | None = None


class Diff(Base):
    event: Event
    before_plan_id: str
    after_plan_id: str
    changed: list[Change] = Field(default_factory=list)
    newly_assigned: list[str] = Field(default_factory=list)
    newly_unassigned: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    added: list[str] = Field(default_factory=list)
    routes_changed: list[str] = Field(default_factory=list)
    locked_stops: int = 0
    metrics_before: Metrics = Field(default_factory=Metrics)
    metrics_after: Metrics = Field(default_factory=Metrics)
    summary: str = ""
