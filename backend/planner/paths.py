"""Пути проекта. Единственное место, где зашита структура каталогов."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
CONFIG_DIR = DATA_DIR / "config"
CACHE_DIR = DATA_DIR / "cache"
SCENARIOS_DIR = DATA_DIR / "scenarios"
RUNTIME_DIR = ROOT / "runtime"
PLANS_DIR = RUNTIME_DIR / "plans"


def ensure_dirs() -> None:
    for path in (CACHE_DIR, SCENARIOS_DIR, PLANS_DIR, CACHE_DIR / "matrices"):
        path.mkdir(parents=True, exist_ok=True)


def _from_dotenv(env_name: str) -> str | None:
    path = ROOT / ".env"
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() == env_name:
            return value.strip().strip('"').strip("'") or None
    return None


def read_secret(env_name: str, *filenames: str) -> str | None:
    """Ключ из переменной окружения, из .env или из файла в корне (всё в .gitignore)."""
    import os

    value = os.environ.get(env_name)
    if value and value.strip():
        return value.strip()
    value = _from_dotenv(env_name)
    if value:
        return value
    for name in filenames:
        candidate = ROOT / name
        if candidate.is_file():
            text = candidate.read_text(encoding="utf-8").strip()
            if text:
                return text.splitlines()[0].strip()
    return None
