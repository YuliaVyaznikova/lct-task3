"""Генератор справочника инженеров (DESIGN.md §4.3)."""

from __future__ import annotations

import collections

import pytest

from planner.core.models import Point, Skill, Transport
from planner.ingest import engineers as gen
from planner.ingest import store

REGIONS = ("vostok", "yugo-vostok", "yugocentr")
EXPECTED_COUNT = {"vostok": 12, "yugo-vostok": 12, "yugocentr": 11}


@pytest.fixture(scope="module")
def scenarios():
    data = {s.id: s for s in store.load_all()}
    if not data:
        pytest.skip("сценарии ещё не собраны")
    return data


def test_quota_matches_weights_exactly():
    quota = gen._quota({"car": 0.30, "foot": 0.25, "public": 0.35, "bike": 0.10}, 12)
    counts = collections.Counter(quota)
    assert len(quota) == 12
    assert counts["car"] == 4 and counts["public"] == 4
    assert counts["foot"] == 3 and counts["bike"] == 1


def test_quota_never_loses_or_adds_places():
    for total in range(1, 30):
        assert len(gen._quota({"a": 0.5, "b": 0.3, "c": 0.2}, total)) == total


def test_skill_demand_follows_work_minutes(scenarios):
    """Спрос считается по минутам работы, а не по числу заявок."""
    orders = scenarios["vostok"].orders
    demand = gen.skill_demand(orders, floor=0.0)
    assert demand[Skill.CONNECTION] > demand[Skill.LOCAL] > demand[Skill.EMERGENCY]
    assert abs(sum(demand.values()) - 1.0) < 1e-9


def test_skill_demand_floor_protects_rare_skills(scenarios):
    """У Югоцентра всего одна аварийная заявка — без floor навык остался бы без людей."""
    orders = scenarios["yugocentr"].orders
    assert gen.skill_demand(orders, floor=0.12)[Skill.EMERGENCY] >= 0.10


@pytest.mark.parametrize("region", REGIONS)
def test_generated_directory_is_valid(scenarios, region):
    scenario = scenarios[region]
    config = gen.load_config(region)
    engineers, seed = gen.generate(config, 42, scenario.orders, scenario.office)
    assert len(engineers) == EXPECTED_COUNT[region]
    gen.check_invariants(engineers, config)  # не должно бросить
    assert 42 <= seed <= 47, "инварианты должны сходиться за единицы попыток, а не перебором"


@pytest.mark.parametrize("region", REGIONS)
def test_generation_is_deterministic(scenarios, region):
    scenario = scenarios[region]
    config = gen.load_config(region)
    first, _ = gen.generate(config, 42, scenario.orders, scenario.office)
    second, _ = gen.generate(config, 42, scenario.orders, scenario.office)
    assert [e.model_dump() for e in first] == [e.model_dump() for e in second]

    other, _ = gen.generate(config, 7, scenario.orders, scenario.office)
    assert [e.model_dump() for e in first] != [e.model_dump() for e in other]


@pytest.mark.parametrize("region", REGIONS)
def test_transport_matches_configured_mix(scenarios, region):
    config = gen.load_config(region)
    engineers, _ = gen.generate(config, 42, scenarios[region].orders, scenarios[region].office)
    counts = collections.Counter(e.transport.value for e in engineers)
    expected = collections.Counter(gen._quota(config.transport_mix, config.count))
    assert counts == expected


def test_invariants_reject_broken_directory(scenarios):
    """Проверка должна ловить справочник, на котором ограничения непроверяемы."""
    scenario = scenarios["vostok"]
    config = gen.load_config("vostok")
    engineers, _ = gen.generate(config, 42, scenario.orders, scenario.office)

    everyone_universal = [e.model_copy(update={"skills": list(Skill)}) for e in engineers]
    with pytest.raises(gen.InvariantError, match="узкий специалист"):
        gen.check_invariants(everyone_universal, config)

    all_on_foot = [e.model_copy(update={"transport": Transport.FOOT}) for e in engineers]
    with pytest.raises(gen.InvariantError, match="транспорт"):
        gen.check_invariants(all_on_foot, config)

    one_shift = [e.model_copy(update={"shift_start": "09:00", "shift_end": "18:00"}) for e in engineers]
    with pytest.raises(gen.InvariantError, match="смены"):
        gen.check_invariants(one_shift, config)


def test_yugo_vostok_has_more_cars(scenarios):
    """До Каширы и Домодедова пешком не добраться — автомобилистов должно быть больше."""
    counts = {}
    for region in ("vostok", "yugo-vostok"):
        config = gen.load_config(region)
        engineers, _ = gen.generate(config, 42, scenarios[region].orders, scenarios[region].office)
        counts[region] = sum(1 for e in engineers if e.transport is Transport.CAR)
    assert counts["yugo-vostok"] >= 5
    assert counts["yugo-vostok"] > counts["vostok"]


