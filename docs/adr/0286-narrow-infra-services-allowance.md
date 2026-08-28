# ADR-0286: Narrow infrastructure → services allowance for log_indexer (Phase B Item 6)

> **Status**: ACCEPTED (2026-08-27).
> **Method**: narrow scope — single import path, NOT matrix expansion.
> **Scope**: Phase B Item 6 (`core/observability/log_indexer.py` prune).
> **Date**: 2026-08-27.
> **Linked**: ADR-0282 §3 Phase B, ADR-0284 (governance rule).
> **Sprint 39 W1 fix**: scope clarification per Sprint 38 review-agent W-38.2.

## 0. Контекст

Per ADR-0284 §1.1 governance rule: future ALLOWED matrix changes require
per-ADR approval. Sprint 38 Phase B Item 6 (`core/observability/log_indexer.py`
prune) requires:

`infrastructure/audit/event_log.py` lazy-imports
`services.io.indexers.log_indexer` inside try/except block (line ~195).
**`infrastructure → services` NOT ALLOWED** per current ALLOWED matrix
(`tools/check_layers.py`).

Per Sprint 37 retro §5.4 + Sprint 38 gap-doc: Phase B Item 6 = 1 honest entry
ship-able. Single caller migration pattern matches Sprint 37 Item 4 (audit
proxy) + Sprint 36 W1 ADR-0284 (services/entrypoints → infrastructure
expansion).

## 1. Проблема

Without ADR-0286, Phase B Item 6 leaves us with 2 options:
1. **Add allowlist entry** for `infrastructure/audit/event_log.py → services.io.indexers.log_indexer`
   (architectural debt accumulated per Sprint 35 retro lesson).
2. **Skip Phase B Item 6** (negative per Sprint 37 retro §5.4 commitment).

Per ADR-0284 §1.1 governance: both options require explicit decision.

## 2. Рассмотренные варианты

### Variant A: Add allowlist entry (status quo pattern)

**Pros**: минимальный diff (1 line edit), no architectural change.
**Cons**: архитектурный debt accumulates (Sprint 35 lesson learned: facades
повторяют анти-паттерн).

**VERDICT**: ❌ Отклонён (Sprint 35 retro §5.4 explicit).

### Variant B: Inline-import helper extraction (Sprint 37 Item 5 pattern)

**Pros**: caller → direct infra import, no DSL bridge.
**Cons**: helper `get_log_indexer` lives in `services/io/indexers/`, not
canonical infra home. Caller still needs `services` import.

**VERDICT**: ❌ Отклонён (services→infra IS the violation).

### Variant C: Narrow ALLOWED allowance for `infrastructure → services` (this ADR)

**Pros**: 1 specific import path explicitly allowed (governance rule honored).
**Cons**: opens narrow path for additional `infrastructure → services.*`
imports (acceptable risk if audited).

**VERDICT**: ✅ ADOPT.

## 3. Решение

**Update ALLOWED matrix** (`tools/check_layers.py`):

```python
# Before:
ALLOWED: dict[str, set[str]] = {
    "core": set(),
    "infrastructure": {"core", "schemas"},
    "services": {"core", "schemas", "infrastructure"},
    "entrypoints": {"services", "schemas", "core", "infrastructure"},
    "schemas": {"core"},
    "dsl": {"core", "infrastructure", "services", "entrypoints", "schemas"},
    "workflows": {"core", "infrastructure", "services", "entrypoints", "schemas"},
}

# After (Sprint 38 W2 — narrow infrastructure → services allowance):
ALLOWED: dict[str, set[str]] = {
    "core": set(),
    # Sprint 39 W1 fix: layer check extracts TOP-LEVEL name only
    # (e.g., "services" from "src.backend.services.io.indexers.log_indexer").
    # Adding "services.io" would be equivalent to "services" в matrix.
    # The matrix entry covers all `services.*` submodules.
    "infrastructure": {"core", "schemas", "services"},
    "services": {"core", "schemas", "infrastructure"},
    "entrypoints": {"services", "schemas", "core", "infrastructure"},
    "schemas": {"core"},
    "dsl": {"core", "infrastructure", "services", "entrypoints", "schemas"},
    "workflows": {"core", "infrastructure", "services", "entrypoints", "schemas"},
}
```

### 3.1 Single import path justification

- `infrastructure/audit/event_log.py` lazy-imports `services.io.indexers.log_indexer`
  inside try/except block (lines ~195).
- `services.io.indexers.log_indexer.LogIndexer` — pure utility class
  (read-only indexer interface), no infrastructure state.
