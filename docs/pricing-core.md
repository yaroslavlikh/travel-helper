# Deterministic pricing core

Статус: реализуется как отдельный bounded context; в UI пока не подключён.

`app/pricing` принимает только типизированный `PricingRequest`. Свободный текст, LLM extraction,
LangGraph и embeddings находятся за границей модуля. Внутри разрешены структурированные provider
observations, versioned config, `Decimal` и фиксированные правила.

Первый этап реализует:

- валидацию exact/window/month запросов;
- цельные `DateScenario`, где перелёт и жильё обязаны относиться к одним датам;
- детерминированное ограничение большого окна;
- расчёт полного сценария без подстановки нулей за отсутствующие компоненты;
- агрегацию дешёвой корзины полных сценариев в `floor/expected/safe`;
- immutable snapshot, стабильные hash/ID и явные warnings;
- AST-проверку отсутствия AI-импортов.

FX-этап ([ADR-0019](adr/0019-cbr-fx-rates.md)) добавляет официальный XML adapter Банка России,
`Decimal`-конвертацию с учётом `Nominal`
и process-local cache. Валидный курс кэшируется на 24 часа; при отказе источника допускается явно
помеченный fallback не старше 72 часов. Валюта, отсутствующая в таблице ЦБ, остаётся unsupported до
отдельного cross-rate adapter.

Flight/stay providers, хранилище snapshots и HTTP API появятся отдельными этапами. До подключения
подтверждённых flight и stay sources `total` пользователю не показывается.

Aviasales Data API используется только для cached date discovery
([ADR-0020](adr/0020-aviasales-cached-date-signals.md)). Сигнал всегда помечен
`usable_for_total=false`: endpoint не получает точный состав группы и не подтверждает live
availability.

Live flight providers должны нормализоваться в единый `FlightOffer`
([ADR-0021](adr/0021-live-flight-normalization.md)). До расчёта компонента проверяются точные даты,
состав группы, налоги, baggage, stops/duration, self-transfer, expiry, dedupe и bait-price. Сам
adapter Amadeus и revalidation будут подключены после конфигурации credentials.

Жильё следует тому же принципу: `StayOffer` обязан содержать full-party/full-stay total, exact
dates, occupancy, rooms и подтверждение полноты mandatory charges. Исключённые из provider total
обязательные сборы добавляются один раз. Профильные правила передаются типизированно, а не
зашиваются одной «средней ценой» на город
([ADR-0022](adr/0022-live-stay-normalization.md)).

Расходы на еду и городской транспорт также считаются без LLM
([ADR-0023](adr/0023-deterministic-daily-costs.md)). Еда строится из versioned fixed basket и
возрастных коэффициентов; городской транспорт — из официальных разовых/day/weekly тарифов. Если
детский тариф или обязательный элемент профиля неизвестен, компонент становится `missing`, а не
нулём.
