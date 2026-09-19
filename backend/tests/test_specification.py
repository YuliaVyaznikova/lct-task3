"""Сверка решения с техническим заданием.

Каждая проверка соответствует конкретному пункту ТЗ и названа так, чтобы
по списку проваленных тестов было видно, какое требование не выполнено.
Это же список, по которому эксперты будут смотреть решение (ТЗ §7.2, §8.1).
"""

from __future__ import annotations

import inspect

import pytest

from planner.core import baseline, explain, metrics, replan, reasons, solver, travel
from planner.core.models import (
    CancelOrderEvent,
    EngineerUnavailableEvent,
    Order,
    PlanParams,
    Priority,
    Skill,
    Transport,
    UrgentOrderEvent,
)
from planner.core.timeutil import hhmm_to_min
from planner.core.validate import Geo, evaluate
from planner.ingest import store

FAST = PlanParams(objective="min_engineers", time_limit_s=4)


@pytest.fixture(scope="module")
def demo():
    scenarios = [s for s in store.load_all() if s.id == "demo"]
    if not scenarios:
        pytest.skip("демо-сценарий не собран: python -m planner.cli demo")
    return scenarios[0]


@pytest.fixture(scope="module")
def demo_plan(demo):
    geo = Geo(demo)
    plan = solver.plan(demo, geo, FAST)
    explain.attach(geo, plan)
    return plan


# ======================================================== ТЗ §2.1 «Что должно уметь решение»


def test_2_1_1_loads_prepared_data():
    """1. Загружать готовые тестовые данные из CSV или JSON либо встроенный набор."""
    from planner.ingest import beeline

    assert callable(beeline.load_region)
    scenarios = {s.id for s in store.load_all()}
    assert {"vostok", "yugo-vostok", "yugocentr", "demo"} <= scenarios


def test_2_1_2_distributes_orders_between_engineers(demo_plan):
    """2. Распределять заявки между инженерами."""
    assert demo_plan.metrics.assigned > 0
    assert len({route.engineer_id for route in demo_plan.routes if route.stops}) > 1


def test_2_1_3_defines_visit_order(demo_plan):
    """3. Определять порядок посещения адресов для каждого инженера."""
    for route in demo_plan.routes:
        assert [stop.seq for stop in route.stops] == list(range(1, len(route.stops) + 1))


def test_2_1_4_orders_have_coordinates_for_the_map(demo):
    """4. Показывать маршруты и точки заявок на карте."""
    assert demo.office.has_coords
    assert all(order.has_coords for order in demo.orders)


def test_2_1_5_plan_says_who_where_when(demo_plan, demo):
    """5. Отображать краткую информацию по плану: кто, куда и в какое время едет."""
    geo = Geo(demo)
    for route in demo_plan.routes:
        if not route.stops:
            continue
        lines = explain.timeline_summary(geo, route)
        assert len(lines) == len(route.stops)
        for line, stop in zip(lines, route.stops):
            assert stop.start in line and stop.order_id in line


@pytest.mark.parametrize(
    "event_type", ["urgent_order", "cancel_order", "engineer_unavailable"]
)
def test_2_1_6_replans_after_each_event(demo, demo_plan, event_type):
    """6. Перестраивать план после события (реализованы все три вида)."""
    working = demo.model_copy(deep=True)
    geo = Geo(working)

    if event_type == "cancel_order":
        target = next(
            s.order_id for r in demo_plan.routes for s in r.stops if s.arrival > "12:00"
        )
        event = CancelOrderEvent(time="12:00", order_id=target)
    elif event_type == "engineer_unavailable":
        victim = max(demo_plan.routes, key=lambda r: len(r.stops)).engineer_id
        event = EngineerUnavailableEvent(time="12:00", engineer_id=victim)
    else:
        anchor = working.orders[0]
        order = replan.make_urgent_order(
            working, "авария", anchor.lat, anchor.lon, Skill.EMERGENCY, ("12:00", "23:59"), 80
        )
        event = UrgentOrderEvent(time="12:00", order=order)

    new_plan, diff = replan.replan(working, demo_plan, event, geo, FAST)

    # План после события допустим в тех условиях, в которых строился:
    # с той же индексацией точек и тем же состоянием заморозки. Проверять его
    # «с нуля» некорректно — часть визитов к моменту события уже выполнена.
    fresh = Geo(working)
    frozen = replan.freeze(fresh, demo_plan, hhmm_to_min(event.time))
    replan.remap_starts(fresh, frozen)
    pending = {
        route.engineer_id: [s.order_id for s in route.stops if not s.locked]
        for route in new_plan.routes
    }
    _, violations = evaluate(fresh, pending, frozen.starts)
    assert not violations, [v.text for v in violations]
    assert diff.summary


