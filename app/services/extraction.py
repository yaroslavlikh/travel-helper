"""Deterministic demo extraction used until the selected LLM adapter is introduced."""

from __future__ import annotations

import re
from typing import Any

from app.domain.models import TravelRequest

MONTH_BY_FRAGMENT = {
    "январ": 1,
    "феврал": 2,
    "март": 3,
    "апрел": 4,
    "мая": 5,
    "июн": 6,
    "июл": 7,
    "август": 8,
    "сентябр": 9,
    "октябр": 10,
    "ноябр": 11,
    "декабр": 12,
}

ORIGIN_BY_FRAGMENT = {
    "москв": ("Москва", "Россия"),
    "санкт-петербург": ("Санкт-Петербург", "Россия"),
    "петербург": ("Санкт-Петербург", "Россия"),
    "казан": ("Казань", "Россия"),
    "екатеринбург": ("Екатеринбург", "Россия"),
}

NUMBER_WORDS = {
    "один": 1,
    "двое": 2,
    "два": 2,
    "три": 3,
    "трое": 3,
    "четыре": 4,
}


def _parse_budget_rub(text: str) -> int | None:
    match = re.search(r"(\d+(?:[\s\u00a0]\d{3})?)\s*(?:тыс(?:яч[аи])?\.?|к\b)", text)
    if match:
        return int(match.group(1).replace(" ", "").replace("\u00a0", "")) * 1_000
    match = re.search(r"(?:бюджет\s*)?(\d{4,7})\s*(?:руб(?:лей|\.)?)?", text)
    return int(match.group(1)) if match else None


def _parse_duration_nights(text: str) -> tuple[int | None, int | None]:
    interval = re.search(r"(\d+)\s*(?:[-–—]|до)\s*(\d+)\s*(?:дн(?:ей|я)?|ноч(?:ей|и)?)", text)
    if interval:
        return int(interval.group(1)), int(interval.group(2))
    single = re.search(r"(\d+)\s*(?:дн(?:ей|я)?|ноч(?:ей|и)?)", text)
    if single:
        value = int(single.group(1))
        return value, value
    if "недел" in text:
        return 7, 7
    return None, None


def _apply_answers(values: dict[str, Any], answers: dict[str, Any]) -> None:
    allowed_fields = set(TravelRequest.model_fields) - {"raw_query"}
    for field, value in answers.items():
        if field in allowed_fields and value not in (None, ""):
            values[field] = value


def extract_travel_request(raw_query: str, answers: dict[str, Any] | None = None) -> TravelRequest:
    """Extract a conservative request patch without turning inference into a fact."""

    text = raw_query.casefold()
    values: dict[str, Any] = {"raw_query": raw_query}
    for fragment, (city, country) in ORIGIN_BY_FRAGMENT.items():
        if fragment in text:
            values.update(origin_city=city, origin_country=country)
            break
    for fragment, month in MONTH_BY_FRAGMENT.items():
        if fragment in text:
            values["month"] = month
            break

    duration_min, duration_max = _parse_duration_nights(text)
    if duration_min is not None:
        values.update(duration_nights_min=duration_min, duration_nights_max=duration_max)
    budget = _parse_budget_rub(text)
    if budget is not None:
        values["budget_total_rub"] = budget

    if "на одного" in text or "один взросл" in text:
        values["adults"] = 1
    elif re.search(r"(?:нас\s+)?двое(?:\s+(?:взросл|человек))?", text):
        values["adults"] = 2
    elif re.search(r"трое\s+(?:взросл|человек)", text):
        values["adults"] = 3
    if "с ребенк" in text or "с детьми" in text:
        values.update(children=1)
        values.setdefault("adults", 1)

    if any(fragment in text for fragment in ("за границ", "зарубеж", "международ")):
        values["destination_scope"] = "international"
    elif any(fragment in text for fragment in ("по россии", "в россии", "внутри страны")):
        values["destination_scope"] = "domestic"
    if any(fragment in text for fragment in ("море", "пляж")):
        values["sea_required"] = True
    if any(
        fragment in text
        for fragment in ("не люблю жар", "не люблю сильную жар", "без жары", "не жарко")
    ):
        values.update(heat_tolerance="low", avoid=["сильная жара"])
    elif "жару люблю" in text:
        values["heat_tolerance"] = "high"

    temperature_match = re.search(r"не выше\s*(\d{2}(?:[.,]\d+)?)\s*(?:°|град)", text)
    if temperature_match:
        values["preferred_max_temperature_c"] = float(temperature_match.group(1).replace(",", "."))
    flight_match = re.search(
        r"(?:не больше|максимум|до)\s*(\d+(?:[.,]\d+)?|один|два|три|четыре)\s*час",
        text,
    )
    if flight_match:
        flight_value = flight_match.group(1)
        values["max_flight_duration_hours"] = float(
            NUMBER_WORDS.get(flight_value, flight_value.replace(",", "."))
        )
    if "без пересад" in text:
        values["preferences"] = ["без пересадок"]
    if "без виз" in text:
        values["visa_willingness"] = "no_visa"
    elif "электронн" in text and "виз" in text:
        values["visa_willingness"] = "evisa_ok"
    if any(fragment in text for fragment in ("строгий бюджет", "не дороже", "не больше")):
        values["budget_strict"] = True
    if "ночн" in text and "жизн" in text:
        values["preferences"] = [*values.get("preferences", []), "ночная жизнь"]

    _apply_answers(values, answers or {})
    return TravelRequest.model_validate(values)
