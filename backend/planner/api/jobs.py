"""Фоновые расчёты и поток событий для диспетчера."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from queue import Queue
from threading import Lock, Thread
from time import monotonic
from uuid import uuid4

from pydantic import BaseModel

PROGRESS_INTERVAL_S = 0.25

logger = logging.getLogger(__name__)


def _error_message(error: Exception) -> str:
    return str(getattr(error, "detail", None) or error)


class PlanningJob:
    def __init__(self) -> None:
        self.events: Queue[tuple[str, dict]] = Queue()
        self.last_progress_at: dict[str | None, float] = {}

    def progress(self, payload: dict) -> None:
        now = monotonic()
        variant = payload.get("variant")
        last_sent_at = self.last_progress_at.get(variant, float("-inf"))
        if now - last_sent_at < PROGRESS_INTERVAL_S:
            return
        self.last_progress_at[variant] = now
        self.events.put(("progress", payload))

    def run(self, work: Callable[[Callable[[dict], None]], BaseModel]) -> None:
        try:
            result = work(self.progress)
            self.events.put(("done", result.model_dump(mode="json", by_alias=True)))
        except Exception as exc:
            logger.exception("фоновый расчёт завершился ошибкой")
            self.events.put(("error", {"detail": _error_message(exc)}))

    def stream(self):
        while True:
            kind, payload = self.events.get()
            yield f"event: {kind}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            if kind in {"done", "error"}:
                return


class JobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, PlanningJob] = {}
        self._lock = Lock()

    def submit(self, work: Callable[[Callable[[dict], None]], BaseModel]) -> str:
        job_id = uuid4().hex
        job = PlanningJob()
        with self._lock:
            self._jobs[job_id] = job
        Thread(target=job.run, args=(work,), daemon=True).start()
        return job_id

    def get(self, job_id: str) -> PlanningJob:
        with self._lock:
            return self._jobs[job_id]


jobs = JobRegistry()