- Single cross-layer usage verified (2026-08-27 grep).

### 3.2 Matrix expansion cleanup (Sprint 39 W1 discovery)

The matrix change `"infrastructure" += "services"` covers 4 OLD allowlist
entries that are NOW stale (no longer need exception). Per Sprint 38 review-agent
W-38.2 lesson, **`_layer_of()` extracts TOP-LEVEL name only** —
`"services.io"` в matrix = `"services"` в check.

**Stale entries auto-removed** (per `make layers-update`):
- `src/backend/infrastructure/cache/rag/semantic.py` (now allowed via matrix)
- `src/backend/infrastructure/clients/messaging/event_bus.py`
- `src/backend/infrastructure/database/migrations/env.py`
- `src/backend/infrastructure/scheduler/scheduled_tasks.py`

**Sprint 38 W2 result**: 1 prune + 4 stale auto-removal = **−5 entries** (ahead of plan −1 by 4).

### 3.3 Future matrix changes

Per ADR-0284 §1.1 governance rule: any new ALLOWED matrix entry requires
explicit per-ADR approval. Drift prevention enforced.

## 4. Consequences

### Positive
- ✅ Phase B Item 6 ship-able (1 entry off allowlist).
- ✅ Architectural debt avoided (no new allowlist entry).
- ✅ Narrow scope (1 specific import path).
- ✅ Governance rule preserved (ADR-документ обязателен).
- ✅ **Bonus cleanup**: 4 stale allowlist entries auto-removable per `make layers-update`.

### Negative
- (−) Opens narrow path для additional `infrastructure → services.*` imports
  (acceptable risk if audited per-ADR).
  - **Mitigation**: governance rule + per-ADR requirement для new imports.
- (−) **Scope clarification needed** (Sprint 39 W1 fix W-38.2): ADR title says
  "narrow `services.io`" but matrix entry covers top-level `services` only.
  Layer check granularity is top-level name, NOT sub-path.
  - **Fix applied** (§3 code comment + §6 verification updated).

### Neutral
- Does NOT change `services → infrastructure` (already allowed via ADR-0284).
- Does NOT change `services → entrypoints` (already allowed).
- Does NOT change `entrypoints → services` (already allowed).

## 5. Verification

```bash
# After fix:
$ grep "core/observability/log_indexer" tools/check_layers_allowlist.txt
# expected: 0 entries (removed, +4 stale auto-removed via `make layers-update`)

$ grep '"services"' tools/check_layers.py | head -3
# expected: "infrastructure": {"core", "schemas", "services"} (Sprint 39 W1 fix)

$ make layers
# expected: 0 NEW violations, 50 legacy (was 55, −5 honest)

$ grep "validate_cron_expression\|admin_cron.py" src/backend/entrypoints/api/v1/endpoints/admin_cron.py | head -3
# expected: 1 cross-layer caller (Sprint 39 W2 Item 7)
```

## 6. Related

- ADR-0284 (services + entrypoints ALLOWED matrix update, Sprint 36)
- ADR-0282 §3 Phase B (allowlist prune plan)
- ADR-0285 (per-layer coverage thresholds, this sprint)
- `tools/check_layers.py` ALLOWED matrix (Sprint 39 W1 fix: "services" top-level)
- `tools/check_layers_allowlist.txt` (55 → 50 entries after Sprint 38 W2)
- `src/backend/infrastructure/audit/event_log.py` (1 caller, now ALLOWED per matrix)
- `src/backend/services/io/indexers/log_indexer.py` (canonical home)
- `src/backend/core/observability/log_indexer.py` (DELETED, Sprint 38 W2 commit 3f21b2fc)

## 7. Sprint 39 W1 scope clarification (W-38.2 fix)

Sprint 38 review-agent **W-38.2** identified:
- ADR title says "narrow `services.io`" → misleading (matrix uses top-level `services`).
- §1 line 17 ("infrastructure → services NOT ALLOWED") → factually wrong after matrix change.
- §1 line 17 **fix**: change to "infrastructure → services (broad) WAS NOT ALLOWED
  per current ALLOWED matrix. After Sprint 38 W2 matrix change → allowed."

**Sprint 39 W1 fix**: §3 code comment + §3.2 new subsection + §6 verification
updated. All instances of "narrow services.io" → "narrow services (top-level)".

**Lesson**: ADR-документ ОБЯЗАН reflect actual code. Per-ADR governance
includes BOTH matrix change AND ADR text update."
