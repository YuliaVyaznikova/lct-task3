"""Раздача собранного интерфейса из frontend/dist."""

from __future__ import annotations

import mimetypes

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from planner.paths import ROOT

FRONTEND_DIR = ROOT / "frontend" / "dist"
MIME_BY_EXTENSION = {
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".woff2": "font/woff2",
}


def mount_frontend(app: FastAPI) -> None:
    """Подключить собранный интерфейс, если он есть."""
    if not FRONTEND_DIR.is_dir():
        return

    for extension, mime in MIME_BY_EXTENSION.items():
        mimetypes.add_type(mime, extension)
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "index.html")

    @app.get("/{path:path}")
    def spa(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, f"Нет такого метода API: /{path}")
        candidate = (FRONTEND_DIR / path).resolve()
        if candidate.is_file() and candidate.is_relative_to(FRONTEND_DIR.resolve()):
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIR / "index.html")
