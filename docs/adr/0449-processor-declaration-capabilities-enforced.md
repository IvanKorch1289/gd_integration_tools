# ADR-0449 — Capability из декларации процессора проверяется в рантайме

* Статус: Accepted (2026-11-16, волна 32)
* Cycle: 188 (волна 32)
* Связан с: ADR-0366 (runtime-resolver), ADR-0416 (capability-контур), ADR-0443 (гейты)
* Затрагивает: `src/backend/dsl/engine/processors/base.py`, `tools/check_decorative_capabilities.py`, `tools/check_decorative_capabilities_allowlist.txt`, `tests/unit/dsl/engine/capability/test_decorator_capabilities_enforced_adr0449.py`

## Контекст

`@processor(capabilities=(...))` публиковал capability в JSON-схеме
(для LSP/линтера), но **движок её не проверял**: runtime-механизмом был только
`required_capability`. Гейт `check_decorative_capabilities` насчитывал 44
декоративные декларации — иными словами, контроль прав в этой форме был
иллюстративным.

## Решение

* `BaseProcessor._declared_capabilities()` собирает проверяемый набор:
  `required_capability` (первым, как раньше) **плюс** capability из
  декларации процессора, **чьё имя есть в vocabulary**;
* capability вне vocabulary остаётся advisory (легаси-декларации используют
  3-сегментную форму вида `net.outbound.compliance.api`, которой нет в
  vocabulary — у неё нет и scope, блокировать по ней вызовы было бы опасно);
* гейт `check_decorative_capabilities` учитывает новый критерий: декларация с
  именем из vocabulary **не** декоративна. Долг сократился 44 → 36;
* тесты фиксируют контракт (enforced / advisory / порядок).

## Уточнение волны 33 (2026-11-16): что именно enforced

Независимая проверка волны 33 (5 агентов, воспроизведение на реальном
SQLAlchemy/движке) уточнила границу этого ADR:

* **`_declared_capabilities()` — сбор набора, а не enforcement.** Проверку
  выполняет `BaseProcessor.auth_check()`, и вызывает её **сам процессор**
  (opt-in): так сделаны БД-процессоры (`db.read`/`db.write`), RPA-процессоры,
  `jdbc_query`, `export` и (с волны 33) `AuditProcessor` → `audit.write`
  (ADR-0454).
* **Проверки в общем пути исполнения шага нет.** `ExecutionEngine` и
  middleware вызывают `processor.process()`; capability-гейт внутри шага не
  выполняется. Поэтому у 32 из 36 мигрированных процессоров декларация
  остаётся **непроверяемой в рантайме** — даже при имени из vocabulary.
* **Гейт `check_decorative_capabilities` считает декларацию недекоративной по
  наличию имени в vocabulary**, а не по достижимости `auth_check()` из
  `process()`. Поэтому его «0 в долге» означает «нет легаси-форм вне
  vocabulary», а не «все capability enforced».

Итог: ADR-0449 закрывает **сбор и нормализацию деклараций**; enforcement
существует на уровне процессоров (ADR-0454 — эталон) и **не доведён до
общего пути исполнения**. Это отдельная задача (см. «Открытые позиции»).

## Открытые позиции (волна 33)

1. **Engine-wide enforcement.** Проверка capability перед каждым шагом в
   `ExecutionEngine`/`middleware` — тогда декларации процессоров станут
   настоящим барьером. Требования: (а) идемпотентность с внутренним
   `auth_check()` процессоров (без двойной проверки), (б) scope-запрос для
   каждого процессора (сейчас `_capability_scope()` по умолчанию `None`),
   (в) декларации в `route.toml`/`plugin.toml` для всех capability, которые
   реально используют 7 канонических роутов (сегодня — 2: `audit.write`,
   `function.call`), (г) миграция 35 новых имён в манифесты либо решение
   владельца о «advisory-режиме».
2. **Гейт CI, который видит декларации процессоров.**
   `tools/check_route_capabilities.py` и статическая карта линтера
   (`dsl/cli/lint.py`) смотрят на `required_capability`/`PROCESSOR_CAPABILITIES`,
   но не на `@processor(capabilities=...)` → новый роут с шагом `audit`
   без декларации CI не ловит (ловит рантайм).
3. **Декларации с именами из vocabulary, но без scope.** Пока у таких
   capability `scope_required=False` (миграция ADR-0451), при усилении
   scope-политики их придётся доработать точечно.

## Последствия

* 8 деклараций перестали быть декоративными по критерию гейта;
* миграция легаси-форм в vocabulary (ADR-0451) сократила долг 36 → 0;
* новые декларации с именами из vocabulary защищены гейтом автоматически —
  но **не** автоматически проверяются в рантайме (см. выше);
* честная формулировка статуса: «декларации собраны и нормализованы;
  enforcement — на уровне процессоров, не на уровне движка».
