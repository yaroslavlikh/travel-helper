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

Провайдеры, FX, хранилище snapshots и HTTP API появятся отдельными этапами. До подключения
подтверждённых flight и stay sources `total` пользователю не показывается.
