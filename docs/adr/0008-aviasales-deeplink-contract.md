# ADR-0008: Aviasales deeplink contract

- Status: accepted for MVP
- Date: 2026-07-15

## Context

Карточка направления должна передавать пользователя в Aviasales, не превращая ориентировочный
период поездки в выдуманную пару билетов. Live web flow Aviasales после поиска использует compact
path вида `/search/MOW1510AER20101`: origin, дата вылета `DDMM`, destination, дата возвращения
`DDMM` и количество взрослых. Документированный query-string контракт не является каноническим
URL текущего web UI и не заполняет форму стабильно.

Публичный контракт Aviasales также ожидает IATA-коды маршрута, пассажиров и, при наличии,
партнёрский `marker`. Ссылка является navigation handoff и не подтверждает цену или наличие.

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
категории `flight`. Frontend не знает provider parameters и не выводит даты из планировочного
диапазона.

Routing использует:

- точная поездка без детей/младенцев: `/search/{ORIGIN}{DDMM}{DEST}{DDMM_BACK}{ADULTS}`;
- подтверждённый one-way: `/search/{ORIGIN}{DDMM}{DEST}{ADULTS}`;
- месяц, гибкое окно или неподтверждённый family suffix: `/routes/{origin}/{destination}`;
- optional `marker` из `AVIASALES_MARKER` остаётся query-параметром.

Если известен лишь месяц или диапазон, даты полностью отсутствуют в deeplink. Пользователь выбирает
их через нативный календарь Aviasales, включая режим «Гибкие даты». Детей и младенцев пока не
кодируем в compact path без подтверждённого provider-контракта: family request открывает route page.
Если origin нельзя безопасно сопоставить с IATA, открывается главная форма без маршрута.

## Consequences

- Точная поездка `15–20 октября` открывает `/search/MOW1510AER20101`.
- Окно вылета `15–16 августа` открывает route page и не выглядит как возврат 16 августа.
- Генерация ссылки стала детерминированной и покрывается unit tests вне browser UI.
- Для расширения географии потребуется IATA resolver/provider вместо бесконечного словаря городов.
- Для affiliate attribution достаточно настроить marker без изменения frontend.
- Поиск цен по диапазону дат остаётся отдельным flight-provider slice.

## Rejected alternatives

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
