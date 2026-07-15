# Istanbul places pipeline

Статус: первый повторяемый vertical slice. Город — Стамбул, целевой объём одного прогона — 100–300
опубликованных туристических POI.

## Границы

- Source первого среза — OpenStreetMap через Overpass, только named tourist POI в фиксированном
  Istanbul bbox. Лицензия ODbL и атрибуция хранятся вместе с source record.
- Overture, Wikidata, Wikivoyage и Wikimedia Commons предусмотрены моделью provenance (`sources`,
  `place_source_records`, snapshots, images), но их adapters не включены в этот bounded slice.
- Платные API, scraping Google/Tripadvisor/Yandex/2GIS, отдельная vector DB, Kafka и глобальный
  каталог не используются.

## Стадии

1. Download: `scripts/import_istanbul_places.py --fetch` получает snapshot и записывает raw JSON
   с SHA-256 checksum.
2. Staging/normalization: отсеиваются POI без имени, координат или mapping в малую taxonomy.
3. Mapping/entity resolution: сначала совпадение `source + external_id`, затем exact normalized name
   в пределах 120 м. Неуверенные fuzzy merges намеренно не выполняются автоматически.
4. Enrichment/features: категории дают прозрачные rule-based tags, признаки качества и Commons image
   только при явном `wikimedia_commons` теге.
5. Embeddings/publish: локальный deterministic `hash-v1` vector длиной 64, затем status `active`.
6. Quality: `make places-eval-istanbul` исполняет 30 фиксированных queries и считает top-5 category
   recall. Это регрессионный индикатор, не заявка на relevance benchmark.

## Поиск и ранжирование

`POST /places/search` поддерживает destination, categories include/exclude, free/budget, indoor,
geospatial radius, duration и accessibility flags. Retrieval смешивает cosine similarity pgvector,
name lexical signal и `place_features`; затем применяет category diversity (не более двух мест одной
категории, пока не достигнут limit). Response возвращает `retrieval_id`, component scores,
ranking version, freshness и image attribution.

## Операционные команды

```bash
make places-up
make places-migrate
make places-import-istanbul
make places-eval-istanbul
```

Перед фактическим импортом нужны Docker daemon и сетевой доступ к Overpass. Если база не
сконфигурирована, endpoint возвращает 503. Это намеренно: UI/API не должны выдавать фиктивные
live-места.
