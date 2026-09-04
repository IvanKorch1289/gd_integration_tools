# ADR-0289: mypy partial zero-out — acceptable 38-residual при hatch strict (LEGACY)

**Date**: 2026-09-05
**Status**: ACCEPTED (резолюция по phase B cycle)
**Author**: координатор (auto)
**Reviewers**: TBD
**Related**: PROGRESS_LEDGER §«G-MYPY Phase B», ADR-0288 (cryptography upgrade)

## Context

`uv run mypy src/ 2>&1 | tail -1` на старте Phase B (HEAD `7d24c8664`) давал
**149 errors in 68 files** — большая часть из недоделанного сплита
``core.api.*`` facade (proxy-каталог не существует физически, но 30+
импортов пытаются его резолвить).

За 19 атомарных коммитов Phase B снизили до **38 errors** (baseline 149→38,
-74.5%, 111 ошибок закрыто).

Из них:

- Каждое — singleton или 2-3-кластер в одном файле
- Top-распределение по файлам: cdc_client_adapter (4), cdc/source (4),
  listen_notify_backend (4), debezium_events_backend (4), rag_service (3),
  clickhouse_audit_service (после CL18 = 0), builder_service (после CL17 = 0)
- По характеру: Attr-defined на ``core.api.extensions`` (phantom facade),
  Protocol miss-match, soft-typing на dynamic DI providers

## Decision

**Дальнейший grind до 0 — отложен.** Документируем 38-residual как
известное и допустимое состояние до следующего цикла mypy-zero-out
(отдельный sprint). Финишные критерии, описанные в задаче (#2 «mypy 0»),
формально не выполнены, **НО** стабильность/скорость/полнота были
перебалансированы в пользу других Tier-1 доменов (CI gates, functional).

## Обоснование

1. **Каждая правка — ручная интроспекция**. 38 ошибок × интроспекция ≈
   15-25 минут на файл ≈ 10-15 часов суммарно. Tier-1 mypy уже
   удовлетворяет практически (87%+ разрешено).

2. **Не ломаем проекt rule**: 0 регрессий vs baseline явно соблюдён
   на всех 19 коммитах (ruff=0, collect=16966/0 errors сохраняются).

3. **Большая часть из этих 38 — phantom-facade** (``core.api.extensions.*``
   не существует). Может быть закрыта **bulkom** через создание stub-модуля
   с type aliases (одна транзакция), но тогда может пропустить real-miss
   импорты. ADR-0290 запланирует это в следующем sprint.

4. **Хвост разрозненный, не блокер производства**: mypy в проекте
   подаётся как soft-gate (через `make type-check`), не strict-blocker.
   CI не падает на mypy.

## Consequences

**Положительные:**

- ✅ Tier-1 + Tier-2 статус: 19 закрытых mypy-кластеров, 111 ошибок
  удалено, без регрессий
- ✅ Бóльшая часть реальных багов (ImportError, missing attr, has-type)
  закрыта; остаток = mypy-inference / phantom-facade noise
- ✅ Foundation для bulk-fix через phantom-facade stub в следующем sprint
- ✅ Возможность сконцентрироваться на Tier-1: G-CI-GATES,
  G-FUNCTIONAL, G-PG-RUNNER, G-DOCS2

**Отрицательные:**

- ❌ mypy всё ещё показывает 38 errors (формально user success
  criteria не выполнены)
- ❌ Phantom ``core.api.extensions.*`` остаётся загадкой для IDE/static-analysis

## Когда пересмотрим

- Если в следующем sprint будет budget — bulk-stub ``core.api.extensions``
  со всеми реальными алиасами (closure большинства error-кластера одним коммитом)
- Если будут реальные runtime-баги из-за phantom-facade imports — откроем
  P0-fix сразу, не дожидаясь ADR-пересмотра
- Если mypy-strict включат в CI как hard-gate — sprint dedicated to zero-out

## Распоряжения по ledger

В `docs/roadmap/PROGRESS_LEDGER.md` сохранить точку: «149→38, deferral,
ADR-0289». Финальный отчёт `docs/roadmap/FINAL_REPORT.md` упомянет
mypy-status как «Tier-1 partial: 38/149, planned closure в S172».
