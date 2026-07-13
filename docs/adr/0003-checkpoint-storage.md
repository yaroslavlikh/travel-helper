# ADR-0003: SQLite locally, PostgreSQL in production

- Status: proposed
- Date: 2026-07-13

## Context

LangGraph clarification требует durable thread checkpoints. Локальный запуск должен быть простым, публичный сервис — устойчивым к рестартам и concurrent writes.

## Decision

Использовать in-memory checkpointer в unit tests, Async SQLite checkpointer для local development и Async PostgreSQL checkpointer для public deployment. Anonymous session ID является LangGraph thread ID или однозначно на него отображается.

## Consequences

Local setup остаётся лёгким, production получает нормальную конкурентность и durable storage. Необходимы одинаковые contract tests на обеих реализациях и миграционная дисциплина state schema.

## Rejected alternatives

- In-memory в production: состояние теряется при рестарте.
- SQLite в public multi-worker deployment: хрупкая конкурентная запись и зависимость от локального диска.
- Redis сразу: дополнительная система без необходимости для целевой нагрузки.
