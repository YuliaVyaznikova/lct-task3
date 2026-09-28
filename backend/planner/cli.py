"""Командная строка сервиса."""

from __future__ import annotations

import argparse
import collections
import sys

from planner.core.models import Scenario
from planner.ingest import beeline, equipment, store
from planner.paths import CACHE_DIR, RAW_DIR, ensure_dirs


def _specs(region: str) -> list[beeline.RegionSpec]:
    if region == "all":
        return list(beeline.REGIONS)
    if region not in beeline.REGION_BY_ID:
        raise SystemExit(
            f"неизвестный регион {region!r}; доступны: all, "
            + ", ".join(beeline.REGION_BY_ID)
        )
    return [beeline.REGION_BY_ID[region]]


def cmd_build(args: argparse.Namespace) -> int:
    ensure_dirs()
    for spec in _specs(args.region):
        synthetic, control = beeline.find_region_files(spec, RAW_DIR)
        scenario = beeline.load_region(synthetic, control, spec=spec)
        equipment.populate(scenario)
        path = store.save(scenario)
        brigades = beeline.control_brigades(scenario)
        cancelled = beeline.cancelled_orders(scenario)
        needs_equipment = sum(1 for o in scenario.orders if o.attributes.get("equipment"))
        print(
            f"{scenario.name:<12} заявок {len(scenario.orders):>3}"
            f"  бригад в контроле {len(brigades):>2}"
            f"  отменённых {len(cancelled):>2}"
            f"  дата {scenario.date}"
            f"  -> {path.relative_to(path.parents[2])}"
        )
        print(f"{'':<12} офис: {scenario.office.address}")
        print(f"{'':<12} заявок с оборудованием: {needs_equipment}; {equipment.summary(scenario)}")
    return 0


def cmd_engineers(args: argparse.Namespace) -> int:
    from planner.ingest import engineers as gen

    ensure_dirs()
    for spec in _specs(args.region):
        scenario = store.load(spec.id)
        gen.populate(scenario, seed=args.seed)
        store.save(scenario)
        required = sum(1 for o in scenario.orders if o.required_transport is not None)
        print(f"{scenario.name:<12} инженеров {len(scenario.engineers):>2}  seed {scenario.meta.generator_seed}")
        print(f"{'':<12} {gen.summary(scenario.engineers)}")
        print(f"{'':<12} заявок с требуемым транспортом: {required}")
        if args.verbose:
            for e in scenario.engineers:
                print(
                    f"{'':<14} {e.id} {e.transport.value:<7} {e.shift_start}–{e.shift_end} "
                    f"[{', '.join(s.value for s in e.skills)}]"
                )
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    from planner.ingest import demo

    ensure_dirs()
    print(f"подбираем демо-набор на основе региона «{args.base}»…")
    scenario, report = demo.build(args.base, verbose=args.verbose)
    path = store.save(scenario)

    print(f"\n{scenario.name}: {len(scenario.orders)} заявок, {len(scenario.engineers)} инженеров")
    for requirement in report:
        mark = "+" if requirement.ok else "-"
        print(f"  [{mark}] {requirement.title}" + (f": {requirement.detail}" if requirement.detail else ""))
    print(f"\n  события для демонстрации:")
    for event in scenario.events:
        target = getattr(event, "order_id", None) or getattr(event, "engineer_id", None)
        if target is None:
            target = event.order.id
        print(f"    {event.time}  {event.type:<22} {target}")
    print(f"\n  -> {path}")
    return 0


def _show_scenario_ids(region: str) -> list[str]:
    if region == "demo":
        return ["demo"]
    return [spec.id for spec in _specs(region)]


def _print_scenario_summary(scenario: Scenario) -> None:
    print(f"\n=== {scenario.name} ({scenario.id}), {scenario.date} ===")
    print(f"офис: {scenario.office.address}")
    print(f"заявок: {len(scenario.orders)}, инженеров: {len(scenario.engineers)}")

    by_skill = collections.Counter(o.skill.value for o in scenario.orders)
    by_priority = collections.Counter(o.priority.value for o in scenario.orders)
    by_window = collections.Counter(
        f"{o.window_start}–{o.window_end}" for o in scenario.orders
    )
    by_duration = collections.Counter(o.duration_min for o in scenario.orders)
    no_coords = sum(1 for o in scenario.orders if not o.has_coords)

    print("навыки:     ", dict(by_skill))
    print("приоритеты: ", dict(by_priority))
    print("длительности:", dict(sorted(by_duration.items())))
    print("окна:       ", dict(sorted(by_window.items())))
    print("районов:    ", len({o.district for o in scenario.orders}))
    print("без координат:", no_coords)
    if scenario.events:
        print(f"заготовок событий: {len(scenario.events)}")


def cmd_show(args: argparse.Namespace) -> int:
    for scenario_id in _show_scenario_ids(args.region):
        _print_scenario_summary(store.load(scenario_id))
    return 0


