"""Map deterministic pricing snapshots to the card contract."""

from __future__ import annotations

from typing import Literal

from app.domain.models import (
    PricingCardView,
    PricingComponentGroup,
    PricingComponentView,
    TravelRequest,
)
from app.pricing.models import ComponentName, CostComponent, FlightPriceSignal, TripPriceEstimate

COMPONENTS: dict[ComponentName, tuple[PricingComponentGroup, str]] = {
    "flight": ("flight", "Перелёт"),
    "stay": ("stay", "Жильё"),
    "food": ("daily", "Еда"),
    "local_transport": ("daily", "Транспорт"),
    "airport_transfer": ("daily", "Трансфер"),
    "activities": ("daily", "Активности"),
    "mandatory_charges": ("required", "Обязательные сборы"),
    "recommended": ("required", "Дополнительно"),
}


def pricing_card(
    *,
    request: TravelRequest,
    snapshot: TripPriceEstimate | None,
) -> PricingCardView:
    """Return an honest card for either a real snapshot or missing critical evidence."""

    if snapshot is None:
        return unavailable_pricing(request)
    components = [_component_view(component) for component in snapshot.components]
    if snapshot.total is None:
        return PricingCardView(
            status="unavailable",
            headline="Цена не рассчитана",
            subtitle="Нет полного сценария с перелётом и жильём на одни даты.",
            pricing_snapshot_id=snapshot.pricing_snapshot_id,
            components=components,
            freshness_label="Расчёт неполный",
            warnings=list(snapshot.warnings),
        )
    status: Literal["stale", "available"] = (
        "stale" if any(item.status == "stale" for item in snapshot.components) else "available"
    )
    return PricingCardView(
        status=status,
        headline=f"≈ {snapshot.total.expected:,} ₽".replace(",", " "),
        subtitle="Ожидаемый бюджет на всю поездку и всю группу.",
        pricing_snapshot_id=snapshot.pricing_snapshot_id,
        floor_total_rub=snapshot.total.floor,
        expected_total_rub=snapshot.total.expected,
        safe_total_rub=snapshot.total.safe,
        components=components,
        freshness_label=(
            f"Актуально до {snapshot.valid_until:%d.%m.%Y %H:%M}"
            if snapshot.valid_until
            else f"Рассчитано {snapshot.calculated_at:%d.%m.%Y %H:%M}"
        ),
        warnings=list(snapshot.warnings),
    )


def unavailable_pricing(request: TravelRequest) -> PricingCardView:
    timing = (
        "Даты известны, но"
        if (request.date_from and request.date_to)
        or (request.flight_departure_date and request.flight_return_date)
        else "Для выбранного периода"
    )
    return PricingCardView(
        status="unavailable",
        headline="Нужны live-цены",
        subtitle=f"{timing} не подключены подтверждённые цены перелёта и жилья.",
        components=[
            PricingComponentView(
                component="flight",
                label="Перелёт",
                status="missing",
                reason="Не подключён live provider авиабилетов.",
            ),
            PricingComponentView(
                component="stay",
                label="Жильё",
                status="missing",
                reason="Не подключён live provider проживания.",
            ),
        ],
        freshness_label="Demo-оценка не подставляется",
        warnings=["Без live перелёта и жилья полный бюджет не рассчитывается."],
    )


def cached_flight_card(
    signal: FlightPriceSignal | tuple[FlightPriceSignal, ...],
) -> PricingCardView:
    """Present a cached route/date observation without calling it a live or total price."""

    signals = signal if isinstance(signal, tuple) else (signal,)
    best = min(signals, key=lambda item: item.amount_rub)
    amount = int(best.amount_rub)
    maximum = int(max(item.amount_rub for item in signals))
    route = f"{best.origin_iata} → {best.destination_iata}"
    airline = f" · {best.airline}" if best.airline else ""
    return PricingCardView(
        status="partial",
        headline=(
            f"Перелёт: от {amount:,} до {maximum:,} ₽"
            if len(signals) > 1
            else f"Перелёт: ≈ {amount:,} ₽"
        ).replace(",", " "),
        subtitle=(
            f"{route}{airline} · цена найдена ранее и проверяется при переходе. "
            "Это не live-цена и не полный бюджет поездки."
        ),
        components=[
            PricingComponentView(
                component="flight",
                label="Перелёт · кэш Aviasales",
                status="partial",
                floor_rub=amount,
                expected_rub=amount,
                safe_rub=maximum,
                reason=(
                    "Найдено по поискам Aviasales; доступность и итоговая цена "
                    "проверяются при переходе."
                ),
            ),
            PricingComponentView(
                component="stay",
                label="Жильё",
                status="missing",
                reason="Источник цен жилья пока не подключён.",
            ),
        ],
        freshness_label=(
            (
                f"Найдено {best.age_hours} ч назад"
                if best.age_hours is not None
                else "Время исходного поиска API не передаёт"
            )
            + (
                f" · источник: cached · {len(signals)} сценариев"
                f" · уверенность {round(best.confidence * 100)}%"
            )
        ),
        warnings=[
            "Кэшированный перелёт не подтверждает наличие, состав пассажиров или полный бюджет.",
        ],
    )


def _component_view(component: CostComponent) -> PricingComponentView:
    group, label = COMPONENTS[component.name]
    return PricingComponentView(
        component=group,
        label=label,
        status=component.status,
        floor_rub=component.amount.floor if component.amount else None,
        expected_rub=component.amount.expected if component.amount else None,
        safe_rub=component.amount.safe if component.amount else None,
        reason=(component.warnings or component.assumptions or (None,))[0],
    )
