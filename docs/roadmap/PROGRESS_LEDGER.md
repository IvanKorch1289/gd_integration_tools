# PROGRESS_LEDGER — единый реестр задач (source of truth)

> **Создан**: 2026-09-04 (координатор роя). Правила:
> - Статусы: `TODO` → `IN_PROGRESS` → `DONE` (с командой-доказательством); регрессия в DONE → `REOPENED` (только эта задача возвращается в цикл).
> - DONE-задачи повторно не анализируются. Не доверять STATUS.md без прямой верификации командами.
> - Перед стартом любой фазы — читать файл целиком.
> - **WIP-ограничение**: 7 файлов в рабочем дереве изменены НЕ этим роем (pii_tokenizer*, web.py, routers.py, express.py, rate_limit_middleware.py, WIKI.md, uv.lock cryptography<51) — не трогать и не коммитить их; uv.lock = остаток закрытого M3-#4.

---

## Майлстоуны

| ID | Майлстоун | Статус | Дата | Доказательство (verified команда/коммит) |
|---|---|---|---|---|
| M1 | Security P0 zero-out | **DONE** | 2026-08-25 | commit `57a396d84` (22/22 P0 closed); bandit -lll: 0 HIGH (SWARM_SYNTHESIS §6, 2026-09-02) |
| M2 | Мёртвый код + god-objects + custom→library | **DONE** (кроме R1 ниже) | 2026-09-03 | Sprint 87: M2-#11 55/55 `55be1c339`; ретро `a05ad0106` |
| M3 | Актуализация зависимостей (CVE) | **DONE** | 2026-09-01 | Sprint 58 `a2ce9ce42`: cryptography 50.0.1 (PYSEC-2026-3552 закрыт), tornado 6.5.8, pypdf 6.16.2; diskcache deferral ADR-0287 |
| M4 | Coverage до 70% gate (критичные пути) | **IN_PROGRESS** | 2026-09-04 | core/auth 79.0% (≥70% ✓, Sprint 88 `3101e1a45`); overall 30.8% — НЕ достигнут; `pyproject.toml:fail_under=60` |
| M5 | High-load hardening (10 задач) | **TODO** | — | 0/10 (Sprint 88 ретро); план: PRODUCTION_READINESS_FINAL.md §M5 |
| M6 | Финальная верификация + закрытие плана | **TODO** | — | 0/N; план: PRODUCTION_READINESS_FINAL.md §M6 |

---

## Верификация 2026-09-04 (координатор, прямые команды)

| Проверка | Результат | Базовая линия | Вердикт |
|---|---|---|---|
| `uv run python -m pytest --collect-only -q` | **16777 collected, 1 error** (чистый запуск) | 16243, 0 errors | P0 REGRESSION → R1 |
| `uv run ruff check src/` | **159 errors** (130 auto-fixable) | 0-6 | P1 → T2 |
| Working tree | 7 файлов WIP + uv.lock (cryptography specifier, M3-#4 остаток) | — | Не трогать |
| bandit/vulture/layers/outdated | Не перевыполнены в этой сессии | SWARM_SYNTHESIS 2026-09-02: 0 HIGH / 0 @90% / 0 new violations / 106 outdated | Переверить в Фазе A |

**Наблюдение**: при параллельном запуске pytest с другими процессами коллекция флакует (225 errors vs 1) — импорт-тайм побочные эффекты в тестах; фиксируется как P2-наблюдение (T5), не блокер.

---

## REOPENED

| ID | Задача | Причина (REOPENED) | Дата | Доказательство регрессии |
|---|---|---|---|---|
| R1 (=M2-#11 частично) | `src/backend/dsl/engine/processors/workflow/workflow_subprocess.py:26` — import-time вызов `get_workflow_factory_module_provider()` | Sprint 87 final batch мигрировал файл на DI, но вызов на уровне модуля при импорте падает: `ModuleRegistryError: Неизвестный ключ infrastructure-модуля: 'workflow'` (module_registry, 45 ключей без `workflow`). Ломает `pytest --collect-only` (1 error → pytest Interrupted → `make test` FAIL). Ретро S87 заявляло «100% CLOSED» без проверки коллекции — false claim | 2026-09-04 | `uv run pytest tests/unit/dsl/engine/processors/workflow/test_processor_registry_integration.py --collect-only` → ModuleRegistryError |

---

## TODO — backlog (P0 → P2)

| ID | Приоритет | Домен | Задача | Оценка |
|---|---|---|---|---|
| T1 | **P0** | dsl | Фикс R1: убрать import-time DI-вызов в `workflow_subprocess.py` (lazy в точке использования), вернуть коллекцию к 0 errors. Команда-доказательство: `uv run python -m pytest --collect-only -q` → `N collected, 0 errors` | 1h |
| T2 | **P1** | repo-wide | `ruff check src/` 159 → 0 (130 auto-fix + ручные 29). Доказательство: `uv run ruff check src/` → `All checks passed` | 2h |
| T3 | **P1** | coverage | M4: overall coverage 30.8% → 70% gate (`fail_under 60→70`), приоритет DSL processors / entrypoints / infrastructure (план M4-#3..#7 в PRODUCTION_READINESS_FINAL) | 32h |
| T4 | **P1** | hardening | M5: 10 задач (pooling, graceful shutdown, CB/rate-limit библиотечные, backpressure, idempotency, timeouts, correlation-id, readiness, auth-matrix M5-#9) | 28h |
| T5 | **P2** | tests | Недетерминированная коллекция при параллельных процессах (import-time side effects) — инвентаризация модулей с импорт-тайм I/O в tests/ | 4h |
| T6 | **P2** | docs | Актуализация docs/STATUS.md + ARCHITECTURE.md по итогам цикла (финальный sync в M6-#6) | 2h |

## DONE — задачи (закрыты, не переанализируются)

| ID | Задача | Закрыта | Доказательство |
|---|---|---|---|
| M2-#1..#17, #19..#26 | God-objects, dead code, DI-миграции (55 сайтов), vulture FP-батчи | S49-S87 | ретро Sprint 64 `fea658052`, S87 `a05ad0106` (55/55) |
| M3-#1..#6 | pip-audit reverification, tornado, pypdf, cryptography+ADR-0288, diskcache deferral | S55+S58 | `3ce5743ef`, `a2ce9ce42`, `d66286f31` |
| M4-#1 (частично) | core/auth coverage 79% ≥ 70% | S88 | `3101e1a45` |

---

## Спринт-план (текущий цикл, точка финиша — done-критерии майлстоунов)

1. **Фаза A** (идёт): рой аналитиков по 10 доменам, сверка с ledger; синтез → этот файл.
2. **Фаза B**: T1 (P0) → T2 (P1) → T3/T4 по саб-спринтам; атомарные коммиты, `IN_PROGRESS`/`DONE` здесь.
3. **Фаза C**: ревью + функциональные тесты + ретро после каждого саб-спринта.
4. **Финиш**: M4+M5+M6 DONE, R1 закрыт, 0 открытых TODO, pre-prod-check и нагрузочный тест пройдены, STATUS.md синхронен.
