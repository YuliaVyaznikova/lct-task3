"""Оборудование как ограничение (ответ экспертов, п.4).

Исходное ТЗ §2.2 относило учёт оборудования к необязательному усложнению.
Эксперты сделали его ограничением: бригада получает оборудование в офисе
на весь день, и назначать ей можно только те заявки, на которые запаса хватает.
"""

from __future__ import annotations

import pytest

from planner.core import solver
from planner.core.models import PlanParams, ReasonCode, Skill
from planner.core.reasons import diagnose
from planner.core.validate import Geo, evaluate, evaluate_route
from planner.ingest import equipment, store
from tests.conftest import make_engineer, make_order, make_scenario

FAST = PlanParams(objective="min_engineers", time_limit_s=3)


def with_equipment(order_id: str, east_km: float, items: dict[str, int], **kwargs):
    order = make_order(order_id, east_km, **kwargs)
    order.attributes["equipment"] = items
    return order


# ------------------------------------------------------------ справочник


def test_connection_needs_a_router():
    assert equipment.needs_for("Подключение", "Конвергенция абонента") == {"router": 1}


def test_set_top_box_replacement_needs_a_box():
    assert equipment.needs_for("Локальная заявка", "TVE/ENT. Замена приставки техником") == {
        "stb": 1
    }


def test_repairs_need_nothing():
    assert equipment.needs_for("Локальная заявка", "Нет линка") == {}
    assert equipment.needs_for("Глобальная проблема", "Авария") == {}


def test_stock_is_defined_for_every_kind():
    config = equipment.load()
    assert config.stock
    for kind in config.kinds:
        assert config.stock[kind] > 0
        assert config.title(kind) != kind, f"у «{kind}» нет человеческого названия"


def test_describe_needs_is_readable():
    text = equipment.describe_needs({"router": 2, "stb": 1})
    assert "роутер" in text and "ТВ-приставка" in text
    assert equipment.describe_needs({}) == "оборудование не требуется"


# ----------------------------------------------------- ограничение маршрута


def test_route_cannot_exceed_the_morning_stock():
    """Запас выдаётся утром и не пополняется — пятая заявка с роутером не влезет."""
    stock = equipment.load().stock["router"]
    orders = [
        with_equipment(f"O{i}", i * 0.5, {"router": 1}, skill=Skill.CONNECTION, duration=30)
        for i in range(1, stock + 2)
    ]
    scenario = make_scenario(orders, [make_engineer("E01", [Skill.CONNECTION])])
    geo = Geo(scenario)

    fits, violations = evaluate_route(geo, scenario.engineers[0], [o.id for o in orders[:stock]])
    assert not violations, "ровно запас должен помещаться"
    assert len(fits.stops) == stock

    _, violations = evaluate_route(geo, scenario.engineers[0], [o.id for o in orders])
    codes = [v.code for v in violations]
    assert "NO_EQUIPMENT" in codes
    assert any("не хватает оборудования" in v.text for v in violations)


def test_solver_respects_the_stock():
    stock = equipment.load().stock["router"]
    orders = [
        with_equipment(f"O{i}", i * 0.4, {"router": 1}, skill=Skill.CONNECTION, duration=20)
        for i in range(1, stock + 3)
    ]
    engineers = [make_engineer(f"E{i:02d}", [Skill.CONNECTION]) for i in (1, 2)]
    scenario = make_scenario(orders, engineers)
    geo = Geo(scenario)

    plan = solver.plan(scenario, geo, FAST)
    _, violations = evaluate(geo, {r.engineer_id: r.order_ids for r in plan.routes})
    assert not violations

    for route in plan.routes:
        used = sum(geo.equipment_needs(s.order_id).get("router", 0) for s in route.stops)
        assert used <= stock, f"{route.engineer_id} везёт {used} роутеров при запасе {stock}"


def test_stock_is_shared_across_the_whole_day_not_per_visit():
    """Две заявки подряд расходуют два роутера, а не по одному каждая заново."""
    orders = [
        with_equipment("A", 1, {"router": 1}, skill=Skill.CONNECTION, duration=20),
        with_equipment("B", 2, {"router": 1}, skill=Skill.CONNECTION, duration=20),
    ]
    scenario = make_scenario(orders, [make_engineer("E01", [Skill.CONNECTION])])
    geo = Geo(scenario)
    route, violations = evaluate_route(geo, scenario.engineers[0], ["A", "B"])
    assert not violations
    total = sum(geo.equipment_needs(s.order_id)["router"] for s in route.stops)
    assert total == 2


def test_order_beyond_any_stock_is_explained():
    """Если заявке нужно больше, чем бригада вообще берёт, это отдельная причина."""
    huge = with_equipment("HUGE", 1, {"router": 99}, skill=Skill.CONNECTION, duration=20)
    scenario = make_scenario([huge], [make_engineer("E01", [Skill.CONNECTION])])
    geo = Geo(scenario)
    result = diagnose(geo, huge)
    assert result.reason_code is ReasonCode.NO_EQUIPMENT
    assert "роутер" in result.reason
    assert "запас" in result.reason


# ------------------------------------------------- на реальных данных


@pytest.fixture(scope="module")
def demo():
    scenarios = [s for s in store.load_all() if s.id == "demo"]
    if not scenarios:
        pytest.skip("демо-сценарий не собран")
    return scenarios[0]


def test_real_orders_carry_their_needs(demo):
    marked = [o for o in demo.orders if o.attributes.get("equipment")]
    assert marked, "подключениям нужен роутер — потребность должна быть проставлена"
    for order in marked:
        assert all(count > 0 for count in order.attributes["equipment"].values())


def test_real_plan_never_exceeds_the_stock(demo):
    geo = Geo(demo)
    plan = solver.plan(demo, geo, FAST)
    for route in plan.routes:
        used: dict[str, int] = {}
        for stop in route.stops:
            for kind, count in geo.equipment_needs(stop.order_id).items():
                used[kind] = used.get(kind, 0) + count
        stock = geo.equipment_stock(route.engineer_id)
        for kind, count in used.items():
            assert count <= stock.get(kind, 0), f"{route.engineer_id}: {kind} {count} > {stock}"


def test_constraint_actually_binds(demo):
    """Ограничение должно работать, а не украшать: хоть у кого-то запас исчерпан."""
    geo = Geo(demo)
    plan = solver.plan(demo, geo, PlanParams(objective="min_engineers", time_limit_s=8))
    stock = equipment.load().stock
    at_limit = 0
    for route in plan.routes:
        used: dict[str, int] = {}
        for stop in route.stops:
            for kind, count in geo.equipment_needs(stop.order_id).items():
                used[kind] = used.get(kind, 0) + count
        if any(used.get(kind, 0) >= stock[kind] for kind in stock):
            at_limit += 1
    assert at_limit > 0, "если запас никому не мешает, ограничение ничего не значит"


def test_equipment_check_appears_in_the_card(demo):
    from planner.core import explain

    geo = Geo(demo)
    plan = solver.plan(demo, geo, FAST)
    explain.attach(geo, plan)
    for card in plan.explanations.values():
        texts = [check["text"] for check in card["checks"]]
        assert any(text.startswith("Оборудование") for text in texts)
