"""Чтение и запись сценариев в data/scenarios/."""

from __future__ import annotations

import json
from pathlib import Path

from planner.core.models import Scenario
from planner.paths import SCENARIOS_DIR


def scenario_path(scenario_id: str, directory: Path | None = None) -> Path:
    return (directory or SCENARIOS_DIR) / f"{scenario_id}.json"


def save(scenario: Scenario, directory: Path | None = None) -> Path:
    path = scenario_path(scenario.id, directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = scenario.model_dump(mode="json", exclude_defaults=False)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def load(scenario_id: str, directory: Path | None = None) -> Scenario:
    path = scenario_path(scenario_id, directory)
    if not path.is_file():
        raise FileNotFoundError(f"нет сценария {scenario_id}: {path}")
    return Scenario.model_validate_json(path.read_text(encoding="utf-8"))


def load_all(directory: Path | None = None) -> list[Scenario]:
    directory = directory or SCENARIOS_DIR
    if not directory.is_dir():
        return []
    return [
        Scenario.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("*.json"))
    ]
