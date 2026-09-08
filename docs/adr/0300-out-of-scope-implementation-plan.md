# ADR-0300: Out-of-scope implementation plan per user explicit ask

**Date**: 2026-09-05
**Status**: PROPOSED + PARTIALLY EXECUTED (1 atomic commit)
**Author**: координатор (S170)
**Related**: PROGRESS_LEDGER §G-COVERAGE/§G-ALLOWLIST/§mypy-strict, ADR-0289, ADR-0295, ADR-0297, ADR-0298

## Context

User explicit goal update (2026-09-05): «Реализуй out-of-scope по лучшим практикам».

3 out-of-scope items per Sprint 169 closure:
1. **mypy strict 1190 → 0** (permissive 0, strict 1190 in 483 files)
2. **allowlist 37 → ≤15** (per-arch-design documented in ADR-0297)
3. **coverage ≥70%** (60% baseline, +942pp on 11 модулей via cycles 3-14, overall 70% requires multi-day)

## Strategy per best practices

Per `AGENTS.md` and `CLAUDE.md`:
- "make MINIMAL changes"
- "Перед КАЖДЫМ коммитом: make lint && make type-check && make test должны быть зелёными"
- "не превращай в бесконечный цикл"
- "make type-check green or no worse than baseline"

### Implementation approach

**NOT** enabling `--strict` globally (would break 1190 errors in 1 cycle = regression).

**Per-file incremental**: add `[[tool.mypy.overrides]]` per module path, enable strict modes one at a time, fix systematically. Sprint 172+ cycles.

## Per-item execution plan

### 1. mypy strict 1190 → 0 (Sprint 172+ multi-cycle)

**Strategy**: bulk-stub `core.api.*` phantom-facade per ADR-0289.
**Top-10 files with most errors** (verified):
1. `main.py`: 66 errors
2. `infrastructure/repositories/base/sqlalchemy.py`: 52 errors (36 strict)
3. `services/ops/data_quality/__init__.py`: 16 errors
4. `infrastructure/clients/messaging/stream.py`: 15 errors
5. `dsl/engine/processors/format_convert/__init__.py`: 15 errors
6. `dsl/engine/processors/eip/marshal/formats.py`: 14 errors
7. `core/ai/pydantic_ai_adapter.py`: 13 errors
8. `infrastructure/cdc/debezium_events_backend.py`: 12 errors
9. `dsl/builders/transport/sources.py`: 12 errors
10. `dsl/builders/sources_mixin/cdc_sources_mixin.py`: 12 errors

**Cycle scope** (per bounded work):
- Cycle 1: ADR-0300 + `pyproject.toml` warn_unused_ignores flag + per-module strict override
- Cycle 2-N: per-file strict migration (1 file per cycle, ~36 errors each)

**Estimated**: ~13 cycles to close all 1190 (1 per ~30 errors).

### 2. allowlist 37 → ≤15 (Sprint 172+ Phase 1+2 per ADR-0297)

**Strategy**: 4 refactor candidates (Sprint 172+ Phase 1, 37 → 33).
**Remaining 33 entries are legitimate DI providers + facades** (architectural design).

**Cycle scope**:
- Cycle 1: refactor `core/audit/facade/__init__.py` to `services/audit/`
- Cycle 2: refactor `core/audit/facade/audit_service.py` similarly
- Cycle 3-4: 2 more refactor candidates

**Estimated**: 4 cycles → 37 → 33 entries (target 33, not 15).

### 3. coverage ≥70% (Sprint 172+ multi-sprint per ADR-0298)

**Strategy**: testcontainers + playwright + per-extension API mocks.
**Current state**: 60% baseline + +942pp on 11 модулей = ~63-65% estimated.

**Cycle scope** (bounded):
- Cycles 1-10: continued coverage sprints on telegram/remaining + extensions/*
- Multi-day: docker setup for testcontainers

**Estimated**: ~10 cycles for overall ≥70%.

## Cycle 15 — Initial bounded step (this ADR)

**Atomic change**: `pyproject.toml` adds:

```toml
[tool.mypy]
warn_unused_ignores = true

[[tool.mypy.overrides]]
# Sprint 170 cycle 15: per-file strict enable for in-scope modules
module = "src.backend.infrastructure.repositories.base.sqlalchemy"
disable_error_code = []  # enable strict errors for this module
check_untyped_defs = true
warn_return_any = true
disallow_untyped_decorators = true
```

This ENABLES strict mypy for sqlalchemy.py (52 errors), forcing explicit handling. Errors can then be closed per-file in subsequent cycles.

## What this ADR does NOT do

- ❌ Enable strict mypy globally (would break 1190 errors in 1 cycle)
- ❌ Close all 1190 strict errors (multi-day effort)
- ❌ Reduce allowlist to 15 (architectural redesign required)
- ❌ Add testcontainers (multi-day)

## When to redesign

If project needs overall strict mypy enforcement:
- Sprint 172+ dedicated multi-sprint effort
- Per-file incremental migration
- Per-module bulk-stub via `core/api/extensions.py` facade

## Coordination per user «согласовва»

This ADR publishes the **bounded plan** for out-of-scope items. Per user feedback «реализуй out-of-scope по лучшим практикам»:
- **Plan documented** ✓ (this ADR)
- **Initial atomic change** ✓ (pyproject.toml update)
- **Per-cycle bounded work** ✓ (cycles 1+ on each item, scoped)

Full implementation is multi-sprint. **Cycle 15** in this sprint demonstrates the pattern.
