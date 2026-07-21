# Destination context and Istanbul POI expansion

Статус: реализован Stage 1 для Стамбула. Другие направления не подключены.

## Контекст направления

`app/places/context.py` отделяет стабильный контекст от динамических фактов. Для Стамбула в
контекст входят географические зоны (Султанахмет, Галата/Каракёй, Бешикташ/Босфор), районы
проживания, форматы поездки и категории каталога. Эти сведения имеют source URL и время записи.

Въезд, текущие цены, расписания, погода и availability не заполняются из POI-каталога. Пока у них
нет отдельного подтверждённого snapshot, в контексте передаётся `unknown` warning. Subchat получает
не более одного destination context, текущую карточку, bounded history и top-5 POI; полный каталог
и raw Overpass payload в prompt не попадают.

## POI quality policy

Импорт сначала валидирует весь ответ Overpass: имя, координаты, явную tourist-taxonomy и уникальный
`source + external_id`. Затем сортирует кандидатов независимо от порядка ответа:

- прозрачный вес категории;
- Wikidata/Wikipedia/Commons references;
- число multilingual `name:*` aliases;
- полезные OSM tags (website, hours, heritage, image и т. п.);
- штраф за подозрительно generic name.

Это не popularity score. Случайные магазины, рестораны, отели и ночные клубы не входят в source
scope. Сейчас команда принимает 100–300 лучших записей; проверенный snapshot дал 250 accepted POI.

## Identity, merge и lifecycle

`source_id + external_id` — основная идентичность. Новый OSM record может присоединиться к
канонической сущности только при exact normalized name и расстоянии до 120 м. Fuzzy merge не
делается; сомнительные совпадения остаются разными записями до ручного review.

После каждого полного snapshot source records, которых в нём нет, получают `deleted_at`; place без
текущего source record становится `inactive`. История source snapshots остаётся в базе. Повторный
импорт идентичного snapshot идемпотентен.

## Retrieval и eval

`hash-v1` хранится только для совместимости schema и **не используется как semantic embedding**.
Онлайн-поиск — честный lexical/category/geospatial baseline: multilingual OSM aliases, русские
category hints и несколько явно заданных Istanbul area hints. Категории диверсифицируются в top-K.

Независимый набор `data/evals/istanbul_places_queries.json` содержит 40 русскоязычных кейсов:
конкретные POI, категории, районы, семья, indoor, outdoor, отрицательные категории и склонения.
На локальном snapshot 2026-07-21: category recall@5 — 0.90, exact-name recall@5 — 1.00 на трёх
named checks, overall passed recall — 0.90. Ошибки baseline: «не туристическое место», «вид на
Босфор», «современное искусство», «место у воды». Это ограничения каталога/lexical baseline, а не
скрытая semantic promise.

## Команды

```bash
make places-up
make places-migrate
PLACES_DATABASE_URL=postgresql://travel:travel@127.0.0.1:5433/travel_places \
  python3 -m uv run python scripts/import_istanbul_places.py --input data/raw/istanbul/<snapshot>.json
PLACES_DATABASE_URL=postgresql://travel:travel@127.0.0.1:5433/travel_places \
  make places-eval-istanbul
PLACES_DATABASE_URL=postgresql://travel:travel@127.0.0.1:5433/travel_places \
  python3 -m uv run pytest tests/integration/test_places_postgres.py
```
