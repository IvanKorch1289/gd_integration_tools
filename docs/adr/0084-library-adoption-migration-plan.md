# ADR-0084 — Library Adoption Migration Plan (structlog, typer, rich, aiocache)

**Status:** Accepted
**Date:** 2026-06-07
**Authors:** K3
**Sources:** v22 final report (R22.1-R22.5), S58 W2 (typer+rich миграция), S57 W1 (pendulum adoption)
**Supersedes:** N/A (new ADR)

---

## Context

v22 final report (2026-06-05) обнаружил dormant state в adoption of high-value libraries:

- **structlog** (v22 п.4): реализован в `infrastructure/logging/structlog_backend.py` (260 LOC) + factory + SinkRouter + PII filter, но default backend = stdlib logging
- **typer** (v22 п.5): в core deps (`typer>=0.12.0,<1.0.0` line 102), 0 использований в `tools/`
- **rich** (v22 п.5): в `security` extras, не в core deps, 0 использований в `tools/`
- **aiocache** (v22 lib-table): НЕ в deps, рекомендован для замены custom cache decorators (681 LOC)

Project rule "libraries > custom" (per S50+ memory) → эти gaps должны быть закрыты, но scope реалистичен.

## Реальное Состояние (S58 W2 recon)

| Library | Status | S58 миграция | Остаток |
|---------|--------|--------------|---------|
| **structlog** | Backend реализован, default=stdlib | W2: НЕ мигрировал (risk: GELF-required config) | 606 файлов с `import logging` |
| **typer** | В core deps, 0 использований | W2: мигрировал `check_layer_imports.py` (proof-of-concept) | ~10 tools с argparse |
| **rich** | В `security` extras, 0 использований | W2: lazy import в `check_layer_imports.py` (fallback на plain text) | — |
| **aiocache** | НЕ в deps | W2: НЕ мигрировал (нет инвентаря cache decorators) | ~681 LOC custom cache code |

## Decision

**Phase migration: каждая library = отдельный sprint (или wave в рамках S59+).** Scope каждой волны фиксирован по формуле "библиотека уже в deps + 1-2 proof-of-concept файла + ADR-0084 update".

Приоритеты (по v22 + project context):

1. **S59 W1: typer + rich CLI migration** (top-3 tools после check_layer_imports)
   - `tools/perf_gate.py` (часто используется в CI)
   - `tools/scaffold.py` (developer-facing)
   - `tools/migrate_plugin_manifest.py` (one-shot migrations)
   - **Out of scope**: tools/checks/*.py (~20 файлов, lower priority)
2. **S59 W2: structlog default switch + migrate top-3 modules**
   - Изменить `factory.py:configure_logging` default: auto → prefer structlog (если установлен И log_settings.gelf_host не пуст)
   - Migrate 3 critical loggers на `get_logger()` factory:
     * `infrastructure/logging/structlog_backend.py` (self)
     * `core/database/listeners.py` (db_logger)
     * `observability/` (3 observability модуля)
   - **Out of scope**: 603 оставшихся файла
3. **S60 W1: aiocache migration (infrastructure-level)**
   - Inventory: `grep -rln "def cached\|@cache\|@lru_cache" src/backend/`
   - Identify: 681 LOC custom cache decorators → migrate to `aiocache.cached()` for async paths
   - **Out of scope**: sync lru_cache uses (stay stdlib)
4. **S60 W2: typer+rich coverage push** (оставшиеся tools)
   - tools/checks/*.py
   - tools/api_fuzz_runner.py
   - tools/changelog_autogen.py

**Граница**: каждая волна = atomic commit, library-функционал **должен работать** end-to-end (никаких placeholder/TODO).

## Альтернативы Evaluated

| Подход | Trade-offs | Decision |
|--------|-----------|----------|
| **Big-bang migration всех 606 файлов на structlog** | ~3-5 спринтов, высокий риск regression, GELF config может сломать dev environments | ❌ Rejected (out of S58-S60 scope) |
| **Skip libraries migration, оставить stdlib + argparse** | Конфликт с project rule, v22 finding unresolved | ❌ Rejected (regression) |
| **Phase migration (chosen)** | Каждая library = отдельная sprint, top-N usage сначала, ADR-0084 фиксирует scope/sequence | ✅ **Selected** |
| **Купить стороннее решение (e.g., DataDog/New Relic)** | $$$/month, vendor lock-in, несовместимо с self-hosted-first constraint | ❌ Rejected (cost + arch) |

## Scope Boundaries (Anti-Patterns)

### Что НЕ делаем в phase migration:

- ❌ Полная миграция 606 файлов на `get_logger()` (S60+ scope)
- ❌ GELF requirement для structlog (default OFF в dev/test)
- ❌ Migration tools/checks/*.py на typer (S60 W2, low priority)
- ❌ Breaking changes в `LoggerProtocol` (5 methods: debug/info/warning/error/exception + bind)

### Что ДЕЛАЕМ в каждой phase:

- ✅ Atomic commit per library/per wave
- ✅ Tests for new code (no "wontfix" TODO tests)
- ✅ Fallback path для slim environments (lazy import rich, structlog optional)
- ✅ Backward compat: existing `import logging` continues to work
- ✅ Documentation update (ADR + changelog + comment в коде)

## S58 W2 Progress (this commit)

| Task | Status |
|------|--------|
| Migrate `tools/check_layer_imports.py` argparse → typer+rich | ✅ Done (commit `5bf2bd3f`) |
| Add `scan_directory()` pure function for white-box testing | ✅ Done |
| Lazy import rich с fallback на plain text | ✅ Done |
| Add 14 unit tests (CliRunner + direct API) | ✅ Done |
| ADR-0084 (this) | ✅ Done |
| **NOT done** (deferred to S59+): default structlog switch | ⏭ S59 W2 |
| **NOT done** (deferred to S59+): migrate 10+ other tools | ⏭ S59 W1 |

## Verification

```bash
# Verify typer migration works
python tools/check_layer_imports.py --help
# → shows typer auto-generated help, --plain option, [DIRECTORY] argument

python tools/check_layer_imports.py extensions/
# → exits 1 with rich table OR plain text violations (--plain)

# Verify tests pass
pytest tests/unit/tools/test_check_layer_imports.py -v
# → 14 passed
```

## Open Items

- **S59 W1**: migrate `tools/perf_gate.py`, `tools/scaffold.py`, `tools/migrate_plugin_manifest.py` на typer
- **S59 W2**: change `factory.py:configure_logging` default — prefer structlog (если GELF host не пуст)
- **S59 W2**: migrate 3 critical loggers на `get_logger()` factory
- **S60 W1**: aiocache inventory + migration (681 LOC → `aiocache.cached()`)
- **S60 W2**: tools/checks/*.py typer coverage (lower priority)
- **S61+**: remaining 603 logging migrations (backlog)

## Relation to Other ADRs

- **ADR-0083** (Versioning DSL): establishes pattern "library + thin DSL facade" — это применяется к structlog/typer/rich миграциям
- **S57 W1** (pendulum): migration of `datetime` → `pendulum` для S57+ new code; pattern: drop-in compat + lazy adoption
- **S57 W2** (pydash), **S57 W3** (orjson), **S57 W4** (glom): similar pattern — library adoption, new code uses library, old code migrates opportunistically
- **v22 п.4 / п.5**: this ADR = execution plan для v22 findings
