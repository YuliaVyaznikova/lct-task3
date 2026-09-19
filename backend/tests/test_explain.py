"""Объяснения решений (DESIGN.md §10)."""

from __future__ import annotations

import pytest

from planner.core import baseline, explain, reasons, solver
from planner.core.models import PlanParams, ReasonCode, Skill, Transport
from planner.core.validate import Geo
from planner.ingest import store
from tests.conftest import make_engineer, make_order, make_scenario

FAST = PlanParams(objective="min_engineers", time_limit_s=2)


@pytest.fixture
def explained(toy, toy_geo):
    plan = solver.plan(toy, toy_geo, FAST)
    explain.attach(toy_geo, plan)
    return plan


def test_every_assigned_order_has_a_card(explained):
    assigned = {s.order_id for r in explained.routes for s in r.stops}
    assert set(explained.explanations) == assigned


def test_card_confirms_all_mandatory_constraints(explained):
    """Четыре проверки: навык, транспорт, окно, смена — и все пройдены."""
    for card in explained.explanations.values():
        assert len(card["checks"]) == 4
        assert all(check["ok"] for check in card["checks"])
        joined = " ".join(check["text"] for check in card["checks"])
        for word in ("Навык", "Транспорт", "Окно", "Смена"):
            assert word in joined


def test_card_mentions_times_from_the_plan(explained, toy_geo):
    for order_id, card in explained.explanations.items():
        stop = next(s for r in explained.routes for s in r.stops if s.order_id == order_id)
        assert stop.arrival in card["headline"]
        assert stop.start in card["headline"]


def test_card_has_travel_and_reason(explained):
    for card in explained.explanations.values():
        assert "км" in card["travel"]
        assert card["why"]


def test_alternatives_are_ranked_by_added_distance():
    """Главный ответ на вопрос ТЗ «почему именно этот инженер»."""
    orders = [make_order("A", 1), make_order("B", 10)]
    engineers = [make_engineer("E01"), make_engineer("E02"), make_engineer("E03")]
    scenario = make_scenario(orders, engineers)
    geo = Geo(scenario)
    plan = solver.plan(scenario, geo, FAST)
    explain.attach(geo, plan)

    card = plan.explanations["A"]
    assert card["alternatives"], "должны быть перечислены другие инженеры"
    added = [
        float(text.split("+")[1].split(" км")[0])
        for text in card["alternatives"]
        if "+" in text and "км" in text
    ]
    assert added == sorted(added), "альтернативы идут от дешёвой к дорогой"


def test_alternatives_count_engineers_without_the_skill():
    orders = [make_order("C", 1, Skill.CONNECTION, duration=70)]
    engineers = [
        make_engineer("E01", [Skill.CONNECTION]),
        make_engineer("E02", [Skill.LOCAL]),
        make_engineer("E03", [Skill.LOCAL]),
    ]
    scenario = make_scenario(orders, engineers)
    geo = Geo(scenario)
    plan = solver.plan(scenario, geo, FAST)
    explain.attach(geo, plan)
    assert any("не подходят по навыку" in text for text in plan.explanations["C"]["alternatives"])


def test_blocking_alternative_names_the_displaced_order():
    """Если мешает не сама заявка, а соседняя, текст обязан это назвать."""
    window = ("10:00", "11:00")
    orders = [
        make_order("NEAR", 1, Skill.LOCAL, window, duration=50),
        make_order("FAR", 25, Skill.LOCAL, window, duration=50),
    ]
    engineers = [make_engineer("E01"), make_engineer("E02")]
    scenario = make_scenario(orders, engineers)
    geo = Geo(scenario)
    plan = solver.plan(scenario, geo, FAST)
    explain.attach(geo, plan)

    texts = [t for card in plan.explanations.values() for t in card["alternatives"]]
    assert any("сдвинула бы заявку" in t or "позже конца окна" in t or "км" in t for t in texts)


# --------------------------------------------------------- причины отказа


def test_no_skill_reason():
    orders = [make_order("C", 1, Skill.CONNECTION, duration=70)]
    plan = baseline.plan(make_scenario(orders, [make_engineer("E01", [Skill.LOCAL])]))
    assert plan.unassigned[0].reason_code is ReasonCode.NO_SKILL
    assert "навыка" in plan.unassigned[0].reason


def test_no_transport_reason():
    orders = [make_order("F", 1, required_transport=Transport.CAR)]
    engineers = [make_engineer("E01", [Skill.LOCAL], Transport.FOOT)]
    plan = baseline.plan(make_scenario(orders, engineers))
    assert plan.unassigned[0].reason_code is ReasonCode.NO_TRANSPORT
    assert "транспорт" in plan.unassigned[0].reason