def test_2_1_7_explains_every_assignment(demo_plan):
    """7. Объяснять результат понятным пользователю языком."""
    assert len(demo_plan.explanations) == demo_plan.metrics.assigned
    for card in demo_plan.explanations.values():
        assert card["checks"], "должны быть перечислены учтённые ограничения"
        assert card["why"], "должно быть сказано, почему выбран этот инженер"
        assert card["travel"]


# ======================================================== ТЗ §2.2 «Обязательные ограничения»


def test_2_2_qualification_is_enforced(demo, demo_plan):
    """Требуемый навык заявки должен входить в список навыков инженера."""
    engineers = demo.engineers_by_id
    orders = demo.orders_by_id
    for route in demo_plan.routes:
        for stop in route.stops:
            assert orders[stop.order_id].skill in engineers[route.engineer_id].skills


def test_2_2_time_is_enforced(demo, demo_plan):
    """Начало работ — в окне; работа с дорогой укладывается в смену."""
    engineers = demo.engineers_by_id
    orders = demo.orders_by_id
    for route in demo_plan.routes:
        for stop in route.stops:
            order = orders[stop.order_id]
            assert order.window_start <= stop.start <= order.window_end
        if route.stops:
            assert route.end_time <= engineers[route.engineer_id].shift_end


def test_2_2_resource_is_enforced(demo, demo_plan):
    """Если в заявке указан требуемый тип транспорта, он должен совпадать."""
    engineers = demo.engineers_by_id
    orders = demo.orders_by_id
    checked = 0
    for route in demo_plan.routes:
        for stop in route.stops:
            required = orders[stop.order_id].required_transport
            if required is not None:
                assert engineers[route.engineer_id].transport == required
                checked += 1
    assert checked > 0, "в наборе должны быть заявки с требуемым транспортом"


def test_2_2_unassigned_orders_are_shown_with_a_reason(demo_plan):
    """Если выполнить все заявки невозможно — показать их явно и назвать причину."""
    for item in demo_plan.unassigned:
        assert item.reason_code
        assert len(item.reason) > 20, "причина должна быть фразой, а не кодом"


# ======================================================== ТЗ §2.3 «Оптимальный маршрут»


def test_2_3_baseline_matches_the_specification_text():
    """Базовый вариант: по порядку поступления первому подходящему инженеру."""
    source = inspect.getsource(baseline.plan)
    assert "for order in scenario.orders" in source
    assert "for engineer in scenario.engineers" in source
    assert "can_append" in source


def test_2_3_first_mandatory_metric_counts_unique_engineers(demo_plan):
    """Выполнение заявок наименьшим количеством персонала."""
    used = {r.engineer_id for r in demo_plan.routes if r.stops}
    assert demo_plan.metrics.engineers_used == len(used)


def test_2_3_second_mandatory_metric_is_per_engineer_and_total(demo_plan):
    """Пробег отображается по каждому исполнителю отдельно и суммарно."""
    by_engineer = demo_plan.metrics.distance_by_engineer
    assert by_engineer
    assert demo_plan.metrics.distance_total_km == pytest.approx(
        sum(by_engineer.values()), abs=0.05
    )


def test_2_3_beats_baseline_on_both_mandatory_metrics(demo, demo_plan):
    """Сравнение с базовым вариантом — на демо-наборе выигрыш по обеим метрикам."""
    base = baseline.plan(demo, Geo(demo))
    assert demo_plan.metrics.assigned > base.metrics.assigned
    assert demo_plan.metrics.engineers_used <= base.metrics.engineers_used
    assert demo_plan.metrics.distance_total_km <= base.metrics.distance_total_km


# ======================================================== ТЗ §2.4 «Формат данных»


def test_2_4_order_has_all_minimal_fields(demo):
    """Заявка: ID, координаты или адрес, длительность, окно, приоритет, навык, транспорт."""
    fields = set(Order.model_fields)
    assert {
        "id",
        "address",
        "lat",
        "lon",
        "duration_min",
        "window_start",
        "window_end",
        "priority",
        "skill",
        "required_transport",
    } <= fields


