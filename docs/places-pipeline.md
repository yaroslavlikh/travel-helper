# Places catalog pipeline

Статус: один повторяемый pipeline для 26 направлений из продуктового каталога. Стамбул остаётся
первым полностью проверенным vertical slice; целевой объём одного прогона — 100–300 опубликованных
туристических POI на направление.

## Границы

- Source — OpenStreetMap через Overpass, только named tourist POI в versioned bounded bbox каждого
  направления. Лицензия ODbL и атрибуция хранятся вместе с source record.
- Overture, Wikidata, Wikivoyage и Wikimedia Commons предусмотрены моделью provenance (`sources`,
  `place_source_records`, snapshots, images), но их adapters не включены в этот bounded slice.
- Платные API, scraping Google/Tripadvisor/Yandex/2GIS, отдельная vector DB, Kafka и глобальный
  каталог не используются.
- Короткое описание POI принимается только из reviewed manifest с явно записанными правами на
  хранение, embeddings и показ excerpt. Публичная статья сама по себе таким разрешением не является;
  детали — в [ADR-0010](adr/0010-provenance-preserving-poi-descriptions.md).

## Стадии

1. Download: `scripts/import_istanbul_places.py --fetch --destination phuket` получает snapshot и записывает raw JSON
   с SHA-256 checksum.
2. Staging/normalization: отсеиваются POI без имени, координат или mapping в малую taxonomy.
3. Quality selection: после нормализации **всего** snapshot кандидаты ранжируются по прозрачным
   OSM quality signals и только затем ограничиваются 100–300 местами.
4. Mapping/entity resolution: сначала совпадение `source + external_id`, затем exact normalized name
   в пределах 120 м. Неуверенные fuzzy merges намеренно не выполняются автоматически.
5. Enrichment/features: категории дают прозрачные rule-based tags, признаки качества и Commons image
   только при явном `wikimedia_commons` теге.
6. Publish/lifecycle: `hash-v1` vector длиной 64 сохраняется только для schema compatibility;
   отсутствующие в новом полном snapshot source records становятся stale, а place без актуального
   source становится `inactive`.
7. Quality: `make places-eval-istanbul` исполняет независимые 40 queries, считает category/name
   recall и печатает top-K errors. Это baseline, не заявка на semantic relevance benchmark.

## Поиск и ранжирование

`POST /places/search` поддерживает destination, categories include/exclude, free/budget, indoor,
geospatial radius, duration и accessibility flags. Retrieval использует lexical aliases, explicit
category/area hints и `place_features`; `hash-v1` не выдаётся за semantic similarity. Затем
применяется category diversity (не более двух мест одной
категории, пока не достигнут limit). Response возвращает `retrieval_id`, component scores,
ranking version, freshness, image attribution и provenance основного source record. В subchat
этот же bounded retrieval вызывает только POI-вопросы и отдаёт не более пяти мест. До первого
успешного импорта конкретного направления UI честно сообщает, что каталог наполняется.
Для каждого места может вернуться одно активное, не просроченное, атрибутированное описание. В
subchat в prompt попадает только короткий excerpt уже отобранных результатов, а не весь каталог.

## Операционные команды

```bash
make places-up
make places-migrate
make places-import-istanbul
make places-import-all
make places-import-descriptions DESCRIPTIONS_INPUT=path/to/reviewed-manifest.json
make places-eval-istanbul
```

Перед фактическим импортом нужны Docker daemon и сетевой доступ к Overpass. Если база не
сконфигурирована, endpoint возвращает 503. Это намеренно: UI/API не должны выдавать фиктивные
live-места.
