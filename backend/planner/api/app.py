"""HTTP API сервиса планирования."""

from __future__ import annotations

import mimetypes
import re
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Body, FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from planner.api.store import PlanRecord, next_plan_id, store
from planner.api import candidates as candidates_module
from planner.api.jobs import jobs
from planner.core import baseline as baseline_module
from planner.core import control as control_module
from planner.core import explain as explain_module
from planner.core import geometry as geometry_module
from planner.core import metrics as metrics_module
from planner.core import replan as replan_module
from planner.core import solver, travel
from planner.core.models import (
    SKILL_RU,
    TRANSPORT_RU,
    Event,
    Plan,
    PlanParams,
    Metrics,
    ReasonCode,
    Route,
    Scenario,
    Unassigned,
)
from planner.core.reasons import diagnose, extra_engineers_needed
from planner.core.validate import Geo, StartState, best_insertion, evaluate, first_blocking_violation
from planner.ingest import beeline
from planner.ingest import engineers as engineers_module
from planner.ingest import normatives
from planner.ingest import store as scenario_store
from planner.paths import ROOT

app = FastAPI(
    title="Планирование маршрутов инженеров",
    description="ЛЦТ 2026, задача №3 «билайн бизнес»",
    version="1.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ScenarioBrief(BaseModel):
    id: str
    name: str
    date: str
    orders: int
    engineers: int
    engineers_min: int
    events: int
    office: str


class PlanRequest(BaseModel):
    scenario_id: str
    params: PlanParams = Field(default_factory=PlanParams)
    engineer_count: int | None = None


class MetricRowOut(BaseModel):
    key: str
    title: str
    ours: float
    baseline: float
    delta: float
    better: bool | None


class ControlReferenceOut(BaseModel):
    """Справочное сопоставление с фактическим ручным распределением."""

    available: bool
    summary: str = ""
    brigades: int = 0
    covered_orders: int = 0
    late_starts: int = 0
    rows: list[dict] = Field(default_factory=list)


class VariantOut(BaseModel):
    key: Literal["min_engineers", "min_distance", "balanced"]
    title: str
    plan_id: str
    metrics: Metrics


class PlanResponse(BaseModel):
    optimized: Plan
    baseline: Plan
    comparison: list[MetricRowOut]
    control: ControlReferenceOut
    scenario: Scenario
    variants: list[VariantOut] = Field(default_factory=list)


class ReplanResponse(BaseModel):
    plan: Plan
    diff: Any
    scenario: Scenario


class ManualRequest(BaseModel):
    order_id: str
    engineer_id: str | None = None
    position: int | Literal["best"] = "best"


def _comparison(ours: Plan, base: Plan) -> list[MetricRowOut]:
    return [
        MetricRowOut(
            key=row.key,
            title=row.title,
            ours=row.ours,
            baseline=row.baseline,
            delta=row.delta,
            better=row.better,
        )
        for row in metrics_module.compare(ours.metrics, base.metrics)
    ]


def _control(scenario: Scenario, plan: Plan) -> ControlReferenceOut:
    """Как эти же заявки распределили вручную."""
    if not control_module.has_control(scenario):
        return ControlReferenceOut(available=False)
    reference = control_module.build(scenario)
    return ControlReferenceOut(
        available=True,
        summary=reference.summary(),
        brigades=len(reference.brigades),
        covered_orders=reference.covered_orders,
        late_starts=reference.late_starts,
        rows=[
            {"title": title, "ours": ours, "control": fact}
            for title, ours, fact in control_module.comparison_rows(
                plan.metrics, reference.metrics
            )
        ],
    )


def _config_region(scenario_id: str) -> str:
    base_region_id = re.sub(r"-\d+$", "", scenario_id)
    if base_region_id in {"vostok", "yugo-vostok", "yugocentr"}:
        return base_region_id
    return "vostok"


def _save_upload(scenario: Scenario) -> None:
    """Загруженный набор никогда не затирает сохранённый сценарий, при совпадении id получает новый."""
    free = scenario_store.free_id(scenario.id)
    if free != scenario.id:
        scenario.id = free
        scenario.name = f"{scenario.name} ({free.rsplit('-', 1)[1]})"
    scenario_store.save(scenario)


def _record(plan_id: str) -> PlanRecord:
    try:
        return store.get(plan_id)
    except KeyError:
        raise HTTPException(404, f"План {plan_id} не найден. Постройте план заново.") from None


def _plan_response(record: PlanRecord) -> PlanResponse:
    baseline = record.baseline or baseline_module.plan(record.scenario, record.geo)
    return PlanResponse(
        optimized=record.plan,
        baseline=baseline,
        comparison=_comparison(record.plan, baseline),
        control=_control(record.scenario, record.plan),
        scenario=record.scenario,
        variants=[VariantOut.model_validate(item) for item in record.variants],
    )


def _load_scenario(scenario_id: str) -> Scenario:
    try:
        return scenario_store.load(scenario_id)
    except FileNotFoundError:
        raise HTTPException(
            404,
            f"Сценарий «{scenario_id}» не найден. Доступные: "
            + ", ".join(s.id for s in scenario_store.load_all()),
        ) from None


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "scenarios": len(scenario_store.load_all())}