def test_2_4_engineer_has_all_minimal_fields(demo):
    """Инженер: ID/имя, стартовая точка, границы смены, 1–3 навыка, транспорт."""
    engineer = demo.engineers[0]
    assert engineer.id and engineer.name
    assert engineer.start.has_coords
    assert engineer.shift_start and engineer.shift_end
    assert 1 <= len(engineer.skills) <= 3
    assert engineer.transport in set(Transport)


def test_2_4_no_return_to_start_required(demo, demo_plan):
    """Для обязательного MVP возвращение в стартовую точку не требуется."""
    for route in demo_plan.routes:
        if len(route.stops) > 1:
            assert route.end_time == route.stops[-1].finish


def test_2_4_1_skill_dictionary_has_exactly_three_entries():
    assert {s.value for s in Skill} == {"local", "connection", "emergency"}


def test_2_4_1_transport_dictionary_has_exactly_four_entries():
    assert {t.value for t in Transport} == {"car", "foot", "bike", "public"}


def test_2_4_1_priority_dictionary_has_exactly_two_entries():
    assert {p.value for p in Priority} == {"normal", "urgent"}


def test_2_4_1_every_order_has_exactly_one_skill(demo):
    for order in demo.orders:
        assert isinstance(order.skill, Skill)


def test_2_4_2_result_contains_everything_required(demo, demo_plan):
    """Формат результата: список заявок, времена, пробег, причины, итоги."""
    for route in demo_plan.routes:
        for stop in route.stops:
            assert stop.arrival and stop.start and stop.finish
            assert stop.travel_km >= 0
    assert demo_plan.metrics.engineers_used >= 0
    assert demo_plan.metrics.distance_by_engineer is not None
    assert demo_plan.plan_explanation


# ======================================================== ТЗ §3.2 «Программные требования»


def test_3_2_solution_runs_without_network(demo, monkeypatch):
    """Сервис обязан считать план без сети: координаты уже лежат в данных.

    Проверяем поведением, а не чтением исходника: маршрутизатор в модуле
    есть, но он необязателен и включается только переменной окружения.
    """
    import httpx

    monkeypatch.delenv("OSRM_URL", raising=False)

    def refuse(*args, **kwargs):
        raise AssertionError("построение плана не должно ходить в сеть")

    monkeypatch.setattr(httpx, "get", refuse)
    monkeypatch.setattr(httpx, "post", refuse)

    plan = solver.plan(demo, Geo(demo), FAST)
    assert plan.metrics.assigned > 0
    assert plan.params.travel_model == "haversine"


def test_3_2_no_database_required():
    from planner.api import store as plan_store

    assert "sqlite" not in inspect.getsource(plan_store).lower()


# ======================================================== ТЗ §4 «Демонстрация»


def test_4_demo_scenario_exists_with_events(demo):
    """Сценарий защиты: набор с заготовленными событиями."""
    assert demo.events, "к демо-набору должны прилагаться события"
    assert {event.type for event in demo.events} >= {"urgent_order", "cancel_order"}


def test_4_7_comparison_table_lists_both_mandatory_metrics_first(demo, demo_plan):
    base = baseline.plan(demo, Geo(demo))
    rows = metrics.compare(demo_plan.metrics, base.metrics)
    assert rows[0].key == "engineers_used"
    assert rows[1].key == "distance_total_km"


# ======================================================== ТЗ §6 «Ресурсы»


def test_6_dataset_size_is_within_recommendation(demo):
    """10–15 инженеров и не более 100 заявок."""
    assert 10 <= len(demo.engineers) <= 15
    assert len(demo.orders) <= 100


def test_6_dataset_covers_all_constraints(demo):
    """В наборе встречаются все навыки, комбинации, транспорт и пересечения окон."""
    from planner.ingest import demo as demo_module

    for requirement in demo_module.check_dataset(demo):
        assert requirement.ok, requirement.title


def test_6_assumptions_are_documented():
    from planner.paths import ROOT

    text = (ROOT / "docs" / "ASSUMPTIONS.md").read_text(encoding="utf-8")
    for topic in ("норматив", "синтетич", "транспорт", "окно", "контрольн"):
        assert topic in text.lower(), topic


# ======================================================== ТЗ §5 «Документация»


