"""Deterministic uncertainty policy for a non-blocking planning dialogue."""

from __future__ import annotations

from app.domain.models import (
    Ambiguity,
    PlanningConfidence,
    PlanningConfidenceLevel,
    PlanningUncertainty,
    TravelRequest,
    UncertaintyImpact,
)

_IMPACT_PENALTIES = {
    "origin_city": 100,
    "destination_scope": 24,
    "month": 24,
    "budget_total_rub": 22,
    "adults": 12,
    "visa_willingness": 8,
    "max_flight_duration_hours": 8,
    "trip_style": 6,
    "baggage_required": 3,
}

_IMPACT_BY_FIELD: dict[str, UncertaintyImpact] = {
    "origin_city": "high",
    "destination_scope": "high",
    "month": "high",
    "budget_total_rub": "high",
    "adults": "medium",
    "visa_willingness": "medium",
    "max_flight_duration_hours": "medium",
    "trip_style": "low",
    "baggage_required": "low",
}

_EFFECT_BY_FIELD = {
    "origin_city": "Нельзя корректно сопоставить маршруты и перелёты.",
    "destination_scope": "Меняет состав shortlist и ограничения на въезд.",
    "month": "Меняет сезонность, ориентиры цен и пригодность мест.",
    "budget_total_rub": "Без него нельзя оценить, насколько варианты комфортны по цене.",
    "adults": "Влияет на интерпретацию общего бюджета и размещения.",
    "visa_willingness": "Меняет допустимые страны и требования к въезду.",
    "max_flight_duration_hours": "Меняет ранжирование по удобству дороги.",
    "trip_style": "Уточняет личные предпочтения внутри уже подходящих вариантов.",
    "baggage_required": "Уточняет будущую стоимость билетов, но не сам выбор направления.",
}


def detect_ambiguities(request: TravelRequest) -> list[Ambiguity]:
    """Classify missing fields without promoting every useful detail to a blocker."""

    items: list[Ambiguity] = []
    if request.origin_city is None:
        items.append(
            Ambiguity(
                field="origin_city",
                topic="departure",
                priority="P0",
                reason=_EFFECT_BY_FIELD["origin_city"],
                question="Из какого города вылетаете? Можно просто: «из Москвы».",
                options=["Москва", "Санкт-Петербург", "Другой город"],
            )
        )
    if request.destination_scope is None:
        items.append(
            Ambiguity(
                field="destination_scope",
                topic="geography",
                priority="P1",
                reason=_EFFECT_BY_FIELD["destination_scope"],
                question="Что рассматриваете: Россию, зарубежье или оба варианта?",
                options=["По России", "За границу", "Оба варианта"],
                default_value="any",
                can_use_default=True,
            )
        )
    if (
        request.month is None
        and request.date_from is None
        and request.departure_window_from is None
        and request.flight_departure_date is None
    ):
        items.append(
            Ambiguity(
                field="month",
                topic="timing",
                priority="P1",
                reason=_EFFECT_BY_FIELD["month"],
                question=(
                    "Когда хотите поехать? Подойдут месяц, точные даты или диапазон — "
                    "например, «20 августа — 3 сентября»."
                ),
                options=["Ближайший месяц", "Укажу месяц", "Укажу точные даты"],
                can_use_default=True,
            )
        )
    if request.budget_total_rub is None:
        items.append(
            Ambiguity(
                field="budget_total_rub",
                topic="budget",
                priority="P1",
                reason=_EFFECT_BY_FIELD["budget_total_rub"],
                question="Какой общий бюджет на поездку будет комфортным?",
                options=["До 100 000 ₽", "100–200 000 ₽", "Более 200 000 ₽"],
                can_use_default=True,
            )
        )
    if request.adults is None:
        items.append(
            Ambiguity(
                field="adults",
                topic="party",
                priority="P1",
                reason=_EFFECT_BY_FIELD["adults"],
                question="Кто едет и сколько вас будет?",
                options=["1", "2", "3+"],
                can_use_default=True,
            )
        )
    if request.visa_willingness is None:
        items.append(
            Ambiguity(
                field="visa_willingness",
                topic="travel_friction",
                priority="P1",
                reason=_EFFECT_BY_FIELD["visa_willingness"],
                question="Виза допустима или лучше смотреть безвизовые направления?",
                options=["Только без визы", "Подойдёт eVisa", "Виза возможна"],
                default_value="any",
                can_use_default=True,
            )
        )
    if request.max_flight_duration_hours is None:
        items.append(
            Ambiguity(
                field="max_flight_duration_hours",
                topic="travel_friction",
                priority="P1",
                reason=_EFFECT_BY_FIELD["max_flight_duration_hours"],
                question="Есть предел по длительности перелёта или пересадкам?",
                options=["До 4 часов", "До 7 часов", "Неважно"],
                can_use_default=True,
            )
        )
    if request.baggage_required is None:
        items.append(
            Ambiguity(
                field="baggage_required",
                topic="travel_friction",
                priority="P2",
                reason=_EFFECT_BY_FIELD["baggage_required"],
                default_value=True,
                can_use_default=True,
            )
        )
    if not request.trip_style:
        items.append(
            Ambiguity(
                field="trip_style",
                topic="trip_style",
                priority="P2",
                reason=_EFFECT_BY_FIELD["trip_style"],
                question="Какой ритм отдыха ближе: спокойно, активно или универсально?",
                options=["Спокойно", "Активно", "Универсально"],
                default_value="универсальный отдых",
                can_use_default=True,
            )
        )
    return sorted(
        items,
        key=lambda item: (
            {"P0": 0, "P1": 1, "P2": 2}[item.priority],
            -_IMPACT_PENALTIES[item.field],
        ),
    )


