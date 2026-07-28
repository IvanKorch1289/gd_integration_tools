# Layer 7 (Observability) Status — Cycle 49

> **Scope:** `src/backend/infrastructure/observability/`, `src/backend/core/observability/`
> **Status:** Production-ready for audited scope, 5.0/10 health score.
> **Cycle 49 analysis:** No actionable fixes; cycle aborted.

## Components analyzed

| Component | LOC | Tests | Status |
|---|---|---|---|
| `core/observability/baggage.py` | 265 | yes | ✅ production-ready |
| `core/observability/logging_helpers.py` | 140 | yes | ✅ production-ready |
| `core/observability/correlation.py` | 98 | yes | ✅ production-ready |
| `core/observability/log_indexer.py` | 30 (facade) | yes | ✅ facade clean |
| `core/observability/metrics.py` | 28 | yes | ✅ production-ready |
| `infrastructure/observability/pii_filter.py` | small | yes | ✅ production-ready |
| `infrastructure/observability/otel.py` | medium | yes | ✅ production-ready |

## Cycle 49 attempt: log_indexer migration

Tried to migrate `services.io.indexers.log_indexer` → `core.io.indexers.log_indexer`
(following the cycle 47-48 manifest migration pattern).

**Result: ABORTED** due to recursive boundary issue:
- `core.io.indexers.log_indexer.py` imports from `services.io.search`
- Migrating `services.io.search` → `core.io.search` would recursively
  cascade to multiple other files

Cost-benefit analysis showed the recursive migration would touch
~15+ files across multiple modules (search, pii_filter, etc.) with
no functional benefit. Decided to document the existing boundary
exception (ADR-0248) instead.

## Findings

1. **No TODO/FIXME/NotImplementedError in Observability** (verified cycle 49)
2. **All TODO strings in `pii_filter.py` are docstring examples** (X-pattern
   regex like `XXXX XXXXXX`), not actual TODOs
3. **Layer enforcement clean**: 0 new layer violations from `core.observability`
4. **Boundary documentation**: `log_indexer.py` properly documents the
   `core → services` exception (ADR-0248)

## Conclusion

Layer 7 is mature and well-maintained. Cycle 49 closed with no
actionable fixes. Future cycles can target:
- Service-level migration of `search` module (multi-file refactor)
- OTel collector optimization (out-of-scope, requires deployment testing)
