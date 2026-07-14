# ADR-0008: Aviasales deeplink contract

- Status: accepted for MVP
- Date: 2026-07-15

## Context

Карточка направления должна передавать пользователя в Aviasales, не превращая ориентировочный
период поездки в выдуманную пару билетов. Ранее frontend напрямую сопоставлял `date_from` с
`depart_date`, а `date_to` с `return_date`. Это неверно: в продукте эти поля могут описывать окно
возможного вылета, тогда как deeplink Aviasales принимает одну точную дату отправления и одну
точную дату возвращения.

Публичный контракт Aviasales также ожидает IATA-коды маршрута, пассажиров и, при наличии,
партнёрский `marker`. Ссылка является navigation handoff и не подтверждает цену или наличие.

## Decision

### Два разных контракта дат

- `month`, `date_from`, `date_to` описывают период выбора направления или примерное окно вылета;
- `flight_departure_date`, `flight_return_date` описывают только явно подтверждённые точные даты
  перелёта;
- `flight_one_way=true` устанавливается только по прямому указанию пользователя.

Изменение примерного периода очищает сохранённые точные flight dates. Явное уточнение точных дат
очищает примерный месяц/диапазон, чтобы один chat не хранил противоречивые значения.

### Provider handoff

Aviasales URL собирается в backend routing-сервисе и передаётся frontend как `external_link`
категории `flight`. Frontend не знает provider parameters и не выводит даты из планировочного
диапазона.

Ссылка передаёт:

- `origin_iata` и `destination_iata`, только когда оба значения известны;
- `depart_date`, `return_date` и `oneway=0` только для валидной подтверждённой пары;
- `depart_date` и `oneway=1` только для подтверждённого one-way запроса;
- `adults`, `children`, `infants`, `trip_class`, `currency`;
- optional `marker` из `AVIASALES_MARKER`.

Если известен лишь месяц или диапазон, даты полностью отсутствуют в deeplink. Пользователь выбирает
их через нативный календарь Aviasales, включая режим «Гибкие даты». Если origin нельзя безопасно
сопоставить с IATA, маршрут не предзаполняется: нельзя молча полагаться на provider default Москвы.

## Consequences

- Окно `15–16 августа` больше не выглядит как поездка с возвращением 16 августа.
- Генерация ссылки стала детерминированной и покрывается unit tests вне browser UI.
- Для расширения географии потребуется IATA resolver/provider вместо бесконечного словаря городов.
- Для affiliate attribution достаточно настроить marker без изменения frontend.
- Поиск цен по диапазону дат остаётся отдельным flight-provider slice.

## Rejected alternatives

- Вычислять случайную дату внутри месяца: создаёт неподтверждённую точность.
- Считать `date_to` датой обратного билета: смешивает окно вылета и границы поездки.
- Собирать URL в браузере: provider contract остаётся непроверяемой частью presentation layer.
- Подставлять Москву при неизвестном origin: квалифицированный переход становится фактически
  неверным.

## References

- [Партнёрские ссылки на Aviasales](https://support.travelpayouts.com/hc/ru/articles/5711895629714-%D0%9F%D0%B0%D1%80%D1%82%D0%BD%D1%91%D1%80%D1%81%D0%BA%D0%B8%D0%B5-%D1%81%D1%81%D1%8B%D0%BB%D0%BA%D0%B8-%D0%BD%D0%B0-Aviasales)
- [Как работают сайт и приложение Aviasales](https://www.aviasales.ru/faq/kak-najti-i-kupit-samye-deshevye-aviabilety?opened_from=faq_main)
- [ADR-0007: Destination subthreads and commerce routing](0007-destination-subthreads-and-commerce-routing.md)