@pytest.mark.parametrize("region", REGIONS)
def test_engineers_start_at_office_unless_they_have_a_remote_base(scenarios, region):
    """По умолчанию старт — офис участка; исключение задаётся в конфигурации."""
    scenario = scenarios[region]
    config = gen.load_config(region)
    engineers, _ = gen.generate(config, 42, scenario.orders, scenario.office)

    remote = [e for e in engineers if e.start.coords != scenario.office.coords]
    expected_remote = sum(base.engineers for base in config.remote_bases)
    assert len(remote) == expected_remote
    assert all(e.start.has_coords for e in engineers)


def test_remote_bases_sit_inside_their_clusters(scenarios):
    """Выездная база должна стоять среди заявок своего кластера, а не у офиса.

    В контрольном распределении Домодедово обслуживает закреплённая бригада,
    Каширу и Ступино — две. Без этого все инженеры выезжали бы из Бирюлёва
    и наматывали по 90 км в один конец.
    """
    from planner.core.travel import haversine_km

    scenario = scenarios["yugo-vostok"]
    config = gen.load_config("yugo-vostok")
    assert config.remote_bases, "у Юго-Востока должны быть выездные базы"

    engineers, _ = gen.generate(config, 42, scenario.orders, scenario.office)
    remote = [e for e in engineers if e.start.coords != scenario.office.coords]
    assert remote

    for engineer in remote:
        # Каждая база должна быть ближе к «своим» заявкам, чем офис участка.
        district = engineer.name.split("(")[-1].rstrip(")")
        cluster = [
            o for o in scenario.orders if o.district.casefold().startswith(district.casefold())
        ]
        assert cluster, district
        nearest = min(haversine_km(*engineer.start.coords, *o.coords) for o in cluster)
        from_office = min(
            haversine_km(*scenario.office.coords, *o.coords) for o in cluster
        )
        assert nearest < from_office


def test_remote_bases_go_to_drivers(scenarios):
    """На выездную базу отправляем автомобилиста: иначе он оттуда не уедет."""
    from planner.core.models import Transport

    scenario = scenarios["yugo-vostok"]
    config = gen.load_config("yugo-vostok")
    engineers, _ = gen.generate(config, 42, scenario.orders, scenario.office)
    for engineer in engineers:
        if engineer.start.coords != scenario.office.coords:
            assert engineer.transport is Transport.CAR


def test_regions_without_remote_bases_all_start_at_office(scenarios):
    for region in ("vostok", "yugocentr"):
        scenario = scenarios[region]
        config = gen.load_config(region)
        assert not config.remote_bases
        engineers, _ = gen.generate(config, 42, scenario.orders, scenario.office)
        assert all(e.start.coords == scenario.office.coords for e in engineers)


@pytest.mark.parametrize("region", REGIONS)
def test_shifts_cover_latest_window(scenarios, region):
    """Слот 20:00–22:00 требует смены, которая позволяет закончить работу внутри неё."""
    scenario = scenarios[region]
    config = gen.load_config(region)
    engineers, _ = gen.generate(config, 42, scenario.orders, scenario.office)
    latest_shift_end = max(e.shift_end_min for e in engineers)
    latest_window_end = max(o.window_end_min for o in scenario.orders if o.window_end != "23:59")
    assert latest_shift_end >= latest_window_end


def test_required_transport_assigned_only_to_connection(scenarios):
    scenario = scenarios["vostok"].model_copy(deep=True)
    gen.populate(scenario, seed=42)
    marked = [o for o in scenario.orders if o.required_transport is not None]
    assert marked, "без требуемого транспорта ограничение «Ресурс» непроверяемо"
    assert all(o.skill is Skill.CONNECTION for o in marked)
    assert all(o.required_transport is Transport.CAR for o in marked)
    assert all(o.attributes.get("required_transport_synthetic") for o in marked)


def test_populate_is_idempotent(scenarios):
    """Повторный запуск не должен накапливать требования к транспорту."""
    scenario = scenarios["vostok"].model_copy(deep=True)
    gen.populate(scenario, seed=42)
    first = {o.id: o.required_transport for o in scenario.orders}
    gen.populate(scenario, seed=42)
    assert {o.id: o.required_transport for o in scenario.orders} == first


def test_saved_scenarios_have_engineers(scenarios):
    for region in REGIONS:
        scenario = scenarios[region]
        assert len(scenario.engineers) == EXPECTED_COUNT[region], region
        assert scenario.meta.generator_seed is not None


def test_config_falls_back_to_defaults():
    config = gen.load_config("vostok")
    assert config.count == 12
    assert config.min_cars == 2  # из defaults
    assert gen.load_config("yugo-vostok").min_cars == 5  # переопределено регионом


def test_unknown_region_is_rejected():
    with pytest.raises(ValueError, match="count"):
        gen.load_config("нет-такого-региона")