def clarification_questions(ambiguities: list[Ambiguity]) -> list[Ambiguity]:
    """Interrupt only for information without which a flight-aware shortlist is invalid."""

    return [item for item in ambiguities if item.priority == "P0" and item.question][:1]


def explicit_assumptions(ambiguities: list[Ambiguity]) -> list[str]:
    """Show conditional reasoning instead of silently fabricating values for unknowns."""

    labels = {
        "destination_scope": (
            "География не указана: shortlist включает Россию и зарубежные варианты."
        ),
        "month": "Период не указан: сезонность, цены и погоду считаем ориентировочными.",
        "budget_total_rub": (
            "Бюджет не указан: варианты не отсекаются по цене, а показаны диапазонами."
        ),
        "adults": (
            "Состав путешественников не указан: общий бюджет и размещение требуют уточнения позже."
        ),
        "visa_willingness": "Готовность оформлять визу не указана: рассматриваем любые варианты.",
        "max_flight_duration_hours": "Ограничение по длительности перелёта не указано.",
        "baggage_required": "Для оценки стоимости предполагаем багаж в тарифе.",
        "trip_style": "Формат отдыха не указан: используем универсальные критерии.",
    }
    return [
        labels[item.field]
        for item in ambiguities
        if item.priority != "P0" and item.can_use_default and item.field in labels
    ]


def planning_confidence(ambiguities: list[Ambiguity]) -> PlanningConfidence:
    """Return a deterministic confidence band for the usable, but partially specified plan."""

    unresolved = [item for item in ambiguities if item.priority != "P0"]
    penalty = sum(_IMPACT_PENALTIES[item.field] for item in unresolved)
    score = max(15, 100 - penalty)
    level: PlanningConfidenceLevel
    if score >= 75:
        level = "high"
        summary = "Подборка хорошо опирается на заданные условия."
    elif score >= 50:
        level = "medium"
        summary = (
            "Подборка уже полезна; несколько условий могут заметно изменить порядок вариантов."
        )
    else:
        level = "low"
        summary = (
            "Подборка — широкий ориентир: её можно смотреть сейчас, а даты или бюджет позже "
            "сделают оценку точнее."
        )
    return PlanningConfidence(
        score=score,
        level=level,
        summary=summary,
        uncertainties=[
            PlanningUncertainty(
                field=item.field,
                impact=_IMPACT_BY_FIELD[item.field],
                effect=_EFFECT_BY_FIELD[item.field],
            )
            for item in unresolved
        ],
    )


def next_best_question(ambiguities: list[Ambiguity]) -> Ambiguity | None:
    """Choose one advisory question by deterministic expected planning impact."""

    return next(
        (item for item in ambiguities if item.priority != "P0" and item.question),
        None,
    )
