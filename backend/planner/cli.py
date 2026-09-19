"""Командная строка сервиса.

    python -m planner.cli build [--region all|vostok|yugo-vostok|yugocentr]
    python -m planner.cli show  --region vostok

Остальные команды (geocode, plan, compare, replan, serve) добавляются
по мере готовности соответствующих модулей.
"""

from __future__ import annotations

import argparse
import collections
import sys

from planner.ingest import beeline, store
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
        path = store.save(scenario)
        brigades = beeline.control_brigades(scenario)
        cancelled = beeline.cancelled_orders(scenario)
        print(
            f"{scenario.name:<12} заявок {len(scenario.orders):>3}"
            f"  бригад в контроле {len(brigades):>2}"
            f"  отменённых {len(cancelled):>2}"
            f"  дата {scenario.date}"
            f"  -> {path.relative_to(path.parents[2])}"
        )
        print(f"{'':<12} офис: {scenario.office.address}")
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


def cmd_show(args: argparse.Namespace) -> int:
    for spec in _specs(args.region):
        scenario = store.load(spec.id)
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
    return 0


def cmd_geocode(args: argparse.Namespace) -> int:
    from planner.ingest import geocode

    ensure_dirs()
    specs = _specs(args.region)
    scenarios = [store.load(spec.id) for spec in specs]

    providers = geocode.Providers()
    keys = [name for name, key in
            (("DaData", providers.dadata_key), ("Яндекс", providers.yandex_key)) if key]
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="planner", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="собрать сценарии из выгрузки билайна")
    build.add_argument("--region", default="all")
    build.set_defaults(func=cmd_build)

    geocode_cmd = sub.add_parser("geocode", help="проставить координаты заявкам и офисам")
    geocode_cmd.add_argument("--region", default="all")
    geocode_cmd.add_argument("--verbose", action="store_true", help="печатать каждый адрес")
    geocode_cmd.set_defaults(func=cmd_geocode)

    engineers_cmd = sub.add_parser("engineers", help="сгенерировать справочник инженеров")
    engineers_cmd.add_argument("--region", default="all")
    engineers_cmd.add_argument("--seed", type=int, default=42)
    engineers_cmd.add_argument("--verbose", action="store_true")
    engineers_cmd.set_defaults(func=cmd_engineers)

    show = sub.add_parser("show", help="сводка по собранному сценарию")
    show.add_argument("--region", default="all")
    show.set_defaults(func=cmd_show)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
