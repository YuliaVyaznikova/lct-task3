"""Справочники по типу заявки: нормативы и оборудование ищут правило одинаково."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, TypeVar


class WorkTypeRule(Protocol):
    @property
    def work_type(self) -> str: ...

    @property
    def hd_match(self) -> str: ...


RuleT = TypeVar("RuleT", bound=WorkTypeRule)


def first_match(rules: Iterable[RuleT], work_type: str, hd_type: str) -> RuleT | None:
    """Первое сверху правило с совпавшими типом работ (целиком) и типом HD (подстрокой); * подходит любому."""
    work = (work_type or "").strip().casefold()
    hd = (hd_type or "").strip().casefold()
    for rule in rules:
        if rule.work_type != "*" and rule.work_type != work:
            continue
        if rule.hd_match != "*" and rule.hd_match not in hd:
            continue
        return rule
    return None
