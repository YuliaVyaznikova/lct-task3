"""Разбор адресов выгрузки билайна в вид, понятный геокодерам."""

from __future__ import annotations

import re
from dataclasses import dataclass

STREET_TYPES: dict[str, str] = {
    "ул": "улица",
    "улица": "улица",
    "пр-кт": "проспект",
    "просп": "проспект",
    "проспект": "проспект",
    "б-р": "бульвар",
    "бульвар": "бульвар",
    "проезд": "проезд",
    "пр-зд": "проезд",
    "пер": "переулок",
    "переулок": "переулок",
    "наб": "набережная",
    "набережная": "набережная",
    "ш": "шоссе",
    "шоссе": "шоссе",
    "туп": "тупик",
    "пл": "площадь",
    "кв-л": "квартал",
    "квартал": "квартал",
}

_ADJECTIVE_TAIL = re.compile(
    r"(ский|ской|цкий|цкой|ный|ная|ний|няя|ый|ая|ой|ий|яя|ое|ее)$",
    re.IGNORECASE,
)
_GENITIVE_TAIL = re.compile(r"(иной|овой|евой|ёвой|ыной)$", re.IGNORECASE)

CITIES = ("Домодедово", "Кашира", "Ступино", "Москва")

MOSCOW_REGION_CITIES = ("Домодедово", "Кашира", "Ступино")

_CITY_PREFIXES = (
    "г.город ",
    "город ",
    "г. ",
    "г.",
    "мо, ",
    "обл.московская область, ",
    "московская область, ",
)


@dataclass(frozen=True)
class NormalizedAddress:
    raw: str
    query: str
    region: str
    city: str
    street: str
    house: str
    settlement: str = ""

    @property
    def query_no_house(self) -> str:
        parts = [self.region if self.region != self.city else "", self.city, self.settlement, self.street]
        return ", ".join(p for p in parts if p)


def _strip_city(text: str) -> tuple[str, str, str]:
    """Отделяет город и регион от остатка адреса."""
    rest = text
    settlement = ""
    city = ""

    m = re.search(r"пгт\.?\s*([\w\-]+)", rest, re.IGNORECASE)
    if m:
        settlement = m.group(1)
        rest = rest[: m.start()] + rest[m.end() :]

    lowered = rest.casefold()
    for prefix in _CITY_PREFIXES:
        if lowered.startswith(prefix):
            rest = rest[len(prefix) :]
            lowered = rest.casefold()

    for candidate in CITIES:
        pattern = re.compile(rf"(?:^|[,\s]|г\.\s*){re.escape(candidate)}\b", re.IGNORECASE)
        m = pattern.search(rest)
        if m:
            city = candidate
            rest = (rest[: m.start()] + " " + rest[m.end() :]).strip(" ,")
            break

    rest = re.sub(r"^(?:г\.)?город\s+москва\b[,\s]*", "", rest, flags=re.IGNORECASE)
    rest = re.sub(r"^(?:г\.)\s*", "", rest)
    rest = rest.strip(" ,")

    region = "Москва" if city == "Москва" else "Московская область"
    return rest, city or "Москва", region if city else "Москва", settlement


_HOUSE_RE = re.compile(
    r"(?:^|[,\s])д\.?\s*"
    r"(?P<number>[0-9]+(?:/[0-9]+)?)"
    r"(?P<letter>[а-яё](?![0-9]))?",
    re.IGNORECASE,
)
_HOUSE_KORPUS_ONLY_RE = re.compile(r"(?:^|[,\s])д\.?\s*(к\s*[0-9]+[а-яё]?)", re.IGNORECASE)


def _extract_house(text: str) -> tuple[str, str]:
    """Возвращает (остаток без дома, дом в компактной записи «128к5», «24/30с1», «16к2»)."""
    house_parts: list[str] = []

    m = _HOUSE_RE.search(text)
    if m:
        house_parts.append(m.group("number"))
        if m.group("letter"):
            house_parts.append(m.group("letter").upper())
        cut_start, cut_end = m.start(), m.end()
    else:
        m = _HOUSE_KORPUS_ONLY_RE.search(text)
        if not m:
            return text.strip(" ,"), ""
        cut_start, cut_end = m.start(), m.end()
        house_parts.append(re.sub(r"\s+", "", m.group(1)).lower())

    tail = text[cut_end:]
    korpus = re.match(r"\s*к(?:орп)?\.?\s*([0-9]+[а-яё]?)", tail, re.IGNORECASE)
    if korpus:
        house_parts.append("к" + korpus.group(1).lower())
        tail = tail[korpus.end() :]
    building = re.match(r"\s*,?\s*стр\.?\s*([0-9]+[а-яё]?)", tail, re.IGNORECASE)
    if building:
        house_parts.append("с" + building.group(1).lower())

    rest = (text[:cut_start] + " ").strip(" ,")
    return rest, "".join(house_parts)


def _format_street(name: str, street_type: str) -> str:
    name = re.sub(r"\s+", " ", name).strip(" ,.")
    if not name:
        return street_type
    if not street_type:
        return name
    last_word = name.split()[-1]
    if _ADJECTIVE_TAIL.search(last_word) and not _GENITIVE_TAIL.search(last_word):
        return f"{name} {street_type}"
    return f"{street_type} {name}"


def _extract_street(text: str) -> str:
    text = text.strip(" ,")
    if not text:
        return ""

    m = re.match(r"^([а-яё\-]+)\.?\s*(.+)$", text, re.IGNORECASE)
    if m and m.group(1).casefold() in STREET_TYPES:
        return _format_street(m.group(2), STREET_TYPES[m.group(1).casefold()])

    m = re.match(r"^(.+?)\s+([а-яё\-]+)\.?$", text, re.IGNORECASE)
    if m and m.group(2).casefold() in STREET_TYPES:
        return _format_street(m.group(1), STREET_TYPES[m.group(2).casefold()])

    m = re.search(r"\s+([а-яё\-]+)\.\s*", text, re.IGNORECASE)
    if m and m.group(1).casefold() in STREET_TYPES:
        name = (text[: m.start()] + " " + text[m.end() :]).strip()
        return _format_street(name, STREET_TYPES[m.group(1).casefold()])

    return re.sub(r"\s+", " ", text).strip(" ,.")


def normalize(raw: str) -> NormalizedAddress:
    text = re.sub(r"\s+", " ", (raw or "").replace("\xa0", " ")).strip()
    text = text.replace("кв.", "").strip(" ,")
    text = re.sub(r",\s*кв\.?\s*[0-9]+\s*$", "", text, flags=re.IGNORECASE)

    rest, city, region, settlement = _strip_city(text)
    rest, house = _extract_house(rest)
    street = _extract_street(rest)

    parts = [region if region != city else "", city, settlement, street, house]
    query = ", ".join(p for p in parts if p)
    return NormalizedAddress(
        raw=raw,
        query=query,
        region=region,
        city=city,
        street=street,
        house=house,
        settlement=settlement,
    )