def cmd_geocode(args: argparse.Namespace) -> int:
    from planner.ingest import geocode

    ensure_dirs()
    specs = _specs(args.region)
    scenarios = [store.load(spec.id) for spec in specs]

    providers = geocode.Providers()
    keys = [
        name
        for name, key in (("DaData", providers.dadata_key), ("Яндекс", providers.yandex_key))
        if key
    ]
    print(f"ключи: {', '.join(keys) if keys else 'нет (работаем на Nominatim/Photon)'}")

    districts = geocode.Districts()
    cache = geocode.Cache()
    overrides = geocode.load_overrides()

    print("центроиды районов…", end=" ", flush=True)
    names = geocode.resolve_districts(scenarios, providers, districts)
    districts.save(names)
    print(f"{len(districts.points)} шт.")

    lines: list[str] = ["# Отчёт геокодирования", ""]
    totals: collections.Counter[str] = collections.Counter()
    for scenario in scenarios:
        print(f"\n{scenario.name}: {len(scenario.orders)} заявок")
        report = geocode.apply_to_scenario(
            scenario, providers, districts, cache, overrides,
            progress=(print if args.verbose else None),
        )
        cache.save()
        store.save(scenario)

        lines.append(f"## {scenario.name} ({scenario.id})")
        lines.append("")
        lines.append(f"офис: {scenario.office.address} -> {scenario.office.lat:.5f}, {scenario.office.lon:.5f}")
        lines.append("")
        lines.append("| заявка | адрес | качество | провайдер | координаты |")
        lines.append("|---|---|---|---|---|")
        counts: collections.Counter[str] = collections.Counter()
        for order, result, log in report:
            counts[result.quality.value] += 1
            totals[result.quality.value] += 1
            lines.append(
                f"| {order.id} | {order.address} | {result.quality.value} | "
                f"{result.provider} | {result.lat:.5f}, {result.lon:.5f} |"
            )
            for entry in log:
                lines.append(f"| | ↳ {entry} | | | |")
        lines.append("")
        print("  итог:", dict(counts))

    if providers.errors:
        lines += ["## Ошибки провайдеров", ""] + [f"- {e}" for e in providers.errors[:50]] + [""]
    report_path = CACHE_DIR / "geocode_report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")

    total = sum(totals.values())
    exact_share = 100.0 * (totals["exact"] + totals["manual"]) / total if total else 0.0
    print(f"\nвсего {total} адресов: {dict(totals)}; точных {exact_share:.1f}%")
    print(f"отчёт: {report_path}")
    return 0


def _plan_scenario_ids(region: str) -> list[str]:
    if region != "all":
        return [region]
    return [spec.id for spec in beeline.REGIONS] + ["demo"]


def cmd_plan(args: argparse.Namespace) -> int:
    from planner.core import baseline, explain, metrics, solver
    from planner.core.models import PlanParams
    from planner.core.validate import Geo

    for spec_id in _plan_scenario_ids(args.region):
        try:
            scenario = store.load(spec_id)
        except FileNotFoundError:
            continue
        if not scenario.engineers:
            print(f"{spec_id}: нет инженеров, запустите «engineers»")
            continue

        geo = Geo(scenario)
        params = PlanParams(objective=args.objective, time_limit_s=args.time_limit)
        plan = solver.plan(scenario, geo, params)
        explain.attach(geo, plan)
        base = baseline.plan(scenario, geo)

        print(f"\n=== {scenario.name} ===")
        print(metrics.comparison_table(plan.metrics, base.metrics))
        print(f"\n{plan.plan_explanation}")
        if args.verbose:
            for route in plan.routes:
                if route.stops:
                    print("\n" + plan.route_explanations[route.engineer_id])
                    for line in explain.timeline_summary(geo, route):
                        print("   " + line)
            if plan.unassigned:
                print("\nНе назначены:")
                for item in plan.unassigned:
                    print(f"   {item.order_id}: {item.reason}")
    return 0


def cmd_control(args: argparse.Namespace) -> int:
    from planner.core import control, solver
    from planner.core.models import PlanParams
    from planner.core.validate import Geo

    for spec in _specs(args.region):
        scenario = store.load(spec.id)
        if not control.has_control(scenario):
            print(f"{scenario.name}: контрольного распределения нет")
            continue
        reference = control.build(scenario)
        geo = Geo(scenario)
        ours = solver.plan(scenario, geo, PlanParams(time_limit_s=args.time_limit))

        print(f"\n=== {scenario.name} ===")
        print(" ", reference.summary())
        print(f"  покрыто контролем: {reference.covered_orders} из {len(scenario.orders)} заявок")
        print()
        print(f"  {'показатель':<30}{'наш план':>12}{'факт':>12}")
        print("  " + "-" * 54)
        for title, mine, fact in control.comparison_rows(ours.metrics, reference.metrics):
            print(f"  {title:<30}{mine:>12.1f}{fact:>12.1f}")
        print(f"  {'визитов начато позже окна':<30}{0:>12}{reference.late_starts:>12}")
    return 0


