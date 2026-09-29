"""Командная строка сервиса."""

from __future__ import annotations

import pytest

from planner import cli


def test_plan_for_an_unknown_region_fails_loudly():
    """Раньше команда молча ничего не печатала и завершалась с кодом 0."""
    with pytest.raises(SystemExit) as failure:
        cli.main(["plan", "--region", "no-such-region"])
    assert "no-such-region" in str(failure.value.code)
