"""Выгрузка результата планирования в формате отчёта на русском языке."""

from __future__ import annotations

from fastapi import APIRouter

from planner.api import lookup
from planner.core import metrics as metrics_module
from planner.core.models import TRANSPORT_RU, Plan, Route, Stop, Unassigned
from planner.core.validate import Geo

router = APIRouter()


@router.get("/api/plans/{plan_id}/export")
def export_plan(plan_id: str) -> dict:
    """Результат планирования в формате выгрузки."""
    record = lookup.record(plan_id)
    plan, geo = record.plan, record.geo

    return {
        "сценарий": record.scenario.name,
        "дата": record.scenario.date,
        "исполнители": [_route_rows(geo, route) for route in plan.routes if route.stops],
        "не_назначены": [_unassigned_row(geo, item) for item in plan.unassigned],
        "итого": _totals(plan),
        "сравнение_с_базовым_вариантом": _comparison(plan, record.baseline),
        "объяснение": plan.plan_explanation,
    }


def _route_rows(geo: Geo, route: Route) -> dict:
    engineer = geo.engineers[route.engineer_id]
    return {
        "исполнитель": engineer.name,
        "транспорт": TRANSPORT_RU[engineer.transport],
        "смена": f"{engineer.shift_start}–{engineer.shift_end}",
        "пробег_км": route.distance_km,
        "заявки": [_stop_row(geo, stop) for stop in route.stops],
    }


def _stop_row(geo: Geo, stop: Stop) -> dict:
    order = geo.orders[stop.order_id]
    return {
        "заявка": stop.order_id,
        "адрес": order.address,
        "окно": f"{order.window_start}–{order.window_end}",
        "прибытие": stop.arrival,
        "начало_работ": stop.start,
        "окончание": stop.finish,
        "пробег_км": stop.travel_km,
    }


def _unassigned_row(geo: Geo, unassigned: Unassigned) -> dict:
    known = unassigned.order_id in geo.orders
    return {
        "заявка": unassigned.order_id,
        "адрес": geo.orders[unassigned.order_id].address if known else "",
        "причина": unassigned.reason,
    }


def _totals(plan: Plan) -> dict:
    return {
        "задействовано_исполнителей": plan.metrics.engineers_used,
        "пробег_по_исполнителям_км": plan.metrics.distance_by_engineer,
        "суммарный_пробег_км": plan.metrics.distance_total_km,
        "назначено_заявок": plan.metrics.assigned,
        "не_назначено_заявок": plan.metrics.unassigned,
    }


def _comparison(plan: Plan, baseline: Plan | None) -> list[dict]:
    if baseline is None:
        return []
    return [
        {
            "показатель": row.title,
            "наш_план": row.ours,
            "базовый": row.baseline,
            "разница": row.delta,
        }
        for row in metrics_module.compare(plan.metrics, baseline.metrics)
    ]