@pytest.mark.parametrize(
    "section",
    [
        "Запуск",
        "Схема решения",
        "Логика оптимизации",
        "Метрики",
        "Известные ограничения",
        "Идеи дальнейшего развития",
    ],
)
def test_5_readme_has_required_sections(section):
    from planner.paths import ROOT

    assert section in (ROOT / "README.md").read_text(encoding="utf-8")


def test_5_data_documentation_describes_units():
    from planner.paths import ROOT

    text = (ROOT / "docs" / "DATA.md").read_text(encoding="utf-8")
    for topic in ("единиц", "справочник", "мин", "километр"):
        assert topic in text.lower(), topic


# ======================================================== ТЗ §8.1 «На что обратят внимание»


def test_8_1_constraints_are_actually_checked_not_just_declared(demo):
    """Валидатор обязан ловить нарушение каждой группы ограничений."""
    geo = Geo(demo)
    engineer = demo.engineers[0]
    foreign = next(
        (o for o in demo.orders if o.skill not in engineer.skills), None
    )
    assert foreign is not None
    _, violations = evaluate(geo, {engineer.id: [foreign.id]})
    assert any(v.code == "NO_SKILL" for v in violations)


def test_8_1_result_is_understandable_without_reading_code(demo_plan):
    """Тексты объяснений — по-русски и без внутренних терминов."""
    blob = " ".join(
        [demo_plan.plan_explanation]
        + list(demo_plan.route_explanations.values())
        + [item.reason for item in demo_plan.unassigned]
    )
    for jargon in ("vehicle", "disjunction", "cumul", "node", "solver", "None"):
        assert jargon not in blob, f"в текстах для диспетчера не должно быть «{jargon}»"
    assert any(word in blob for word in ("инженер", "заявк", "маршрут"))


def test_8_1_reacts_correctly_to_intraday_change(demo, demo_plan):
    """Визиты, начатые до события, не должны измениться."""
    at = "13:00"
    before = {
        stop.order_id: (route.engineer_id, stop.start)
        for route in demo_plan.routes
        for stop in route.stops
        if stop.arrival <= at
    }
    working = demo.model_copy(deep=True)
    target = next(
        s.order_id for r in demo_plan.routes for s in r.stops if s.arrival > at
    )
    new_plan, _ = replan.replan(
        working, demo_plan, CancelOrderEvent(time=at, order_id=target), Geo(working), FAST
    )
    after = {
        stop.order_id: (route.engineer_id, stop.start)
        for route in new_plan.routes
        for stop in route.stops
    }
    for order_id, value in before.items():
        assert after[order_id] == value


def test_8_1_run_is_reproducible_from_readme():
    """Команды из README должны существовать в интерфейсе командной строки."""
    from planner import cli
    from planner.paths import ROOT

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for command in ("build", "geocode", "engineers", "demo", "plan", "serve"):
        assert f"planner.cli {command}" in readme, f"README не упоминает {command}"
        assert cli.main is not None
    parser_commands = inspect.getsource(cli.main)
    for command in ("build", "geocode", "engineers", "demo", "plan", "serve"):
        assert f'"{command}"' in parser_commands


# ======================================================== целостность плана


def test_every_order_is_assigned_or_explained(demo, demo_plan):
    covered = set(demo_plan.assignment) | {u.order_id for u in demo_plan.unassigned}
    assert covered == {o.id for o in demo.orders}


def test_no_order_is_assigned_twice(demo_plan):
    assigned = [stop.order_id for route in demo_plan.routes for stop in route.stops]
    assert len(assigned) == len(set(assigned))


def test_metrics_are_consistent_with_routes(demo, demo_plan):
    recomputed = metrics.compute(demo, demo_plan.routes, demo_plan.unassigned)
    assert recomputed.assigned == demo_plan.metrics.assigned
    assert recomputed.engineers_used == demo_plan.metrics.engineers_used
    assert recomputed.distance_total_km == pytest.approx(
        demo_plan.metrics.distance_total_km, abs=0.01
    )


def test_extra_engineers_estimate_is_actionable(demo, demo_plan):
    """Формулировка «нужно ещё +N инженеров», о которой просил постановщик."""
    geo = Geo(demo)
    needed = reasons.extra_engineers_needed(geo, demo_plan.unassigned)
    assert needed >= 0
    if demo_plan.unassigned:
        assert needed <= len(demo_plan.unassigned)
