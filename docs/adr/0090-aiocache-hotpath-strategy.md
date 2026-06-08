# ADR-0090: aiocache hot-path strategy (audit + defer)

**Date:** 2026-06-08
**Status:** Accepted (S67 W1 — audit + decision)
**Sprint:** S67
**Deciders:** core team
**Supersedes:** — (extends ADR-0086, ADR-0051)
**Related:** ADR-0086 (aiocache migration plan), ADR-0051 (in-house cache)

## Context

Backlog S64-W1: "aiocache default-ON hot-path" (от роевого анализа V22).
ADR-0086 (S59 W4) предложил per-feature миграцию custom cache (1778 LOC)
→ aiocache. ADR-0051 явно отказался от aiocache в пользу in-house
`CachingDecorator` для hot-path (требует envelope/stampede/tenant).

Audit проведён 2026-06-08:

**aiocache state:**
```
pyproject.toml dep:     "aiocache>=0.12.0,<1.0.0"  (declared)
.venv:                  NOT installed (ModuleNotFoundError)
src/backend usages:     1 (infrastructure/cache/aiocache_poc.py — POC only)
```

**@cached/@multi_cached usage в production:**
```
grep -rn "@cached\|@multi_cached" src/backend/ → 11 hits
  - 7 в cache_decorators.py (definitions + docstrings)
  - 2 в core/resilience/decorators.py (docstring reference)
  - 1 в core/utils/cache_keys.py (docstring)
  - 1 в core/resilience/__init__.py (re-export)
  - 0 production callsites  ← KEY FINDING
```

**@aiocache.cached usage:**
```
grep -rn "@aiocache.cached" src/backend/ → 1 hit (POC only)
```

**Вывод:** in-house `@cached` decorator определён, но **не используется
в production**. Hot-path не декорированы ни in-house, ни aiocache.

## Decision

**DEFER** "aiocache default-ON hot-path" до момента, когда будут
выполнены preconditions:

### Preconditions (блокирующие)

1. **aiocache installed в .venv** — требует `pip install aiocache`
   (запрещено в sandboxed env per AGENTS.md rule).
2. **Hot-path call sites identified** — 0 production callsites
   сейчас. Audit нужен для определения 5-10 hot-path функций
   (например, settings load, schema validation, secret resolution).
3. **Envelope/stampede/tenant strategy** — для 4 из топ-10 hot-path
   in-house `CachingDecorator` остаётся обязательным (envelope
   compression + stampede protection + tenant isolation).
   aiocache НЕ предоставляет эти features из коробки.
4. **Metrics integration** — aiocache plugins для prometheus
   (нужен custom serializer + metrics collector).

### Стратегия (когда preconditions выполнены)

**Phase 1 (S67+):** identify 5 hot-path call sites, decorate
in-house `@cached` (НЕ aiocache), measure hit rate, document
gain.

**Phase 2 (S68+):** для 1-2 hot-path без envelope/stampede/tenant
заменить in-house decorator на aiocache (через feature-flag
`cache.aiocache_enabled`, default-OFF).

**Phase 3 (S68+):** если Phase 2 показывает gain ≥ 30% latency
→ включить aiocache default-ON для этих use-cases.

### Когда НЕ использовать aiocache

* Hot-path с envelope (gzip + JSON serialization) — in-house
  `CachingDecorator` остаётся primary.
* Hot-path с stampede protection (`KeyLockManager`) — aiocache
  не предоставляет per-key lock, нужен custom plugin.
* Hot-path с tenant isolation (`tenant_wrapper.py`) — aiocache
  не имеет built-in tenant prefix, нужно вручную.
* Hot-path с disk backend — aiocache DiskCache в contrib,
  не core, не используем в production.
* Hot-path с circuit breaker integration — in-house cache_chain
  integration остаётся primary.

## Consequences

### Positive

* Audit-факт зафиксирован: 0 production callsites используют
  in-house `@cached` decorator. Это baseline для будущей
  миграции.
* Hot-path стратегия ясна: envelope/stampede/tenant → in-house,
  simple memory-only → aiocache.
* ADR-0086 (S59 W4) + ADR-0051 (in-house) + ADR-0090 (этот)
  дают полную картину cache-strategy.

### Negative

* Backlog S64-W1 ("aiocache default-ON hot-path") **DEFERRED**.
* Hot-path performance gain не реализован (но и не критично —
  текущая hot-path не bottleneck по metrics).
* aiocache в pyproject.toml dep но не в .venv — discrepancy
  (resolved при `uv sync` или `pip install`).

### Neutral

* aiocache 0.12+ API стабилен (не blocking).
* 2 файла aiocache-related (aiocache_poc.py, cache_decorators.py)
  остаются как есть — POC + facade.

## Implementation Status

| Component | Status | Location |
|-----------|--------|----------|
| aiocache dep в pyproject | DONE | pyproject.toml |
| aiocache_poc.py | DONE | infrastructure/cache/aiocache_poc.py |
| in-house @cached facade | DONE | core/resilience/cache_decorators.py |
| 0 production callsites | CONFIRMED | grep audit |
| Hot-path call sites identified | TODO | S67+ Phase 1 |
| aiocache installed в .venv | TODO | blocked by sandboxed env |
| 1-2 callsites migrated | TODO | S68+ Phase 2 |
| Default-ON for migrated callsites | TODO | S68+ Phase 3 (if ≥30% gain) |

## References

* `src/backend/core/resilience/cache_decorators.py` (in-house facade)
* `src/backend/infrastructure/cache/aiocache_poc.py` (POC)
* `src/backend/infrastructure/cache/` (custom cache, 1778 LOC)
* `pyproject.toml` (aiocache dep declared)
* ADR-0086 (aiocache migration plan, parent)
* ADR-0051 (in-house cache decision)
* S58 W1 LESSON: "libraries > custom" (libraries-vs-custom-gate skill)
