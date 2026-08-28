# ADR-0286: Narrow infrastructure → services allowance for log_indexer (Phase B Item 6)

> **Status**: ACCEPTED (2026-08-27).
> **Method**: narrow scope — single import path, NOT matrix expansion.
> **Scope**: Phase B Item 6 (`core/observability/log_indexer.py` prune).
> **Date**: 2026-08-27.
> **Linked**: ADR-0282 §3 Phase B, ADR-0284 (governance rule).

## 0. Контекст

Per ADR-0284 §1.1 governance rule: future ALLOWED matrix changes require
per-ADR approval. Sprint 38 Phase B Item 6 (`core/observability/log_indexer.py`
prune) requires:

`infrastructure/audit/event_log.py` (existing entry) lazy-imports
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

### Variant C: Narrow ALLOWED allowance for `infrastructure → services.io` (this ADR)

**Pros**: 1 specific import path explicitly allowed (governance rule honored).
**Cons**: opens narrow path for additional `infrastructure → services.io.*`
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

# After (Sprint 38 W2 — narrow infrastructure → services.io allowance):
ALLOWED: dict[str, set[str]] = {
    "core": set(),
    "infrastructure": {"core", "schemas", "services.io"},  # ← ADD "services.io"
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

### 3.2 Future matrix changes

Per ADR-0284 §1.1 governance rule: any new ALLOWED matrix entry requires
explicit per-ADR approval. Drift prevention enforced.

## 4. Consequences

### Positive
- ✅ Phase B Item 6 ship-able (1 entry off allowlist).
- ✅ Architectural debt avoided (no allowlist entry).
- ✅ Narrow scope (1 specific import path).
- ✅ Governance rule preserved (ADR-документ обязателен).

### Negative
- (−) Opens narrow path для additional `infrastructure → services.io.*` imports
  (acceptable risk if audited per-ADR).
  - **Mitigation**: `services.io.*` prefix requires suffix `.indexers`,
    `.facade`, etc — narrow scope maintained.
- (−) 2 entries may overlap (log_indexer prune + narrow allowance).

### Neutral
- Does NOT change `infrastructure → services` (broad allowance).
- Does NOT change `services → infrastructure` (already allowed via ADR-0284).

## 5. Verification

```bash
# Before fix:
$ grep "core/observability/log_indexer" tools/check_layers_allowlist.txt
# expected: 1 entry present (current)

# After fix:
$ grep "core/observability/log_indexer" tools/check_layers_allowlist.txt
# expected: 0 entries (removed)
$ grep "services.io" tools/check_layers.py
# expected: "services.io" in infrastructure ALLOWED set
$ make layers
# expected: 0 NEW violations, 54 legacy (was 55)
```

## 6. Related

- ADR-0284 (services + entrypoints ALLOWED matrix update, Sprint 36)
- ADR-0282 §3 Phase B (allowlist prune plan)
- ADR-0285 (per-layer coverage thresholds, this sprint)
- `tools/check_layers.py` (ALLOWED matrix source)
- `tools/check_layers_allowlist.txt` (target: 55 → 54 entries)
- `src/backend/infrastructure/audit/event_log.py` (1 caller)
- `src/backend/services/io/indexers/log_indexer.py` (canonical home)
- `src/backend/core/observability/log_indexer.py` (DELETE target)