@app.get("/api/scenarios", response_model=list[ScenarioBrief])
def list_scenarios() -> list[ScenarioBrief]:
    briefs = [
        ScenarioBrief(
            id=s.id,
            name=s.name,
            date=s.date,
            orders=len(s.orders),
            engineers=len(s.engineers),
            engineers_min=engineers_module.min_count(
                engineers_module.load_config(_config_region(s.id))
            ),
            events=len(s.events),
            office=s.office.address,
        )
        for s in scenario_store.load_all()
    ]
    briefs.sort(key=lambda b: (b.id != "demo", b.name))
    return briefs


@app.get("/api/scenarios/{scenario_id}", response_model=Scenario)
def get_scenario(scenario_id: str) -> Scenario:
    return _load_scenario(scenario_id)


@app.get("/api/reference")
def reference() -> dict:
    """Справочники и допущения чтобы интерфейс не хранил их копию."""
    return {
        "skills": {key.value: value for key, value in SKILL_RU.items()},
        "transports": {key.value: value for key, value in TRANSPORT_RU.items()},
        "reason_codes": [code.value for code in ReasonCode],
        "work_types": normatives.work_types(),
        "travel_model": travel.describe(),
    }


@app.post("/api/scenarios/upload", response_model=Scenario)
async def upload_scenario(
    synthetic: UploadFile,
    control: UploadFile | None = None,
    seed: int = 42,
) -> Scenario:
    """Загрузка своих данных: CSV в формате выгрузки билайна либо готовый JSON-сценарий."""
    import tempfile

    raw = await synthetic.read()
    name = synthetic.filename or "upload.csv"

    if name.lower().endswith(".json"):
        try:
            scenario = Scenario.model_validate_json(raw.decode("utf-8"))
        except Exception as exc:
            raise HTTPException(422, f"Не удалось разобрать JSON-сценарий: {exc}") from None
        _save_upload(scenario)
        return scenario

    with tempfile.TemporaryDirectory() as tmp:
        synthetic_path = Path(tmp) / name
        synthetic_path.write_bytes(raw)
        control_path = None
        if control is not None:
            control_path = Path(tmp) / (control.filename or "control.csv")
            control_path.write_bytes(await control.read())
        try:
            scenario = beeline.load_region(synthetic_path, control_path)
        except beeline.IngestError as exc:
            raise HTTPException(422, f"Не удалось прочитать выгрузку: {exc}") from None

    from planner.ingest import geocode as geocode_module

    providers = geocode_module.Providers()
    districts = geocode_module.Districts()
    cache = geocode_module.Cache()
    try:
        geocode_module.apply_to_scenario(scenario, providers, districts, cache)
        cache.save()
    except Exception as exc:
        raise HTTPException(
            422,
            "Не удалось определить координаты адресов: "
            f"{exc}. Проверьте формат файла или соберите сценарий командой "
            "python -m planner.cli build && python -m planner.cli geocode.",
        ) from None

    engineers_module.populate(
        scenario, seed=seed, region_id=scenario.id if scenario.id in {"vostok", "yugo-vostok", "yugocentr"} else "vostok"
    )
    _save_upload(scenario)
    return scenario


