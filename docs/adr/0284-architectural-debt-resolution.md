# ADR-0284: Architectural debt resolution (services + entrypoints → infrastructure)

> **Status**: ACCEPTED (2026-08-27).
> **Method**: ALLOWED matrix update (Variant A, smallest blast radius).
> **Scope**: Closes Sprint 35 architectural debt (services→infra, entrypoints→infra).
> **Date**: 2026-08-27.
> **Linked**: ADR-0282 §3 Phase B (layer allowlist prune plan).

## 0. Контекст

Per `SPRINT_35_RETRO_2026-08-27.md` §2 critical lesson: **core-facade removal
ALWAYS reveals caller-side layer violations**. Sprint 35 created 2 new
allowlist entries при removing `core.notifications` и `core.workflow.__getattr__`:

| Entry | Importer layer | Imported |
|---|---|---|
| 1 | `services` | `infrastructure.notifications` |
| 2 | `entrypoints` | `infrastructure.workflow.factory` |

Pre-existing (NOT Sprint 35):
| 3 | `services` | `infrastructure.observability.mq_trace_propagator` |

`SPRINT_36_GAP_ANALYSIS_2026-08-27.md` §2 explored 3 variants:

| Variant | Description | VERDICT |
|---|---|---|
| **A** | Update `tools/check_layers.py` ALLOWED matrix | ✅ ADOPT (this ADR) |
| B | Hybrid facade pattern (NS-3 cycle 32) | ❌ Regressive — repeats anti-pattern |
| C | Status quo + accept debt | ❌ Leads to debt accumulation |

## 1. Решение

**Update ALLOWED matrix** (`tools/check_layers.py`):

```python
# Before:
ALLOWED: dict[str, set[str]] = {
    "core": set(),
    "infrastructure": {"core", "schemas"},
    "services": {"core", "schemas"},  # ← ADD "infrastructure"
    "entrypoints": {"services", "schemas", "core"},  # ← ADD "infrastructure"
    "schemas": {"core"},
    "dsl": {"core", "infrastructure", "services", "entrypoints", "schemas"},
    "workflows": {"core", "infrastructure", "services", "entrypoints", "schemas"},
}

# After:
ALLOWED: dict[str, set[str]] = {
    "core": set(),
    "infrastructure": {"core", "schemas"},
    "services": {"core", "schemas", "infrastructure"},
    "entrypoints": {"services", "schemas", "core", "infrastructure"},
    "schemas": {"core"},
    "dsl": {"core", "infrastructure", "services", "entrypoints", "schemas"},
    "workflows": {"core", "infrastructure", "services", "entrypoints", "schemas"},
}
```

### 1.1 Governance rule

**Future ALLOWED matrix changes require per-ADR approval** (closes floodgate risk):

- ✅ Adding new layer-to-layer dependency → MUST file ADR
- ✅ Removing existing dependency → MUST file ADR
- ✅ Comments in `tools/check_layers.py` document this requirement

### 1.2 Removal plan

3 entries removed from `tools/check_layers_allowlist.txt`:
1. `services/ops/notification_hub.py → infrastructure.notifications`
2. `entrypoints/api/v1/endpoints/admin_workflow_versioning.py → infrastructure.workflow.factory`
3. `services/messaging/kafka_facade.py → infrastructure.observability.mq_trace_propagator`

## 2. Consequences

### Positive
- ✅ **3 entries off allowlist** (61 → **58**, honest net: 60 → 58 + 2 new from other agents).
- ✅ Architectural honesty: `services` и `entrypoints` legitimate consumers of `infrastructure`.
- ✅ Unblocks future Phase B prunes (no new debt created per prune).
- ✅ Aligns с extensions pattern (extensions ALREADY allowed infrastructure directly).

### Negative
- (−) Opens floodgate: future services/entrypoints→infra imports без review = drift risk.
  - **Mitigation**: governance rule (per-ADR approval для matrix changes).
- (−) Slightly broader cross-layer surface.
  - **Mitigation**: per-ADR per-entry audit при matrix edits.

### Neutral
- Does NOT change extension boundary (frontend→core only).
- Does NOT change core→infra (still forbidden — core = leaf).

## 3. Alternatives considered

### Variant B: Hybrid facade (NS-3 cycle 32 pattern)

Add `core/X/__init__.py` thin facades:
- `core/notifications_gateway/__init__.py`
- `core/workflow_factory/__init__.py`
- `core/mq_trace/__init__.py`

**Rejected**: Contradicts ADR-0282 §3 Phase B (which deletes core facades).
Adds 3 new facades — exactly what Sprint 35 was deleting. **Regressive**.

### Variant C: Status quo + accept debt

Continue adding allowlist entries + inline ADR follow-up notes.

**Rejected**: Debt accumulates (60 → 65 → 70 entries за несколько sprints).
Reviewer confusion: "architectural debt vs real violation?". ADR-0282 §3
"60 → 50 за 5 sprints" target becomes нереальным.

## 4. Verification

```bash
$ grep -A2 "ALLOWED: dict" tools/check_layers.py
# expected: services + infrastructure, entrypoints + infrastructure
$ awk -F'\t' 'NR>6 && NF>=3' tools/check_layers_allowlist.txt | wc -l
# expected: 58 (was 61)
$ make layers
# expected: 0 NEW violations, 58 legacy
$ pytest tests/unit/core/test_no_notifications_facade.py tests/unit/core/test_workflow_public_api.py -v
# expected: 8/8 PASS (no regression — Sprint 35 callers still work)
```

## 5. Related

- ADR-0282 §3 Phase B (layer allowlist prune plan)
- ADR-0281 (HTTP-migration Phase C close-out) — sibling architecture ADR
- `SPRINT_35_RETRO_2026-08-27.md` §2 (critical lesson "core-facade removal reveals caller debt")
- `SPRINT_36_GAP_ANALYSIS_2026-08-27.md` §2 (Variant A recommendation)
- `tools/check_layers.py` (ALLOWED matrix source)
- `tools/check_layers_allowlist.txt` (baseline 61 → 58 entries)
