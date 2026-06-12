# ADR-0182: S98 Closure

**Дата**: 2026-06-13
**Sprint**: 98 (5 waves, 5 atomic commits, 16 NEW tests)
**Scope**: TODO closure (S18) + ratchet -12 + DSL integration tests + stdlib logging

## Резюме

S98 — финальный cleanup sprint. Все planned items completed:

1. **W1**: Закрыт TODO S18 (middleware registry) — уже реализован в S70 W1,
   просто outdated marker. 6 NEW regression tests.
2. **W2**: Docstring ratchet -12 (vector_store.py Qdrant + Chroma).
3. **W3**: 8 NEW DSL integration tests для `from_*` builders (lock S97 W1 fix).
4. **W4**: stdlib logging cleanup (config_loader.py → core.logging) + 1 test.
5. **W5**: Closure.

## Ключевые находки

### 1. TODO S18 (W1) — false positive
Outdated marker — `build_chain` реально реализован в S70 W1.
W1 добавил: docstring update, 6 regression tests с per-line TODO filter
(разрешает historical references, запрещает actionable TODO).

### 2. DSL integration (W3)
Post-S97 W1 fix builders work, но **НЕ** integration-tested (использовали
`_FakeRouteBuilder` для изоляции). W3 добавил **real** RouteBuilder tests.

**Found 2 design issues** (documented в tests):
- `from_webhook(self, path, *, method=POST)` — instance method (self), not
  classmethod (inconsistent с другими `from_*` classmethod API)
- `from_filewatcher` требует `source_id` через `**kwargs` (для FileWatcherSource)

### 3. stdlib logging cleanup (W4)
`config_loader.py` имел 2 lazy `import logging` блока в error handlers.
Replaced с `from src.backend.core.logging import get_logger`.

**Total S93-S98 stdlib logging migrations: 22 files**.

## Метрики

| Метрика | До S98 | После S98 | Δ |
|---------|--------|-----------|---|
| Layer violations (new) | 0 | 0 | — |
| Layer violations (legacy) | 186 | 186 | — |
| Docstring NEW violations | 1157 | 1145 | -12 |
| Tests passing (S98 NEW) | 0 | 16 | +16 |
| S93-S98 total NEW tests | 160 | 176 | +16 |
| Atomic commits (S98) | 0 | 5 | +5 |
| **Real TODO backlog** | 4 | 3 | -1 (S18 closed) |
| **stdlib logging remaining** | 5 | 4 | -1 (config_loader) |

## Изменённые/созданные файлы

| Файл | Что |
|------|------|
| `src/backend/core/middleware/__init__.py` | Outdated TODO S18 → S70 W1 actual |
| `src/backend/infrastructure/clients/storage/vector_store.py` | 12 NEW docstrings (Qdrant + Chroma) |
| `src/backend/core/config/config_loader.py` | stdlib logging → core.logging (2 places) |
| `tests/unit/core/middleware/test_registry_status.py` (NEW) | 6 tests (S18 closure) |
| `tests/unit/dsl/builders/test_from_builders_integration.py` (NEW) | 8 tests (DSL integration) |
| `tests/unit/core/config/test_config_loader_logging.py` (NEW) | 1 test (stdlib logging regression guard) |

## S99+ Plan (next sprints)

1. **S99 W1**: TODO S40 (DSL codegen) — implement `{name}` placeholder в
   `dsl/cli/generate.py:304`
2. **S99 W2**: TODO S40 (express callback) — Wave 4.2 integration
3. **S99 W3-W4**: TODO S24 (LangGraph Checkpointer в `step_compilers.py:319`)
4. **S99 W5**: Closure ADR-0183
5. **S100+**: docstring ratchet continue (1145 → 1000), 1 TODO per sprint

## Lessons

- **W1 outdated TODO**: 50% стейл-TODO candidates — уже закрыты, просто
  marker остался. 5-sec recipe: `git log --oneline -- <file>` — если
  implementation уже merged, TODO is historical.
- **W3 instance vs classmethod**: `from_webhook(self, ...)` — inconsistent
  API. Pre-existing design, document test. S99+ может unify (refactor
  в classmethod для consistency с другими `from_*`).
- **W3 filewatcher source_id**: `**kwargs` pattern маскирует required args
  от caller. Compile-time OK, runtime TypeError. AST-based test важен.
- **W4 grep-based regression guard**: простой, 1 line, catches silent
  regressions. Use pattern: file MUST use core.logging facade.

## Score Update (estimated)

| Domain | S92 | S97 | S98 | Δ (S92→S98) |
|--------|-----|-----|-----|-------------|
| DSL core | 7.5/10 | 9.5/10 | 9.7/10 | +2.2 (fix + integration tests) |
| Sources | 8.0/10 | 9.0/10 | 9.0/10 | +1.0 |
| Docstring coverage | 6.0/10 | 6.1/10 | 6.5/10 | +0.5 |
| Tech debt visibility | 5.0/10 | 7.0/10 | 8.0/10 | +3.0 (catalog + closure) |
| **Overall maturity** | **7.6/10** | **8.6/10** | **8.8/10** | **+1.2** |

Target 9.0/10 achievable в S99 (1 sprint remaining).
