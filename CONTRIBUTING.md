# Contributing

Этот документ задаёт обязательный developer workflow. Конкретные инструменты могут меняться через ADR или отдельный tooling commit, но публичные команды и правила истории сохраняются.

## Единый интерфейс команд

Корневой `Makefile` self-documenting: `make help` показывает доступные цели и короткие описания. Make targets являются тонкими aliases над `uv`/tool commands и одинаково работают локально и в CI.

Обязательный контракт:

| Target | Назначение | Меняет файлы |
|---|---|---|
| `make help` | Показать команды | Нет |
| `make bootstrap` | Установить locked dependencies и dev tools | Только environment |
| `make run` | Запустить production-like app локально | Нет |
| `make dev` | Запустить app с reload для разработки | Нет |
| `make format` | Применить formatter/autofix | Да |
| `make format-check` | Проверить формат без изменения файлов | Нет |
| `make lint` | Статический lint без autofix | Нет |
| `make typecheck` | Проверить типы | Нет |
| `make test` | Запустить полный network-independent test suite | Нет, кроме ignored artifacts |
| `make test-unit` | Быстрые unit tests | Нет, кроме ignored artifacts |
| `make test-integration` | Integration tests с mocked external I/O | Нет, кроме ignored artifacts |
| `make docs-check` | Проверить Markdown и локальные ссылки | Нет |
| `make check` | Все обязательные немутирующие quality gates | Нет |
| `make clean` | Удалить только генерируемые локальные artifacts | Да |

`make check` обязан включать как минимум `format-check`, `lint`, `typecheck`, `test` и `docs-check`. Он не должен скачивать незалоченные зависимости, ходить во внешние API или исправлять файлы. CI вызывает `make check`, а не дублирует внутренние команды в YAML.

## Ожидаемый цикл изменения

1. Убедиться, что рабочее дерево не содержит чужих незавершённых изменений.
2. Обновить затронутый контракт/ADR до кода, если меняется решение.
3. Реализовать одну смысловую единицу вместе с релевантными тестами и документацией.
4. Запустить быстрые релевантные проверки во время работы.
5. Запустить `make check` перед push. До появления Makefile docs-only изменения проверяются через `git diff --check` и ручную проверку локальных ссылок.
6. Создать атомарный Conventional Commit.
7. Проверить чистое рабочее дерево и опубликовать commit.

Не нужно создавать commit после каждого файла. Commit создаётся после каждой законченной feature/fix/refactor или самостоятельного изменения tests/docs/tooling. Нельзя смешивать несвязанные изменения только ради меньшего числа commits.

## Conventional Commits

Формат заголовка:

```text
<type>(optional-scope): short imperative description
```

Допустимые основные types:

- `feat`: новое пользовательское или API-поведение;
- `fix`: исправление дефекта;
- `refactor`: изменение структуры без изменения поведения;
- `test`: самостоятельное добавление или переработка тестов;
- `docs`: документация без изменения runtime behavior;
- `build`: dependencies, packaging, Makefile и build system;
- `ci`: CI/CD workflows;
- `chore`: обслуживание, не подходящее под остальные types;
- `perf`: измеримое улучшение производительности;
- `revert`: явный откат commit.

Примеры:

```text
feat(graph): add clarification interrupt and resume
fix(scoring): exclude unavailable weather component
refactor(providers): extract shared timeout policy
test(api): cover partial response after weather failure
docs: record model provider evaluation criteria
build: add Makefile quality targets
ci: run make check on pull requests
```

Заголовок описывает результат, а не процесс: избегать `updates`, `changes`, `wip`, `misc`. Для breaking change использовать `!` и footer `BREAKING CHANGE:`. Ссылка на issue допустима в body/footer, но не заменяет понятный заголовок.

## Atomicity rules

- Feature commit включает необходимые для неё tests и обновление пользовательского/технического контракта: это одна завершённая единица.
- Отдельный `test:` commit используется, когда меняется только test coverage/infrastructure без runtime behavior.
- `refactor:` должен сохранять поведение и проходить существующие tests; изменение поведения оформляется `feat:` или `fix:`.
- Tooling, dependency и CI изменения не прячутся внутри feature commit, если они применимы ко всему проекту.
- Не коммитить secrets, `.env`, local databases, caches, coverage и generated output.
- Не использовать `--no-verify` для обхода падающих проверок. Исправить причину или явно задокументировать блокер.

## Pull requests и main

Пока проект ведётся напрямую в `main`, каждый опубликованный commit всё равно должен быть атомарным и проходить quality gate. Перед подключением дополнительных участников или public beta следует включить protected `main` и обязательную CI-проверку; после этого features выполняются в короткоживущих ветках и попадают в `main` через review.