def cmd_calibrate(args: argparse.Namespace) -> int:
    """Сверяет офлайн-модель расстояний с реальной дорожной сетью (OSRM)."""
    import numpy as np

    from planner.core.travel import OsrmTravel, TravelModel, _haversine_matrix

    pairs: list[tuple[float, float, float]] = []
    for spec in _specs(args.region):
        scenario = store.load(spec.id)
        points = [o.coords for o in scenario.orders] + [scenario.office.coords]
        if len(points) > OsrmTravel.MAX_POINTS:
            points = points[: OsrmTravel.MAX_POINTS]
        road_model = OsrmTravel(points, args.osrm)
        if not road_model.connected:
            print(f"{scenario.name}: OSRM недоступен ({'; '.join(road_model.errors[:1])})")
            continue
        straight = _haversine_matrix(points)
        offline = TravelModel(points)
        for i in range(len(points)):
            for j in range(len(points)):
                if i != j and straight[i, j] > 0.2:
                    pairs.append(
                        (straight[i, j], road_model.distance_km(i, j), offline.distance_km(i, j))
                    )
        print(f"{scenario.name:<12} точек {len(points):>3}")

    if not pairs:
        print("нет данных для калибровки")
        return 1

    data = np.array(pairs)
    straight, road, offline = data[:, 0], data[:, 1], data[:, 2]
    print()
    print(f"пар точек: {len(data)}")
    print()
    print(f"{'диапазон, км':<16}{'пар':>7}{'дорога/прямая':>16}{'ошибка модели':>16}")
    for low, high in ((0.2, 1), (1, 3), (3, 10), (10, 30), (30, 500)):
        mask = (straight >= low) & (straight < high)
        if not mask.any():
            continue
        factor = float(np.median(road[mask] / straight[mask]))
        error = float(np.median(np.abs(offline[mask] - road[mask]) / road[mask]) * 100)
        print(f"{f'{low}–{high}':<16}{int(mask.sum()):>7}{factor:>16.2f}{error:>15.1f}%")
    total_error = float(np.median(np.abs(offline - road) / road) * 100)
    print()
    print(f"медианная ошибка офлайн-модели против дорожной сети: {total_error:.1f}%")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    ensure_dirs()
    uvicorn.run("planner.api.app:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="planner", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    build_cmd = sub.add_parser("build", help="собрать сценарии из выгрузки билайна")
    build_cmd.add_argument("--region", default="all")
    build_cmd.set_defaults(func=cmd_build)

    geocode_cmd = sub.add_parser("geocode", help="проставить координаты заявкам и офисам")
    geocode_cmd.add_argument("--region", default="all")
    geocode_cmd.add_argument("--verbose", action="store_true", help="печатать каждый адрес")
    geocode_cmd.set_defaults(func=cmd_geocode)

    engineers_cmd = sub.add_parser("engineers", help="сгенерировать справочник инженеров")
    engineers_cmd.add_argument("--region", default="all")
    engineers_cmd.add_argument("--seed", type=int, default=42)
    engineers_cmd.add_argument("--verbose", action="store_true")
    engineers_cmd.set_defaults(func=cmd_engineers)

    demo_cmd = sub.add_parser("demo", help="собрать демонстрационный сценарий с событиями")
    demo_cmd.add_argument("--base", default="vostok", help="регион-основа")
    demo_cmd.add_argument("--verbose", action="store_true")
    demo_cmd.set_defaults(func=cmd_demo)

    show_cmd = sub.add_parser("show", help="сводка по собранному сценарию")
    show_cmd.add_argument("--region", default="all")
    show_cmd.set_defaults(func=cmd_show)

    plan_cmd = sub.add_parser("plan", help="построить план и сравнить с базовым вариантом")
    plan_cmd.add_argument("--region", default="demo")
    plan_cmd.add_argument("--objective", default="auto",
                          choices=["auto", "min_engineers", "min_distance"])
    plan_cmd.add_argument("--time-limit", type=int, default=20, dest="time_limit")
    plan_cmd.add_argument("--verbose", action="store_true", help="печатать маршруты и отказы")
    plan_cmd.set_defaults(func=cmd_plan)

    control_cmd = sub.add_parser(
        "control", help="справочное сравнение с фактическим ручным распределением"
    )
    control_cmd.add_argument("--region", default="all")
    control_cmd.add_argument("--time-limit", type=int, default=20, dest="time_limit")
    control_cmd.set_defaults(func=cmd_control)

    calibrate_cmd = sub.add_parser(
        "calibrate", help="сверить модель расстояний с реальной дорожной сетью"
    )
    calibrate_cmd.add_argument("--region", default="all")
    calibrate_cmd.add_argument("--osrm", default="https://router.project-osrm.org")
    calibrate_cmd.set_defaults(func=cmd_calibrate)

    serve_cmd = sub.add_parser("serve", help="запустить веб-сервис")
    serve_cmd.add_argument("--host", default="127.0.0.1")
    serve_cmd.add_argument("--port", type=int, default=8000)
    serve_cmd.add_argument("--reload", action="store_true")
    serve_cmd.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
