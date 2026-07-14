# ADR-0008: Aviasales deeplink contract

- Status: accepted for MVP
- Date: 2026-07-15

## Context

Карточка направления должна передавать пользователя в Aviasales, не превращая ориентировочный
период поездки в выдуманную пару билетов. Проверка compact search path и query-string deeplink
показала нестабильное заполнение дат в разных браузерных контекстах. Для MVP надёжно подтверждён
только route page вида `/routes/mow/aer`, который передаёт маршрут и оставляет выбор дат Aviasales.

Route page Aviasales ожидает IATA-коды маршрута и, при наличии, партнёрский `marker`. Ссылка
является navigation handoff и не подтверждает цену или наличие.

## Decision

### Два разных контракта дат

- `date_from`, `date_to` описывают точные границы поездки: вылет и возвращение;
- `departure_window_from`, `departure_window_to` описывают диапазон возможных дат вылета, но не
  возвращение;
- `month` описывает только месяц;
- `flight_departure_date`, `flight_return_date` временно сохраняются только для совместимости с
  уже записанными local checkpoints;
- `flight_one_way=true` устанавливается только по прямому указанию пользователя.

Фраза «с 15 по 20 октября» означает точную поездку. Фраза «могу вылететь 15 или 16 октября»
означает departure window. Изменение примерного периода очищает точные даты, а точное уточнение
очищает месяц и departure window.

### Provider handoff

Aviasales URL собирается в backend routing-сервисе и передаётся frontend как `external_link`
категории `flight`. Frontend не знает provider parameters, не передаёт даты и не обещает
предзаполненный поиск.

Routing использует один контракт для любых дат и состава путешественников:

- при известных origin и destination IATA: `/routes/{origin}/{destination}`;
- optional `marker` из `AVIASALES_MARKER` остаётся query-параметром;
- если хотя бы один IATA неизвестен, используется главная форма Aviasales без выдуманного маршрута.

Даже подтверждённые точные даты полностью отсутствуют в deeplink. Пользователь выбирает их через
нативный календарь Aviasales. Date extraction продолжает работать для рекомендаций и памяти чата,
но временно не участвует во внешнем routing-контракте.

## Consequences

- Точная поездка и гибкое окно открывают одну route page с корректными городами.
- Карточка и Aviasales не расходятся из-за частично распознанных дат.
- Генерация ссылки стала детерминированной и покрывается unit tests вне browser UI.
- Для расширения географии потребуется IATA resolver/provider вместо ограниченного словаря городов.
- Для affiliate attribution достаточно настроить marker без изменения frontend.
- Поиск цен по диапазону дат остаётся отдельным flight-provider slice.

## Rejected alternatives

- Compact search URL: даты заполняются нестабильно в разных браузерных контекстах.
- Вычислять случайную дату внутри месяца: создаёт неподтверждённую точность.
- Считать конец departure window датой обратного билета: смешивает разные пользовательские intents.
- Собирать URL в браузере: provider contract остаётся непроверяемой частью presentation layer.
- Подставлять Москву при неизвестном origin: квалифицированный переход становится фактически
  неверным.

## References

- [Пример compact search URL](https://www.aviasales.ru/search/MOW1510AER20101)
- [Партнёрские ссылки на Aviasales](https://support.travelpayouts.com/hc/ru/articles/5711895629714-%D0%9F%D0%B0%D1%80%D1%82%D0%BD%D1%91%D1%80%D1%81%D0%BA%D0%B8%D0%B5-%D1%81%D1%81%D1%8B%D0%BB%D0%BA%D0%B8-%D0%BD%D0%B0-Aviasales)
- [Как работают сайт и приложение Aviasales](https://www.aviasales.ru/faq/kak-najti-i-kupit-samye-deshevye-aviabilety?opened_from=faq_main)
- [ADR-0007: Destination subthreads and commerce routing](0007-destination-subthreads-and-commerce-routing.md)
