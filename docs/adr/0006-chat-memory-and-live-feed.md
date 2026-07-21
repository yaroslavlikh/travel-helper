# ADR-0006: Thread memory with a live recommendation feed

- Status: accepted for MVP
- Date: 2026-07-14

## Context

Пользователь выбирает направление итеративно: сначала описывает поездку, затем меняет бюджет,
визовые ограничения, погоду или длительность перелёта. Одноразовая форма и новая выдача под
каждым ответом не отражают этот процесс и быстро создают несколько противоречивых shortlist.

## Decision

Интерфейс состоит из двух связанных областей:

- chat thread хранит сообщения, заданные вопросы, ответы и краткие объяснения изменений;
- live feed показывает только текущую версию TravelRequest и актуальный ranked shortlist.

Каждое новое сообщение в существующем thread интерпретируется как patch к подтверждённому
TravelRequest. Неизвестные поля не затирают известные. Явная просьба убрать ограничение хранится
отдельно от отсутствующего значения. После patch повторно выполняются ambiguity rules, hard
filters и deterministic scoring.

LangGraph checkpoint является backend memory критериев, questions и turn history. Для local/dev
используется Async SQLite checkpointer; production target остаётся PostgreSQL. Браузер хранит
presentation history и последний feed в `localStorage`, чтобы мгновенно восстанавливать несколько
анонимных чатов. Это не cross-device account storage.

На desktop пользователь может свернуть боковую историю в компактную панель. Это отдельная локальная
UI-настройка и не меняет список чатов, active thread или backend memory.

При первом входе без сохранённых чатов UI автоматически создаёт пустой chat. Пользователь может
создать новый chat вручную; новый thread не наследует критерии предыдущего.

## Visual content boundary

Карточка показывает конкретный город/регион, реальные фотографии с source/credit, примеры районов
и достопримечательностей, а также ссылки на внешний поиск проживания и активностей. В demo mode
эти ссылки являются navigation examples, не подтверждают наличие или цену и явно маркируются.
LLM не придумывает отели, туры, изображения или availability.

## Consequences

- Уточнения меняют существующую ленту, а не создают независимую выдачу.
- Questions остаются в transcript после ответа и помечаются решёнными.
- Frontend вычисляет и показывает понятный diff: добавленные, удалённые и перемещённые варианты.
- Потеря `localStorage` удаляет только локальное представление списка чатов; backend thread memory
  живёт в checkpointer в рамках retention policy.
- До public beta нужны server-side chat index, retention/delete API и PostgreSQL.

## Rejected alternatives

- Хранить всё только в DOM: история пропадает при reload.
- Передавать всю историю в каждый prompt: растут latency, privacy risk и вероятность drift.
- Дублировать полные recommendation cards в каждом сообщении: пользователь видит устаревшие
  версии вместо одного актуального shortlist.
