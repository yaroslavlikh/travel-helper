"""Deterministic ambiguity classification and explicit default disclosure."""

from __future__ import annotations

from app.domain.models import Ambiguity, TravelRequest


def detect_ambiguities(request: TravelRequest) -> list[Ambiguity]:
    """Return every relevant ambiguity, sorted by product priority."""

    items: list[Ambiguity] = []
    if request.origin_city is None:
        items.append(
            Ambiguity(
                field="origin_city",
                priority="P0",
                reason="Без города вылета нельзя оценить маршруты и стоимость.",
                question="Из какого города планируете вылет?",
                options=["Москва", "Санкт-Петербург", "Другой город"],
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
                priority="P0",
                reason="Период влияет на цены, погоду и доступность рейсов.",
                question="В каком месяце или в какие даты хотите поехать?",
                options=["Ближайший месяц", "Укажу месяц", "Укажу точные даты"],
            )
        )
    if request.adults is None:
        items.append(
            Ambiguity(
                field="adults",
                priority="P0",
                reason="Бюджет и варианты размещения зависят от числа путешественников.",
                question="Сколько взрослых поедет?",
                options=["1", "2", "3+"],
            )
        )
    if request.budget_total_rub is None:
        items.append(
            Ambiguity(
                field="budget_total_rub",
                priority="P0",
                reason="Без примерного бюджета нельзя применить ключевой фильтр.",
                question="Какой ориентировочный общий бюджет на поездку в рублях?",
                options=["До 100 000 ₽", "100–200 000 ₽", "Более 200 000 ₽"],
            )
        )
    if request.destination_scope is None:
        items.append(
            Ambiguity(
                field="destination_scope",
                priority="P0",
                reason="Нужно понять, допустимы ли зарубежные направления.",
                question="Рассматривать поездки по России, за границу или оба варианта?",
                options=["По России", "За границу", "Оба варианта"],
            )
        )
    if request.visa_willingness is None:
        items.append(
            Ambiguity(
                field="visa_willingness",
                priority="P1",
                reason="Визовые ограничения существенно меняют список стран.",
                default_value="any",
                can_use_default=True,
            )
        )
    if request.max_flight_duration_hours is None:
        items.append(
            Ambiguity(
                field="max_flight_duration_hours",
                priority="P1",
                reason="Допустимая длительность перелёта влияет на ранжирование.",
                can_use_default=True,
            )
        )
    if request.baggage_required is None:
        items.append(
            Ambiguity(
                field="baggage_required",
                priority="P1",
                reason="Багаж влияет на итоговую стоимость авиабилета.",
                default_value=True,
                can_use_default=True,
            )
        )
    if not request.trip_style:
        items.append(
            Ambiguity(
                field="trip_style",
                priority="P2",
                reason="Формат отдыха помогает персонализировать ранжирование.",
                default_value="универсальный отдых",
                can_use_default=True,
            )
        )
    return sorted(items, key=lambda item: {"P0": 0, "P1": 1, "P2": 2}[item.priority])


def clarification_questions(ambiguities: list[Ambiguity]) -> list[Ambiguity]:
    """Ask at most three P0 questions and never ask optional defaults prematurely."""

    return [item for item in ambiguities if item.priority == "P0" and item.question][:3]


def explicit_assumptions(ambiguities: list[Ambiguity]) -> list[str]:
    """Disclose every P1/P2 default when the search can proceed."""

    labels = {
        "visa_willingness": "Готовность оформлять визу не указана: рассматриваем любые варианты.",
        "max_flight_duration_hours": "Ограничение по длительности перелёта не указано.",
        "baggage_required": "Для оценки стоимости предполагаем багаж в тарифе.",
        "trip_style": "Формат отдыха не указан: используем универсальные критерии.",
    }
    return [
        labels[item.field] for item in ambiguities if item.priority != "P0" and item.can_use_default
    ]
