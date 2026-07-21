# Методика рейтинга направлений

Статус: действующая методика `ranking-v1`. Реализация: `app/services/scoring.py`; все
параметры: `app/data/scoring.json`. Ranking не использует LLM для фактов, score или порядка.

## Последовательность

1. Из запроса извлекаются структурированные условия. LLM может участвовать только в extraction.
2. Для каждого кандидата детерминированно вычисляются hard checks.
3. Считаются шесть компонентов, каждый от 0 до 100, затем uncertainty и caps.
4. Допущенные кандидаты сортируются стабильно; diversity может менять порядок только среди
   вариантов не хуже чем на `score_gap` от лидера.
5. Внешние affiliate-ссылки, CTA, изображение и их позиции не участвуют в фильтрации или score.

## Шесть компонентов

| Компонент | Вес | Prior при отсутствии evidence |
| --- | ---: | ---: |
| Бюджет | 28 | 30 |
| Experience fit | 22 | 50 |
| Логистика | 18 | 40 |
| Погода | 14 | 45 |
| Въезд | 8 | 30 |
| Practical fit | 10 | 50 |

`effective = confidence × observed + (1 − confidence) × prior`.
Итог — сумма `effective × weight`, минус uncertainty. Отсутствующая величина не исключает её
вес: она получает объявленный prior и увеличивает uncertainty. В `scoring.json` uncertainty имеет
multiplier `10` и cap `15`; низкий budget/entry/logistics fit ограничивается caps `55/60/55`.

Experience fit — `(positive matches + avoided non-matches) / all stated tag conditions`.
В `positive` одинаково входят preferences, trip_style и priorities. Поэтому запрос только
«не хочу море» повышает неморской вариант и снижает морской.

## Hard checks

Отсутствующее пользовательское ограничение не создаёт check. Если ограничение есть, но evidence
отсутствует, результат `UNKNOWN`, а не pass.

| Ограничение | PASS | FAIL | UNKNOWN / NOT_APPLICABLE |
| --- | --- | --- | --- |
| Strict budget | known maximum не выше бюджета | minimum выше бюджета или known maximum выше бюджета | maximum неизвестен — `UNKNOWN` (включая неизвестный minimum) |
| Максимальный перелёт | known duration в лимите | known duration выше лимита | duration отсутствует — `UNKNOWN` |
| Температурный лимит | known temperature в лимите | known temperature выше лимита | temperature отсутствует — `UNKNOWN` |
| `no_visa` | только `none` | `evisa` или `visa` | `unknown` — `UNKNOWN` |
| `evisa_ok` | `none` или `evisa` | `visa` | `unknown` — `UNKNOWN` |
| `visa_ok` | любой known режим (`none`, `evisa`, `visa`) | — | `unknown` — `UNKNOWN` |
| `any` | — | — | `NOT_APPLICABLE`: визовый режим не ограничивает shortlist |
| Scope, море, регион, явное исключение | evidence соответствует | известное противоречие | Не создаются без такого ограничения |

`FAIL` исключает вариант. `UNKNOWN` для длительности и температуры делает карточку
`CONDITIONAL` с понятной причиной. `UNKNOWN` strict budget или visa не подтверждает обязательное
условие и исключает вариант из обычной выдачи.

Поддерживаемая география сознательно ограничена явными aliases и country sets: Азия, Европа,
Ближний Восток, Россия/внутренние направления. Произвольные названия стран и регионов не
сопоставляются substring-поиском и не считаются выполненным hard constraint.

## Fallback и diversity

Если нормальная выдача пуста, fallback может ослабить **только** strict budget. В него попадает
кандидат со `strict_budget=FAIL`, когда каждый другой применимый hard check равен `PASS` или
`NOT_APPLICABLE`. `UNKNOWN`/`FAIL` визы, региона, температуры, перелёта и прочих условий
fallback запрещает. Предыдущие risks/cons сохраняются и дополняются понятным бюджетным
предупреждением.

Diversity работает после стабильной сортировки: только внутри 12 баллов от лидера, штрафует
сходство на 8 баллов и держит не более двух направлений из одной страны, пока доступен другой
кандидат. `rank_before_diversity` и `rank_after_diversity` сохраняются для проверки эффекта.

## Ограничения v1

Это ranking над demo fixture, а не live pricing, availability, погодой или визовыми правилами.
Все оценки в карточке — modelled evidence, не гарантия покупки. Живой каталог мест Стамбула
использует отдельный hybrid ranking: [places pipeline](places-pipeline.md).
