"""Справочное сопоставление с фактическим ручным распределением (core/control.py)."""

from __future__ import annotations

import pytest

from planner.core import control, solver
from planner.core.models import PlanParams, Transport
from planner.core.validate import Geo
from planner.ingest import store

REGIONS = ("vostok", "yugo-vostok", "yugocentr")


@pytest.fixture(scope="module")
def scenarios():
    data = {s.id: s for s in store.load_all()}
    if not data:
        pytest.skip("сценарии ещё не собраны")
    return data


@pytest.mark.parametrize("region", REGIONS)
def test_control_is_available_for_every_region(scenarios, region):
    assert control.has_control(scenarios[region])


def test_scenario_without_control_is_handled():
    from tests.conftest import make_engineer, make_order, make_scenario

    scenario = make_scenario([make_order("A", 1)], [make_engineer("E01")])
    assert not control.has_control(scenario)
    reference = control.build(scenario)
    assert reference.brigades == []
    assert reference.covered_orders == 0
    assert "нет контрольного распределения" in reference.summary()


@pytest.mark.parametrize("region", REGIONS)
def test_brigades_match_the_control_file(scenarios, region):
    from planner.ingest.beeline import control_brigades

    reference = control.build(scenarios[region])
    assert reference.brigades == control_brigades(scenarios[region])
    assert reference.metrics.engineers_used == len(reference.brigades)


@pytest.mark.parametrize("region", REGIONS)
def test_every_control_order_is_placed(scenarios, region):
    scenario = scenarios[region]
    reference = control.build(scenario)
    expected = sum(1 for o in scenario.orders if o.attributes.get("control_engineer"))
    assert reference.covered_orders == expected
    assigned = {stop.order_id for route in reference.plan.routes for stop in route.stops}
    assert len(assigned) == expected


def test_brigade_profiles_are_deliberately_generous(scenarios):
    """Нарушение, найденное при щедром профиле, тем более было в реальности."""
    scenario = scenarios["vostok"]
    reference = control.build(scenario)
    engineers = control.brigade_engineers(scenario, reference.brigades)
    for engineer in engineers:
        assert len(engineer.skills) == 3
        assert engineer.transport is Transport.CAR
        assert engineer.shift_start <= "06:00" or engineer.shift_start == "06:00"
        assert engineer.shift_end >= "23:00"


def test_manual_distribution_misses_windows(scenarios):
    """Факт не укладывается в собственные нормативы — постановщик это подтверждал."""
    total_late = sum(control.build(scenarios[r]).late_starts for r in REGIONS)
    assert total_late > 0


@pytest.mark.parametrize("region", REGIONS)
def test_our_plan_never_misses_a_window(scenarios, region):
    """В отличие от факта, наш план не нарушает окон ни разу."""
    scenario = scenarios[region]
    geo = Geo(scenario)
    plan = solver.plan(scenario, geo, PlanParams(objective="min_engineers", time_limit_s=4))
    orders = scenario.orders_by_id
    for route in plan.routes:
        for stop in route.stops:
            order = orders[stop.order_id]
            assert order.window_start <= stop.start <= order.window_end


@pytest.mark.parametrize("region", ["vostok", "yugocentr"])
def test_compact_regions_beat_the_manual_plan_on_mileage(scenarios, region):
    """На московских участках маршруты короче фактических в пересчёте на заявку."""
    scenario = scenarios[region]
    geo = Geo(scenario)
    ours = solver.plan(scenario, geo, PlanParams(objective="min_engineers", time_limit_s=6))
    reference = control.build(scenario)
    assert ours.metrics.distance_per_order_km < reference.metrics.distance_per_order_km


def test_yugo_vostok_mileage_is_not_a_like_for_like_comparison(scenarios):
    """На Юго-Востоке сравнивать километраж напрямую нельзя — и это нужно знать.

    Факт закрывает все 83 заявки, но 17 визитов начинает позже обещанного
    клиенту окна. Мы берём меньше заявок и не нарушаем ни одного окна,
    поэтому наборы обслуженных заявок разные, а «км на заявку» считается
    по разным множествам. Тест фиксирует именно это положение дел, чтобы
    расхождение не выдавалось за победу и не пропало незамеченным.
    """
    scenario = scenarios["yugo-vostok"]
    geo = Geo(scenario)
    ours = solver.plan(scenario, geo, PlanParams(objective="min_engineers", time_limit_s=6))
    reference = control.build(scenario)

    assert reference.covered_orders > ours.metrics.assigned
    assert reference.late_starts >= 10
    orders = scenario.orders_by_id
    for route in ours.routes:
        for stop in route.stops:
            assert stop.start <= orders[stop.order_id].window_end


def test_comparison_rows_are_limited_to_comparable_metrics(scenarios):
    scenario = scenarios["vostok"]
    reference = control.build(scenario)
    ours = solver.plan(scenario, Geo(scenario), PlanParams(time_limit_s=3))
    rows = control.comparison_rows(ours.metrics, reference.metrics)
    assert [title for title, _, _ in rows] == [
        "Задействовано исполнителей",
        "Суммарный пробег, км",
        "Пробег на заявку, км",
    ]


def test_control_does_not_leak_into_optimization():
    """Контроль нигде не влияет на расчёт: в солвере его не должно быть упомянуто."""
    import inspect

    from planner.core import baseline, metrics, reasons

    for module in (solver, baseline, metrics, reasons):
        source = inspect.getsource(module)
        assert "control_engineer" not in source, module.__name__
        assert "control.build" not in source, module.__name__


def test_summary_is_readable(scenarios):
    text = control.build(scenarios["yugo-vostok"]).summary()
    assert "бригад" in text
    assert "км" in text
    for jargon in ("None", "Violation", "Metrics"):
        assert jargon not in text