def _create_plan(request: PlanRequest, on_progress=None) -> PlanResponse:
    source = _load_scenario(request.scenario_id)
    working = source.model_copy(deep=True)

    if request.engineer_count and request.engineer_count != len(working.engineers):
        try:
            engineers_module.resize(
                working,
                request.engineer_count,
                region_id=_config_region(working.id),
            )
        except engineers_module.InvariantError as exc:
            raise HTTPException(422, str(exc)) from None

    geo = Geo(working)

    if request.params.objective == "auto":
        keys = ("min_engineers", "min_distance", "balanced")
        attempts = solver.parallel_plans(
            working, request.params, keys[:2], next_plan_id(), on_progress=on_progress
        )
        attempts.append(solver.balance(
            working, geo, request.params, attempts[1], next_plan_id(), on_progress=on_progress
        ))
        best = attempts[0]
        if metrics_module.is_better(attempts[1].metrics, best.metrics):
            best = attempts[1]
    else:
        keys = (request.params.objective,)
        attempts = [solver.plan(
            working, geo, request.params, plan_id=next_plan_id(), on_progress=on_progress
        )]
        best = attempts[0]

    titles = {
        "min_engineers": "Меньше инженеров",
        "min_distance": "Меньший пробег",
        "balanced": "Ровная загрузка",
    }
    for attempt in attempts:
        attempt.id = next_plan_id()
        explain_module.attach(geo, attempt)
    variants = [
        VariantOut(key=key, title=titles[key], plan_id=attempt.id, metrics=attempt.metrics)
        for key, attempt in zip(keys, attempts)
    ]
    base = baseline_module.plan(working, geo, plan_id=f"{best.id}-base")
    encoded_variants = [variant.model_dump(mode="json") for variant in variants]
    for attempt in attempts:
        store.put(PlanRecord(
            plan=attempt, scenario=working, baseline=base, variants=encoded_variants,
            selected_plan_id=best.id,
        ))
    return PlanResponse(
        optimized=best,
        baseline=base,
        comparison=_comparison(best, base),
        control=_control(working, best),
        scenario=working,
        variants=variants,
    )


@app.post("/api/plans", response_model=PlanResponse)
def create_plan(request: PlanRequest) -> PlanResponse:
    return _create_plan(request)


@app.post("/api/plans/jobs")
def create_plan_job(request: PlanRequest) -> dict[str, str]:
    _load_scenario(request.scenario_id)
    return {"job_id": jobs.submit(lambda progress: _create_plan(request, progress))}


