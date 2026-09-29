"""Сигнал остановки расчёта для текущего потока."""

from __future__ import annotations

import threading

_local = threading.local()


class Cancelled(Exception):
    """Расчёт остановлен по запросу диспетчера."""


def bind(stop: threading.Event | None) -> None:
    _local.stop = stop


def requested() -> bool:
    stop = getattr(_local, "stop", None)
    return stop is not None and stop.is_set()


def check() -> None:
    if requested():
        raise Cancelled()
