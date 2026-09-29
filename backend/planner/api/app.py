"""HTTP API сервиса планирования: сборка приложения из маршрутов."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from planner.api import (
    export,
    geometry_routes,
    manual,
    plans,
    saved_routes,
    scenarios,
    static,
)

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

for module in (scenarios, plans, manual, saved_routes, geometry_routes, export):
    app.include_router(module.router)
static.mount_frontend(app)