@app.get("/api/plans/jobs/{job_id}/events")
def plan_job_events(job_id: str) -> StreamingResponse:
    try:
        job = jobs.get(job_id)
    except KeyError:
        raise HTTPException(404, f"Расчёт {job_id} не найден") from None
    return StreamingResponse(job.stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/api/plans/{plan_id}", response_model=PlanResponse)
def get_plan(plan_id: str) -> PlanResponse:
    return _plan_response(_record(plan_id))


@app.post("/api/plans/{plan_id}/select", response_model=PlanResponse)
def select_plan(plan_id: str) -> PlanResponse:
    _record(plan_id)
    store.select(plan_id)
    return get_plan(plan_id)


def _apply_event(plan_id: str, event: Event, on_progress=None) -> ReplanResponse:
    record = _record(plan_id)
    working = record.scenario.model_copy(deep=True)
    geo = Geo(working)
    new_id = next_plan_id()
    try:
        new_plan, diff = replan_module.replan(
            working, record.plan, event, geo, plan_id=new_id,
            on_progress=on_progress,
        )
    except replan_module.ReplanError as exc:
        raise HTTPException(409, str(exc)) from None

    store.put(
        PlanRecord(plan=new_plan, scenario=working, baseline=record.baseline, diff=diff)
    )
    return ReplanResponse(plan=new_plan, diff=diff, scenario=working)


@app.post("/api/plans/{plan_id}/events", response_model=ReplanResponse)
def apply_event(plan_id: str, event: Annotated[Event, Body()]) -> ReplanResponse:
    return _apply_event(plan_id, event)


@app.post("/api/plans/{plan_id}/events/jobs")
def apply_event_job(plan_id: str, event: Annotated[Event, Body()]) -> dict[str, str]:
    _record(plan_id)
    return {"job_id": jobs.submit(lambda progress: _apply_event(plan_id, event, progress))}


def _manual_assignment(record: PlanRecord, request: ManualRequest) -> dict[str, list[str]]:
    geo = record.geo
    if request.order_id not in geo.orders:
        raise HTTPException(404, f"Заявки {request.order_id} нет в сценарии")

    assignment = {route.engineer_id: list(route.order_ids) for route in record.plan.routes}
    for order_ids in assignment.values():
        if request.order_id in order_ids:
            order_ids.remove(request.order_id)

    if request.engineer_id is not None:
        if request.engineer_id not in geo.engineers:
            raise HTTPException(404, f"Инженера {request.engineer_id} нет в сценарии")
        engineer = geo.engineers[request.engineer_id]
        current = assignment.setdefault(request.engineer_id, [])

        if request.position == "best":
            found = best_insertion(
                geo, engineer, current, request.order_id, lunch=record.plan.params.lunch
            )
            if found is None:
                blocking = first_blocking_violation(
                    geo, engineer, current, request.order_id, lunch=record.plan.params.lunch
                )
                raise HTTPException(
                    422,
                    blocking.text if blocking else
                    f"{engineer.name} не может взять заявку {request.order_id}",
                )
            current.insert(found[0], request.order_id)
        else:
            position = max(0, min(int(request.position), len(current)))
            current.insert(position, request.order_id)

    return assignment


def _manual_unassigned(
    record: PlanRecord, request: ManualRequest, routes: list[Route]
) -> list[Unassigned]:
    geo = record.geo
    assigned = {stop.order_id for route in routes for stop in route.stops}
    unassigned: list[Unassigned] = []
    for order in record.scenario.orders:
        if order.id in assigned:
            continue
        if order.id == request.order_id and request.engineer_id is None:
            unassigned.append(
                Unassigned(
                    order_id=order.id,
                    reason_code=ReasonCode.MANUAL,
                    reason="снята с маршрута вручную диспетчером",
                )
            )
        else:
            unassigned.append(diagnose(geo, order, routes))
    return unassigned


@app.post("/api/plans/{plan_id}/manual", response_model=PlanResponse)
def manual_assign(plan_id: str, request: ManualRequest) -> PlanResponse:
    """Ручное переназначение заявки."""
    record = _record(plan_id)
    geo = record.geo
    assignment = _manual_assignment(record, request)
    routes, violations = evaluate(geo, assignment, lunch=record.plan.params.lunch)
    if violations:
        raise HTTPException(422, "; ".join(v.text for v in violations[:3]))

    unassigned = _manual_unassigned(record, request, routes)
    record.plan.routes = routes
    record.plan.unassigned = unassigned
    record.plan.metrics = metrics_module.compute(
        record.scenario, routes, unassigned, extra_engineers_needed(geo, unassigned)
    )
    explain_module.attach(geo, record.plan)
    store.put(record)

    return _plan_response(record)


@app.get("/api/plans/{plan_id}/candidates/{order_id}")
def get_candidates(plan_id: str, order_id: str) -> list[dict]:
    """Допустимые перестановки заявки и их влияние на два маршрута."""
    record = _record(plan_id)
    if order_id not in record.geo.orders:
        raise HTTPException(404, f"Заявки {order_id} нет в сценарии")
    return candidates_module.list_candidates(record.geo, record.plan, order_id)


@app.get("/api/plans/{plan_id}/explain/{order_id}")
def explain_order(plan_id: str, order_id: str) -> dict:
    record = _record(plan_id)
    card = record.plan.explanations.get(order_id)
    if card is not None:
        return {"assigned": True, **card}
    for unassigned in record.plan.unassigned:
        if unassigned.order_id == order_id:
            return {
                "assigned": False,
                "order_id": order_id,
                "reason_code": unassigned.reason_code.value,
                "reason": unassigned.reason,
            }
    raise HTTPException(404, f"Заявки {order_id} нет в плане {plan_id}")


@app.get("/api/plans/{plan_id}/geometry")
def plan_geometry(plan_id: str) -> dict:
    """Ломаные маршрутов по дорогам только для отрисовки на карте."""
    record = _record(plan_id)
    geometry = geometry_module.build(record.geo, record.plan)
    return {
        "available": geometry.available,
        "source": geometry.source,
        "profile": geometry_module.PROFILE,
        "routes": geometry.routes,
        "legs": geometry.legs,
        "errors": geometry.errors[:5],
    }


@app.get("/api/plans/{plan_id}/export")
def export_plan(plan_id: str) -> dict:
    """Результат планирования в формате выгрузки."""
    record = _record(plan_id)
    plan, geo = record.plan, record.geo
    base = record.baseline

    return {
        "сценарий": record.scenario.name,
        "дата": record.scenario.date,
        "исполнители": [
            {
                "исполнитель": geo.engineers[route.engineer_id].name,
                "транспорт": TRANSPORT_RU[geo.engineers[route.engineer_id].transport],
                "смена": f"{geo.engineers[route.engineer_id].shift_start}–"
                f"{geo.engineers[route.engineer_id].shift_end}",
                "пробег_км": route.distance_km,
                "заявки": [
                    {
                        "заявка": stop.order_id,
                        "адрес": geo.orders[stop.order_id].address,
                        "окно": f"{geo.orders[stop.order_id].window_start}–"
                        f"{geo.orders[stop.order_id].window_end}",
                        "прибытие": stop.arrival,
                        "начало_работ": stop.start,
                        "окончание": stop.finish,
                        "пробег_км": stop.travel_km,
                    }
                    for stop in route.stops
                ],
            }
            for route in plan.routes
            if route.stops
        ],
        "не_назначены": [
            {
                "заявка": u.order_id,
                "адрес": geo.orders[u.order_id].address if u.order_id in geo.orders else "",
                "причина": u.reason,
            }
            for u in plan.unassigned
        ],
        "итого": {
            "задействовано_исполнителей": plan.metrics.engineers_used,
            "пробег_по_исполнителям_км": plan.metrics.distance_by_engineer,
            "суммарный_пробег_км": plan.metrics.distance_total_km,
            "назначено_заявок": plan.metrics.assigned,
            "не_назначено_заявок": plan.metrics.unassigned,
        },
        "сравнение_с_базовым_вариантом": (
            [
                {
                    "показатель": row.title,
                    "наш_план": row.ours,
                    "базовый": row.baseline,
                    "разница": row.delta,
                }
                for row in metrics_module.compare(plan.metrics, base.metrics)
            ]
            if base
            else []
        ),
        "объяснение": plan.plan_explanation,
    }


for _extension, _mime in {
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".woff2": "font/woff2",
}.items():
    mimetypes.add_type(_mime, _extension)

_FRONTEND = ROOT / "frontend" / "dist"
if _FRONTEND.is_dir():
    app.mount("/assets", StaticFiles(directory=_FRONTEND / "assets"), name="assets")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(_FRONTEND / "index.html")

    @app.get("/{path:path}")
    def spa(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, f"Нет такого метода API: /{path}")
        candidate = (_FRONTEND / path).resolve()
        if candidate.is_file() and candidate.is_relative_to(_FRONTEND.resolve()):
            return FileResponse(candidate)
        return FileResponse(_FRONTEND / "index.html")