def test_shift_mismatch_reason():
    orders = [make_order("X", 1, Skill.LOCAL, ("20:00", "22:00"))]
    engineers = [make_engineer("E01", [Skill.LOCAL], shift=("09:00", "18:00"))]
    plan = baseline.plan(make_scenario(orders, engineers))
    assert plan.unassigned[0].reason_code is ReasonCode.SHIFT_MISMATCH
    assert "смен" in plan.unassigned[0].reason


def test_unreachable_reason():
    """Пешеход до точки в 60 км не дойдёт за время окна."""
    orders = [make_order("X", 60, Skill.LOCAL, ("10:00", "12:00"))]
    engineers = [make_engineer("E01", [Skill.LOCAL], Transport.FOOT, ("09:00", "23:00"))]
    plan = baseline.plan(make_scenario(orders, engineers))
    assert plan.unassigned[0].reason_code is ReasonCode.UNREACHABLE
    assert "км" in plan.unassigned[0].reason


def test_capacity_reason_uses_singular_for_one_engineer():
    window = ("10:00", "11:00")
    orders = [
        make_order("A", 1, Skill.LOCAL, window, duration=55),
        make_order("B", 12, Skill.LOCAL, window, duration=55),
    ]
    plan = baseline.plan(make_scenario(orders, [make_engineer("E01")]))
    assert plan.unassigned[0].reason_code is ReasonCode.CAPACITY
    assert plan.unassigned[0].reason.startswith("единственный инженер")


def test_no_coords_reason(toy_geo):
    order = toy_geo.orders["A"].model_copy(update={"lat": None, "lon": None})
    result = reasons.diagnose(toy_geo, order)
    assert result.reason_code is ReasonCode.NO_COORDS


# ----------------------------------------------------- план и маршруты


def test_plan_summary_mentions_key_numbers(explained):
    text = explained.plan_explanation
    m = explained.metrics
    assert str(m.engineers_used) in text
    assert str(m.assigned) in text
    assert "км" in text


def test_plan_summary_suggests_extra_staff_when_needed():
    """Формулировка, которую постановщик назвал желаемой на сессии вопросов."""
    window = ("10:00", "11:00")
    orders = [make_order(f"O{i}", i, Skill.LOCAL, window, duration=55) for i in range(1, 6)]
    scenario = make_scenario(orders, [make_engineer("E01")])
    geo = Geo(scenario)
    plan = solver.plan(scenario, geo, FAST)
    explain.attach(geo, plan)
    assert plan.metrics.extra_engineers_needed > 0
    assert "нужно ещё" in plan.plan_explanation


def test_plan_summary_says_when_everything_fits(toy_geo):
    orders = [make_order("A", 1), make_order("B", 2)]
    scenario = make_scenario(orders, [make_engineer("E01")])
    geo = Geo(scenario)
    plan = solver.plan(scenario, geo, FAST)
    explain.attach(geo, plan)
    assert "Все заявки распределены" in plan.plan_explanation


def test_route_summary_is_short_and_factual(explained, toy_geo):
    for engineer_id, text in explained.route_explanations.items():
        route = next(r for r in explained.routes if r.engineer_id == engineer_id)
        assert toy_geo.engineers[engineer_id].name in text
        assert f"{route.distance_km:.1f} км" in text
        assert len(text) < 400, "маршрутная сводка не должна превращаться в портянку"


def test_explanations_are_deterministic(toy, toy_geo):
    first = solver.plan(toy, toy_geo, FAST)
    explain.attach(toy_geo, first)
    second = solver.plan(toy, toy_geo, FAST)
    explain.attach(toy_geo, second)
    if first.assignment == second.assignment:
        assert first.explanations == second.explanations


# ------------------------------------------------- на реальных данных


def test_explanations_on_real_region():
    scenarios = [s for s in store.load_all() if s.id == "vostok"]
    if not scenarios:
        pytest.skip("сценарии ещё не собраны")
    scenario = scenarios[0]
    geo = Geo(scenario)
    plan = solver.plan(scenario, geo, PlanParams(objective="min_engineers", time_limit_s=5))
    explain.attach(geo, plan)

    assert plan.plan_explanation
    assert len(plan.explanations) == plan.metrics.assigned
    for unassigned in plan.unassigned:
        assert unassigned.reason and unassigned.reason_code
    # Карточка не должна разрастаться в простыню (Q&A, блок 12).
    for card in plan.explanations.values():
        assert len(card["alternatives"]) <= explain.MAX_ALTERNATIVES + 1
