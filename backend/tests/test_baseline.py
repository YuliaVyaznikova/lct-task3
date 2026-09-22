"""Базовый вариант и метрики сравнения."""

from __future__ import annotations

import pytest

from planner.core import baseline, metrics
from planner.core.models import ReasonCode, Skill, Transport
from planner.core.validate import Geo, evaluate
from planner.ingest import store
from tests.conftest import make_engineer, make_order, make_scenario


def test_assigns_to_first_suitable_engineer_in_order():
    """Первый по порядку во входных данных подходящий инженер."""
    orders = [make_order("A", 1), make_order("B", 2)]
    engineers = [make_engineer("E01"), make_engineer("E02")]
    plan = baseline.plan(make_scenario(orders, engineers))
    assert plan.assignment == {"A": "E01", "B": "E01"}, "второй инженер берётся только при отказе первого"


def test_visit_order_equals_assignment_order():
    orders = [make_order("FAR", 8), make_order("NEAR", 1)]
    plan = baseline.plan(make_scenario(orders, [make_engineer("E01")]))
    assert plan.routes[0].order_ids == ["FAR", "NEAR"], "базовый вариант не переставляет заявки"


def test_skips_engineer_without_skill():
    orders = [make_order("C", 1, Skill.CONNECTION, duration=70)]
    engineers = [make_engineer("E01", [Skill.LOCAL]), make_engineer("E02", [Skill.CONNECTION])]
    assert baseline.plan(make_scenario(orders, engineers)).assignment == {"C": "E02"}


def test_skips_engineer_without_required_transport():
    orders = [make_order("F", 1, required_transport=Transport.CAR)]
    engineers = [
        make_engineer("E01", [Skill.LOCAL], Transport.FOOT),
        make_engineer("E02", [Skill.LOCAL], Transport.CAR),
    ]
    assert baseline.plan(make_scenario(orders, engineers)).assignment == {"F": "E02"}


def test_unassigned_orders_get_a_reason():
    orders = [make_order("C", 1, Skill.CONNECTION, duration=70)]
    plan = baseline.plan(make_scenario(orders, [make_engineer("E01", [Skill.LOCAL])]))
    assert plan.assignment == {}
    assert len(plan.unassigned) == 1
    assert plan.unassigned[0].reason_code is ReasonCode.NO_SKILL
    assert "навык" in plan.unassigned[0].reason


def test_plan_is_always_feasible(toy):
    plan = baseline.plan(toy)
    geo = Geo(toy)
    _, violations = evaluate(geo, {r.engineer_id: r.order_ids for r in plan.routes})
    assert not violations


def test_is_deterministic(toy):
    first = baseline.plan(toy)
    second = baseline.plan(toy)
    assert first.assignment == second.assignment
    assert first.metrics.model_dump() == second.metrics.model_dump()


def test_every_order_is_either_assigned_or_explained(toy):
    plan = baseline.plan(toy)
    covered = set(plan.assignment) | {u.order_id for u in plan.unassigned}
    assert covered == {o.id for o in toy.orders}


def test_metrics_count_only_used_engineers(toy):
    plan = baseline.plan(toy)
    used = {r.engineer_id for r in plan.routes if r.stops}
    assert plan.metrics.engineers_used == len(used)
    assert set(plan.metrics.distance_by_engineer) == used


def test_distance_total_equals_sum_by_engineer(toy):
    m = baseline.plan(toy).metrics
    assert m.distance_total_km == pytest.approx(sum(m.distance_by_engineer.values()), abs=0.05)


def test_metrics_track_urgent_orders(toy):
    m = baseline.plan(toy).metrics
    assert m.urgent_total == 1
    assert 0 <= m.urgent_assigned <= 1


def test_compare_marks_direction_correctly():
    a = metrics.Metrics(engineers_used=8, distance_total_km=70.0, assigned=58, unassigned=3)
    b = metrics.Metrics(engineers_used=11, distance_total_km=96.0, assigned=55, unassigned=6)
    rows = {row.key: row for row in metrics.compare(a, b)}
    assert rows["engineers_used"].better is True
    assert rows["distance_total_km"].better is True
    assert rows["assigned"].better is True
    assert rows["unassigned"].better is True

    worse = {row.key: row for row in metrics.compare(b, a)}
    assert worse["engineers_used"].better is False
    assert worse["assigned"].better is False


def test_compare_marks_equal_as_neutral():
    same = metrics.Metrics(engineers_used=5)
    assert all(row.better is None for row in metrics.compare(same, same))


def test_comparison_table_lists_mandatory_metrics_first():
    text = metrics.comparison_table(metrics.Metrics(), metrics.Metrics())
    lines = [line for line in text.splitlines() if line.strip()]
    assert "Задействовано инженеров" in lines[2]
    assert "Суммарный пробег" in lines[3]


def test_is_better_follows_lexicographic_objective():
    more_orders = metrics.Metrics(assigned=60, engineers_used=12, distance_total_km=200.0)
    fewer_orders = metrics.Metrics(assigned=59, engineers_used=5, distance_total_km=50.0)
    assert metrics.is_better(more_orders, fewer_orders), "заявки важнее числа инженеров"

    fewer_people = metrics.Metrics(assigned=60, engineers_used=8, distance_total_km=300.0)
    shorter = metrics.Metrics(assigned=60, engineers_used=9, distance_total_km=100.0)
    assert metrics.is_better(fewer_people, shorter), "инженеры важнее пробега"


@pytest.fixture(scope="module")
def real_scenarios():
    data = [s for s in store.load_all() if s.engineers]
    if not data:
        pytest.skip("сценарии ещё не собраны")
    return data


def test_baseline_runs_on_real_data(real_scenarios):
    for scenario in real_scenarios:
        plan = baseline.plan(scenario)
        assert plan.kind == "baseline"
        assert plan.metrics.orders_total == len(scenario.orders)
        assert plan.metrics.assigned + plan.metrics.unassigned == len(scenario.orders)


def test_baseline_leaves_room_for_improvement(real_scenarios):
    """Если бы жадность справлялась идеально, сравнивать было бы не с чем."""
    for scenario in real_scenarios:
        plan = baseline.plan(scenario)
        assert plan.metrics.unassigned > 0, scenario.id


def test_extra_engineers_estimate_is_sane(real_scenarios):
    for scenario in real_scenarios:
        plan = baseline.plan(scenario)
        assert 0 < plan.metrics.extra_engineers_needed <= plan.metrics.unassigned
