"""Синтетический справочник инженеров."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from planner.core.models import Engineer, Order, Point, Scenario, Skill, Transport
from planner.core.timeutil import hhmm_to_min
from planner.paths import CONFIG_DIR

MAX_ATTEMPTS = 100


@dataclass
class Shift:
    start: str
    end: str
    share: float


@dataclass
class RemoteBase:
    """Выездная база: инженеры, начинающие день в удалённом кластере заявок."""

    districts: list[str]
    engineers: int


@dataclass
class EngineerConfig:
    count: int
    skills_mix: dict[str, float]
    skill_demand_floor: float
    transport_mix: dict[str, float]
    shifts: list[Shift]
    required_transport_share: float
    min_cars: int
    remote_bases: list[RemoteBase] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


class InvariantError(RuntimeError):
    pass


def load_config(region_id: str, path: Path | None = None) -> EngineerConfig:
    path = path or CONFIG_DIR / "engineers.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    merged: dict[str, Any] = dict(raw.get("defaults") or {})
    merged.update((raw.get("regions") or {}).get(region_id) or {})
    if "count" not in merged:
        raise ValueError(f"в {path} не задан count для региона {region_id!r}")
    return EngineerConfig(
        count=int(merged["count"]),
        skills_mix=dict(merged["skills_mix"]),
        skill_demand_floor=float(merged["skill_demand_floor"]),
        transport_mix=dict(merged["transport_mix"]),
        shifts=[Shift(**s) for s in merged["shifts"]],
        required_transport_share=float(merged["required_transport_share"]),
        min_cars=int(merged["min_cars"]),
        remote_bases=[RemoteBase(**base) for base in merged.get("remote_bases", [])],
    )


def skill_demand(orders: list[Order], floor: float) -> dict[Skill, float]:
    """Доля навыка в спросе по рабочим минутам, а не по числу заявок."""
    minutes: dict[Skill, float] = {s: 0.0 for s in Skill}
    for order in orders:
        minutes[order.skill] += order.duration_min
    total = sum(minutes.values()) or 1.0
    shares = {skill: max(value / total, floor) for skill, value in minutes.items()}
    norm = sum(shares.values())
    return {skill: value / norm for skill, value in shares.items()}


def _weighted_choice(rng: random.Random, weights: dict[Any, float]) -> Any:
    keys = sorted(weights, key=str)
    return rng.choices(keys, weights=[weights[k] for k in keys], k=1)[0]


def _pick_skills(rng: random.Random, demand: dict[Skill, float], how_many: int) -> list[Skill]:
    remaining = dict(demand)
    chosen: list[Skill] = []
    for _ in range(how_many):
        if not remaining:
            break
        skill = _weighted_choice(rng, remaining)
        chosen.append(skill)
        remaining.pop(skill)
    return sorted(chosen, key=lambda s: list(Skill).index(s))


def _quota(weights: dict[Any, float], total: int) -> list[Any]:
    """Раздаёт `total` мест по долям методом наибольших остатков."""
    keys = sorted(weights, key=str)
    norm = sum(weights[k] for k in keys) or 1.0
    exact = {k: weights[k] / norm * total for k in keys}
    result: list[Any] = []
    counts = {k: int(exact[k]) for k in keys}
    for key in keys:
        result.extend([key] * counts[key])
    remainder = sorted(keys, key=lambda k: (-(exact[k] - counts[k]), str(k)))
    index = 0
    while len(result) < total:
        result.append(remainder[index % len(remainder)])
        index += 1
    return result[:total]


def _shift_plan(config: EngineerConfig) -> list[Shift]:
    """Смены раздаются по долям детерминированно, без обращения к rng."""
    plan: list[Shift] = []
    for shift in config.shifts:
        plan.extend([shift] * round(shift.share * config.count))
    while len(plan) < config.count:
        plan.append(config.shifts[0])
    return plan[: config.count]


def check_invariants(engineers: list[Engineer], config: EngineerConfig) -> None:
    """Справочник должен позволять проверить все три группы ограничений."""
    for skill in Skill:
        owners = [e for e in engineers if skill in e.skills]
        if len(owners) < 2:
            raise InvariantError(f"навык {skill.value}: только {len(owners)} инженеров, нужно ≥2")

    shifts = {(e.shift_start, e.shift_end) for e in engineers}
    if len(shifts) < 2:
        raise InvariantError("обе смены должны быть представлены")
    for shift in shifts:
        covered = {
            skill
            for e in engineers
            if (e.shift_start, e.shift_end) == shift
            for skill in e.skills
        }
        if Skill.EMERGENCY not in covered:
            raise InvariantError(f"в смене {shift[0]}–{shift[1]} некому выполнять аварии")

    transports = {e.transport for e in engineers}
    if len(transports) < len(Transport):
        missing = sorted(t.value for t in Transport if t not in transports)
        raise InvariantError(f"не представлен транспорт: {', '.join(missing)}")

    cars = sum(1 for e in engineers if e.transport is Transport.CAR)
    if cars < config.min_cars:
        raise InvariantError(f"автомобилистов {cars}, нужно ≥{config.min_cars}")

    for shift in shifts:
        has_car_connection = any(
            e.transport is Transport.CAR
            and Skill.CONNECTION in e.skills
            and (e.shift_start, e.shift_end) == shift
            for e in engineers
        )
        if not has_car_connection:
            raise InvariantError(
                f"в смене {shift[0]}–{shift[1]} нет автомобилиста с навыком подключения"
            )

    if not any(len(e.skills) == 1 for e in engineers):
        raise InvariantError("нужен хотя бы один узкий специалист с одним навыком")


def _district_centroid(orders: list[Order], districts: list[str]) -> Point | None:
    """Центр тяжести заявок кластера там и базируется выездная бригада."""
    wanted = {name.strip().casefold() for name in districts}
    points = [
        o for o in orders if o.has_coords and (o.district or "").strip().casefold() in wanted
    ]
    if not points:
        return None
    return Point(
        address=f"выездная база: {', '.join(districts)}",
        lat=sum(o.lat for o in points) / len(points),
        lon=sum(o.lon for o in points) / len(points),
    )


def _assign_remote_bases(
    engineers: list[Engineer], config: EngineerConfig, orders: list[Order]
) -> int:
    """Переносит часть автомобилистов на выездные базы (см."""
    if not config.remote_bases:
        return 0

    candidates = [e for e in engineers if e.transport is Transport.CAR]
    moved = 0
    for base in config.remote_bases:
        point = _district_centroid(orders, base.districts)
        if point is None:
            continue
        for _ in range(base.engineers):
            if not candidates:
                break
            engineer = candidates.pop(0)
            engineer.start = point.model_copy()
            engineer.name = f"{engineer.name} ({base.districts[0]})"
            moved += 1
    return moved


def _generate_once(
    seed: int, config: EngineerConfig, orders: list[Order], start: Point
) -> list[Engineer]:
    rng = random.Random(seed)
    demand = skill_demand(orders, config.skill_demand_floor)
    sizes = {"one": 1, "two": 2, "three": 3}
    shifts = _shift_plan(config)

    transports = _quota(config.transport_mix, config.count)
    skill_counts = [sizes[k] for k in _quota(config.skills_mix, config.count)]
    rng.shuffle(transports)
    rng.shuffle(skill_counts)

    engineers: list[Engineer] = []
    for index in range(config.count):
        shift = shifts[index]
        engineers.append(
            Engineer(
                id=f"E{index + 1:02d}",
                name=f"Инженер {index + 1:02d}",
                skills=_pick_skills(rng, demand, skill_counts[index]),
                transport=Transport(transports[index]),
                shift_start=shift.start,
                shift_end=shift.end,
                start=Point(address=start.address, lat=start.lat, lon=start.lon),
            )
        )
    _assign_remote_bases(engineers, config, orders)
    return engineers


def generate(
    config: EngineerConfig, seed: int, orders: list[Order], start: Point
) -> tuple[list[Engineer], int]:
    """Возвращает справочник и seed, на котором инварианты сошлись."""
    last: InvariantError | None = None
    for attempt in range(MAX_ATTEMPTS):
        engineers = _generate_once(seed + attempt, config, orders, start)
        try:
            check_invariants(engineers, config)
        except InvariantError as exc:
            last = exc
            continue
        return engineers, seed + attempt
    raise InvariantError(
        f"за {MAX_ATTEMPTS} попыток не удалось собрать справочник: {last}"
    )


def assign_required_transport(orders: list[Order], seed: int, share: float) -> int:
    """Проставляет часть заявок «подключение» требование ехать на автомобиле."""
    candidates = [o for o in orders if o.skill is Skill.CONNECTION]
    how_many = int(round(len(candidates) * share))
    if how_many <= 0:
        return 0
    rng = random.Random(seed)
    for order in rng.sample(candidates, how_many):
        order.required_transport = Transport.CAR
        order.attributes["required_transport_synthetic"] = True
    return how_many


def populate(
    scenario: Scenario,
    seed: int = 42,
    config_path: Path | None = None,
    region_id: str | None = None,
) -> Scenario:
    """Дополняет сценарий инженерами и требованиями к транспорту (на месте)."""
    config = load_config(region_id or scenario.id, config_path)
    engineers, used_seed = generate(config, seed, scenario.orders, scenario.office)
    scenario.engineers = engineers
    for order in scenario.orders:
        order.required_transport = None
        order.attributes.pop("required_transport_synthetic", None)
    assign_required_transport(scenario.orders, used_seed, config.required_transport_share)
    scenario.meta.generator_seed = used_seed
    return scenario


MIN_ENGINEERS = 6


def min_count(config: EngineerConfig) -> int:
    """Наименьший состав региона, при котором квоты транспорта сходятся."""
    for count in range(MIN_ENGINEERS, 100):
        quota = _quota(config.transport_mix, count)
        if quota.count(Transport.CAR.value) >= config.min_cars and all(
            transport.value in quota for transport in Transport
        ):
            return count
    raise InvariantError("квоты транспорта не сходятся ни при каком составе")


def resize(
    scenario: Scenario,
    count: int,
    seed: int | None = None,
    config_path: Path | None = None,
    region_id: str | None = None,
) -> Scenario:
    """Пересобирает состав бригад под заданное число (ответ экспертов, п.12)."""
    base = region_id or scenario.id
    config = load_config(base, config_path)
    minimum = min_count(config)
    if count < minimum:
        reason = (
            f"нужно не меньше {config.min_cars} автомобилистов, часть из них "
            "начинает день на выездных базах"
            if minimum > MIN_ENGINEERS
            else "при меньшем составе невозможно представить все типы транспорта "
            "и закрыть обе смены"
        )
        raise InvariantError(f"бригад должно быть не меньше {minimum}: {reason}")

    config.count = count
    engineers, used_seed = generate(
        config, seed if seed is not None else (scenario.meta.generator_seed or 42),
        scenario.orders, scenario.office,
    )
    scenario.engineers = engineers
    scenario.meta.generator_seed = used_seed
    return scenario


def summary(engineers: list[Engineer]) -> str:
    import collections

    by_transport = collections.Counter(e.transport.value for e in engineers)
    by_size = collections.Counter(len(e.skills) for e in engineers)
    by_skill = collections.Counter(s.value for e in engineers for s in e.skills)
    by_shift = collections.Counter(f"{e.shift_start}–{e.shift_end}" for e in engineers)
    return (
        f"транспорт {dict(by_transport)}; навыков у инженера {dict(sorted(by_size.items()))}; "
        f"владельцев навыка {dict(by_skill)}; смены {dict(by_shift)}"
    )


def latest_finish(scenario: Scenario) -> int:
    """Самое позднее допустимое окончание работ для проверки длины смен."""
    return max(o.window_end_min + o.duration_min for o in scenario.orders)


def shift_covers_all_windows(scenario: Scenario) -> bool:
    latest = max(hhmm_to_min(e.shift_end) for e in scenario.engineers)
    return latest >= max(o.window_end_min for o in scenario.orders)
