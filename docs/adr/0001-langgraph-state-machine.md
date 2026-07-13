# ADR-0001: LangGraph as a deterministic state machine

- Status: proposed
- Date: 2026-07-13

## Context

Pipeline ветвится на clarification, должен сохранять состояние между HTTP calls, продолжаться после ответа и переживать частичный отказ внешних источников. При этом продукт не должен становиться multi-agent или автономным planner.

## Decision

Использовать LangGraph `StateGraph` как orchestration layer. Топология и conditional routes задаются кодом; LLM не выбирает произвольный следующий tool/node. Clarification реализуется через checkpointer + interrupt/resume.

## Consequences

Плюсы: явное сериализуемое состояние, встроенный resume, наблюдаемые stage boundaries, удобные fault-recovery tests. Минусы: дополнительная зависимость, schema migrations graph state и необходимость идемпотентных side effects из-за replay semantics.

## Rejected alternatives

- Одна длинная FastAPI service-функция: проще сначала, но clarification state и resume быстро станут самодельным workflow engine.
- Autonomous/ReAct agent: непредсказуемый control flow и слабее гарантия детерминированных фильтров.
- Multi-agent: не оправдан scope и стоимостью MVP.
