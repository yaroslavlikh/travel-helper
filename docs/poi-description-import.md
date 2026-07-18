# Импорт описаний POI

Этот путь добавляет к уже импортированному OSM-месту короткое атрибутированное описание для
bounded retrieval. Он намеренно не скачивает страницы и не обходит сайты: оператор сам передаёт
проверенный JSON manifest после проверки лицензии или прямого разрешения автора.

## До импорта

1. Применить миграции и импортировать OSM-каталог Стамбула.
2. Убедиться, что правообладатель разрешил три независимые операции: хранить текст, строить его
   embeddings и показывать короткий excerpt с атрибуцией.
3. Сопоставить документ со стабильным `place_osm_external_id` из уже загруженного OSM record.
   Не сопоставлять только по имени: одно имя может относиться к нескольким местам.
4. Задать `observed_at` с часовым поясом. Для изменяемого контента задать `valid_until`; после этой
   даты описание не попадёт ни в UI, ни в RAG retrieval.

## Manifest

```json
{
  "schema_version": 1,
  "destination": "istanbul",
  "source": {
    "slug": "partner-istanbul-guide",
    "name": "Partner Istanbul Guide",
    "license": "Direct partner permission dated 2026-07-18",
    "attribution": "© Partner Istanbul Guide",
    "base_url": "https://example.org/",
    "usage_policy": {
      "may_store_text": true,
      "may_embed_text": true,
      "may_display_excerpt": true,
      "requires_attribution": true,
      "reviewed_at": "2026-07-18T10:00:00+00:00",
      "review_note": "Agreement explicitly covers bounded storage, embeddings and attributed excerpts."
    }
  },
  "documents": [
    {
      "source_external_id": "stable-id-in-partner-system",
      "source_url": "https://example.org/istanbul/place",
      "place_osm_external_id": "way/123456",
      "language_code": "ru",
      "content_kind": "overview",
      "text": "Короткое проверенное описание от 80 до 1600 символов.",
      "observed_at": "2026-07-18T10:00:00+00:00",
      "valid_until": "2027-07-18T10:00:00+00:00"
    }
  ]
}
```

`content_kind` принимает `overview`, `practical` или `editorial`. Один `source_external_id` можно
передать только один раз в manifest; это исключает случайное перемещение одного документа между
разными POI.

## Запуск и результат

```bash
make places-import-descriptions DESCRIPTIONS_INPUT=path/to/reviewed-manifest.json
```

Скрипт выводит только агрегированный report: число принятых, обновлённых, неизменённых,
просроченных и отклонённых записей. Текст описаний и другие неограниченные данные в лог не
попадают. Повторный импорт того же текста не пересоздаёт chunks; изменённый текст создаёт новый
source snapshot и заново индексирует только свои chunks.
Если существующий `source_external_id` в новом manifest указывает на другой POI, запись будет
отклонена с причиной `source_external_id_is_bound_to_another_place`, а не будет незаметно
перепривязана.

Основным источником самого POI остаётся OpenStreetMap record; источник описания передаётся
отдельно и не заменяет географическую provenance места.

## Использование Дзена и блогов

Статья на публичной площадке не считается разрешением на импорт. Использовать автора Дзена можно
только при записанном согласии, которое явно разрешает storage, embeddings и attributed excerpts;
это согласие и формат атрибуции фиксируются в `usage_policy`. Без такого основания можно хранить
ссылку как материал для редакторской проверки, но не текст и не его embedding.
