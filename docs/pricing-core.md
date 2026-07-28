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
