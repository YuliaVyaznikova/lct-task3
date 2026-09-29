"""Сценарии: список, просмотр, справочники и загрузка своих данных."""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile

from planner.api import lookup
from planner.api.jobs import jobs
from planner.api.schemas import ScenarioBrief
from planner.core import cancel, travel
from planner.core.models import SKILL_RU, TRANSPORT_RU, ReasonCode, Scenario
from planner.ingest import beeline
from planner.ingest import engineers as engineers_module
from planner.ingest import geocode as geocode_module
from planner.ingest import normatives
from planner.ingest import store as scenario_store

router = APIRouter()


@router.get("/api/health")
def health() -> dict:
    return {"status": "ok", "scenarios": len(scenario_store.load_all())}


@router.get("/api/scenarios", response_model=list[ScenarioBrief])
def list_scenarios() -> list[ScenarioBrief]:
    briefs = [_brief(scenario) for scenario in scenario_store.load_all()]
    briefs.sort(key=lambda brief: (brief.id != "demo", brief.name))
    return briefs


@router.get("/api/scenarios/{scenario_id}", response_model=Scenario)
def get_scenario(scenario_id: str) -> Scenario:
    return lookup.load_scenario(scenario_id)


@router.get("/api/reference")
def reference() -> dict:
    """Справочники и допущения чтобы интерфейс не хранил их копию."""
    return {
        "skills": {key.value: value for key, value in SKILL_RU.items()},
        "transports": {key.value: value for key, value in TRANSPORT_RU.items()},
        "reason_codes": [code.value for code in ReasonCode],
        "work_types": normatives.work_types(),
        "travel_model": travel.describe(),
    }


@router.post("/api/scenarios/upload", response_model=Scenario)
async def upload_scenario(
    synthetic: UploadFile,
    control: UploadFile | None = None,
    seed: int = 42,
) -> Scenario:
    """Загрузка своих данных: CSV в формате выгрузки билайна либо готовый JSON-сценарий."""
    scenario, is_csv = await _read_upload(synthetic, control)
    return _finish_upload(scenario, is_csv, seed)


@router.post("/api/scenarios/upload/jobs")
async def upload_scenario_job(
    synthetic: UploadFile,
    control: UploadFile | None = None,
    seed: int = 42,
) -> dict[str, str]:
    """Та же загрузка фоновой задачей: поиск адресов присылает прогресс в поток событий расчёта."""
    scenario, is_csv = await _read_upload(synthetic, control)
    return {"job_id": jobs.submit(lambda progress: _finish_upload(scenario, is_csv, seed, progress))}


async def _read_upload(synthetic: UploadFile, control: UploadFile | None) -> tuple[Scenario, bool]:
    raw = await synthetic.read()
    name = synthetic.filename or "upload.csv"
    if name.lower().endswith(".json"):
        return _parse_json_scenario(raw), False
    control_raw = await control.read() if control is not None else None
    control_name = (control.filename if control else None) or "control.csv"
    return _parse_csv_scenario(name, raw, control_name, control_raw), True


def _finish_upload(scenario: Scenario, is_csv: bool, seed: int, progress=None) -> Scenario:
    if is_csv:
        _geocode(scenario, progress)
        engineers_module.populate(scenario, seed=seed, region_id=lookup.config_region(scenario.id))
    cancel.check()
    _save_upload(scenario)
    return scenario


def _brief(scenario: Scenario) -> ScenarioBrief:
    config = engineers_module.load_config(lookup.config_region(scenario.id))
    return ScenarioBrief(
        id=scenario.id,
        name=scenario.name,
        date=scenario.date,
        orders=len(scenario.orders),
        engineers=len(scenario.engineers),
        engineers_min=engineers_module.min_count(config),
        events=len(scenario.events),
        office=scenario.office.address,
    )


def _parse_json_scenario(raw: bytes) -> Scenario:
    try:
        return Scenario.model_validate_json(raw.decode("utf-8"))
    except ValueError as exc:
        raise HTTPException(422, f"Не удалось разобрать JSON-сценарий: {exc}") from None


def _parse_csv_scenario(
    name: str, raw: bytes, control_name: str, control_raw: bytes | None
) -> Scenario:
    with tempfile.TemporaryDirectory() as tmp:
        synthetic_path = Path(tmp) / name
        synthetic_path.write_bytes(raw)

        control_path = None
        if control_raw is not None:
            control_path = Path(tmp) / control_name
            control_path.write_bytes(control_raw)

        try:
            return beeline.load_region(synthetic_path, control_path)
        except beeline.IngestError as exc:
            raise HTTPException(422, f"Не удалось прочитать выгрузку: {exc}") from None


def _geocode(scenario: Scenario, progress=None) -> None:
    cache = geocode_module.Cache()

    def on_located(done: int, total: int) -> None:
        cancel.check()
        if progress is not None:
            progress({"stage": "geocode", "done": done, "total": total})

    try:
        geocode_module.apply_to_scenario(
            scenario, geocode_module.Providers(), geocode_module.Districts(), cache,
            on_located=on_located,
        )
    except geocode_module.GeocodeError as exc:
        raise HTTPException(
            422,
            "Не удалось определить координаты адресов: "
            f"{exc}. Проверьте формат файла или соберите сценарий командой "
            "python -m planner.cli build && python -m planner.cli geocode.",
        ) from None
    finally:
        cache.save()


def _save_upload(scenario: Scenario) -> None:
    """Загруженный набор не затирает сохранённый сценарий, при совпадении id получает новый."""
    free = scenario_store.free_id(scenario.id)
    if free != scenario.id:
        scenario.id = free
        if scenario.name in scenario_store.names():
            scenario.name = f"{scenario.name} ({free.rsplit('-', 1)[1]})"
    scenario_store.save(scenario)
