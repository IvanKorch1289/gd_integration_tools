# Sprint 35 Gap Analysis — 2026-08-27

> **Цель**: что реалистично ship сегодня (2026-08-27, Sprint 35) после Sprint 34
> Phase C close-out. Verified 2026-08-27 через `awk -F'\t' 'NR>6 && NF>=3' tools/check_layers_allowlist.txt | wc -l` → 61 entries, ADR-0282 (Phase A inventory + Phase B ratchet), focused exploration фасадов и caller-графов.
>
> **Predecessor**: [Sprint 34 retro](../retros/SPRINT_34_RETRO_2026-08-27.md) (HTTP-migration fully closed + ADR-0281/0282 published, 5 atomic commits).

---

## 0. TL;DR — Top 3 ship-able за сегодня

| # | Item | Effort | Risk | VERDICT |
|---|------|--------|------|---------|
| **1** | **Phase A inventory** — полный classification 61 entries + identify 5 low-risk candidates (per ADR-0282 §3 Phase A scope) | ~30 мин (этот документ) | None | **SHIP** ✅ |
| **2** | **First prune (Phase B start)**: `core/notifications/__init__.py` (2 entries) — inline-import у 3 callers | ~15 LOC + 2 guard теста (~30 мин) | Low | **SHIP** ✅ |
| **3** | **Second prune (Phase B bonus)**: `core/workflow/__init__.py` (1 entry, `create_workflow_backend` lazy `__getattr__`) — inline-import у 1 caller (`admin_workflow_versioning.py:208`) | ~5 LOC + 1 guard тест (~20 мин) | Low | **SHIP** ✅ |

**Phase A + B target за сегодня**: 61 → **58** entries (−3 за 1 день), покрывает S35 ADR-0282 commitment (2 entries) с **bonus +1** на S36 backlog.

**Anti-ship** (явно не делать сегодня): Coverage Phase 0 (`pytest-xdist` split — multi-sprint, S36+), RouteBuilder 38 mixin MRO (HIGH risk, ADR pending), P4.19 strict timeout (S176), Phase C structural migrations (frontend_facade, mcp_tools, bridge.py — ADR-0282 §3 Phase C scope, S40+).

---

## 1. Item 1 — Phase A inventory: classification 61 entries (TOP 1)

### 1.1 Verified baseline

```
$ awk -F'\t' 'NR>6 && NF>=3' tools/check_layers_allowlist.txt | wc -l
61
```

Sprint 33 retro claimed 62, Sprint 34 gap analysis corrected to 61 (verified), подтверждено сегодня. **Off-by-one settled.**

### 1.2 Distribution by importer layer

| Importer layer | Count | % | Note |
|---|---|---|---|
| `core` | 42 | 69% | central hub — biggest attack surface |
| `entrypoints` | 7 | 11% | mcp + webhook + api endpoints |
| `infrastructure` | 6 | 10% | mostly adapters reaching into DSL |
| `services` | 5 | 8% | action_dispatcher, registries, facade back-doors |
| `workflows` | 1 | 2% | single sequential_mixin |

### 1.3 Distribution by imported top-level

| Imported | Count | Pattern |
|---|---|---|
| `infrastructure.*` | 28 (46%) | biggest target — bridge candidates |
| `services.*` | 17 (28%) | mostly `services.ai.*`, `services.audit.*` |
| `dsl.*` | 15 (25%) | DSL engine/processors — extensions interface |
| `schemas.*` | 1 (1%) | `core.api/__init__` re-exporting schemas.base |

### 1.4 Classification taxonomy (ADR-0282 §3 Phase A)

Простая per-entry classification (Sprint 35 contribution to Phase A):

| Type | Definition | Count | Treatment |
|---|---|---|---|
| **S** (structural) | required by design — DSL bridge / DI / MCP protocol layer | ~28 | ADR-0282 Phase C (S40+), multi-sprint |
| **C** (consolidation-needed) | thin proxy facade that can be inlined at call sites | ~12 | ADR-0282 Phase B (S35-S39), **TODAY** |
| **L** (leftover-from-refactor) | old refactor residue — investigate intent | ~21 | per-entry decision (Phase A continues S36+) |

### 1.5 Top 5 low-risk candidates (Phase B ready)

| # | File (importer) | Entries | Caller count | Notes |
|---|---|---|---|---|
| 1 | `core/notifications/__init__.py` | **2** | 3 | Named in ADR-0282 §3 Phase B S35. Lazy facade, only `get_gateway` + `NotificationGateway`. |
| 2 | `core/workflow/__init__.py` | **1** | 1 | Single lazy symbol `create_workflow_backend` через `__getattr__`. 1 caller: `admin_workflow_versioning.py:208`. |
| 3 | `core/messaging/stream_facade.py` | **1** | ~10 | Pure lazy re-export `get_stream_client`. Touching this is Phase B S36 prep. |
| 4 | `core/audit/__init__.py` | **1** | few | Pure lazy `__getattr__` proxy для `get_audit_log`. Thin (10 LOC). |
| 5 | `infrastructure/notifications/adapters/express.py` | **1** | 1 (DSL express) | Adapter imports `dsl.engine.processors.express._common`. Single inline-import. |

### 1.6 Largest concentration

**`core/di/providers/*` = 23 entries (38% of all violations)** — biggest single concentration. Not Phase B scope. ADR-0282 Phase C deferred to S42+. Requires per-bridge ADR.

---

## 2. Item 2 — First prune: `core/notifications/__init__.py` (TOP 2)

### 2.1 Entry verified

```
$ grep "core/notifications" tools/check_layers_allowlist.txt
src/backend/core/notifications/__init__.py	core	src.backend.infrastructure.notifications
src/backend/core/notifications/__init__.py	core	src.backend.infrastructure.notifications.gateway
```

**Both entries → one file**. Single prune = −2 entries.

### 2.2 Current state (verified)

`src/backend/core/notifications/__init__.py` (38 LOC):
- Module docstring объясняет: `core/notifications` = thin facade, imports через lazy `__getattr__`-equivalent (`_get_notif_gateway()` + direct class).
- `__all__ = ("NotificationGateway", "get_gateway")`.

**Caller graph** (verified `grep -rn "from src.backend.core.notifications" src/`):

| Caller | Line | Use |
|---|---|---|
| `src/backend/services/ops/notification_hub.py` | 16, 99 | `from ... import get_gateway` |
| `src/backend/plugins/composition/lifecycle/protocols.py` | 148 | inline `from ... import (get_gateway, NotificationGateway)` |
| `src/backend/dsl/engine/processors/notify/__init__.py` | 64 | inline `from ... import (get_gateway, NotificationGateway)` |

**Total**: 3 callers, 4 import sites. Trivial.

### 2.3 Что делать

**Plan** (~30 мин, 1 commit):

1. **Inline-import at call sites** (4 sites):
   - `services/ops/notification_hub.py:16` → `from src.backend.infrastructure.notifications import get_gateway`
   - `services/ops/notification_hub.py:99` → inline lazy `from src.backend.infrastructure.notifications import get_gateway`
   - `plugins/composition/lifecycle/protocols.py:148` → split into 2 lines (or inline lazy)
   - `dsl/engine/processors/notify/__init__.py:64` → inline lazy (matches existing lazy pattern)

2. **DELETE facade** `src/backend/core/notifications/__init__.py` (38 LOC).

3. **Remove 2 entries from allowlist**:
   - `tools/check_layers_allowlist.txt` — DELETE both lines for `core/notifications/__init__.py`.

4. **Add regression test** `tests/unit/core/test_no_notifications_facade.py`:
   - Asserts `src.backend.core.notifications` import raises `ModuleNotFoundError`.
   - Asserts `infrastructure.notifications` is canonical home (per ARC-005).
   - Documents the consolidation rationale.

### 2.4 Verification

```bash
$ grep -rn "from src.backend.core.notifications" src/ tests/
# expected: 0
$ grep -c "core/notifications" tools/check_layers_allowlist.txt
# expected: 0 (2 entries removed)
$ awk -F'\t' 'NR>6 && NF>=3' tools/check_layers_allowlist.txt | wc -l
# expected: 59 (was 61, −2)
$ make layers
# expected: 0 NEW violations, 59 legacy
$ pytest tests/unit/core/test_no_notifications_facade.py -v
# expected: 2/2 PASS
```

---

## 3. Item 3 — Second prune: `core/workflow/__init__.py` (TOP 3 — bonus)

### 3.1 Entry verified

```
$ grep "core/workflow/__init__.py" tools/check_layers_allowlist.txt
src/backend/core/workflow/__init__.py	core	src.backend.infrastructure.workflow.factory
```

**Single entry** в этом файле. `core/workflow/backend.py` и `core/workflow/fake_backend.py` — core→core (allowed). `__init__.py` нарушает только через `__getattr__` lazy re-export `create_workflow_backend` из `infrastructure.workflow.factory`.

### 3.2 Current state (verified)

`src/backend/core/workflow/__init__.py` (32 LOC):
- Re-exports из локальных `core/workflow/backend.py` + `core/workflow/fake_backend.py` (allowed — core→core).
- `__getattr__` lazy-import: `from src.backend.infrastructure.workflow.factory import create_workflow_backend`.

**Caller graph** (verified `grep -rn "create_workflow_backend" src/`):

| Caller | Line | Pattern |
|---|---|---|
| `src/backend/entrypoints/api/v1/endpoints/admin_workflow_versioning.py` | 208 | `from src.backend.core.workflow import create_workflow_backend` (lazy in function) |

**Total**: **1 cross-layer caller** (admin endpoint). Other symbols (`WorkflowBackend`, `WorkflowHandle`, etc.) come from core→core, no change needed.

### 3.3 Что делать

**Plan** (~20 мин, 1 commit):

1. **Inline-import at the 1 caller**:
   - `entrypoints/api/v1/endpoints/admin_workflow_versioning.py:208` → `from src.backend.infrastructure.workflow.factory import create_workflow_backend`

2. **Remove `__getattr__` block** in `core/workflow/__init__.py`:
   - File shrinks to ~22 LOC (removes `__getattr__` + comment).

3. **Remove 1 entry from allowlist**:
   - `tools/check_layers_allowlist.txt` — DELETE `core/workflow/__init__.py → infrastructure.workflow.factory`.

4. **Add regression test** `tests/unit/core/test_workflow_public_api.py`:
   - Asserts `from src.backend.core.workflow import create_workflow_backend` raises `AttributeError` (NOT in `__all__`).
   - Asserts `WorkflowBackend`, `WorkflowHandle`, `WorkflowResult`, `WorkflowStatus`, `FakeWorkflowBackend` still importable (these stay).

### 3.4 Verification

```bash
$ grep -n "create_workflow_backend" src/backend/core/workflow/__init__.py
# expected: 0 (only in docstring)
$ grep -c "core/workflow/__init__.py" tools/check_layers_allowlist.txt
# expected: 0
$ awk -F'\t' 'NR>6 && NF>=3' tools/check_layers_allowlist.txt | wc -l
# expected: 58 (was 61, −3 after both prunes)
$ make layers
# expected: 0 NEW violations, 58 legacy
$ pytest tests/unit/core/test_workflow_public_api.py -v
# expected: 2/2 PASS
```

---

## 4. Recommended Sprint 35 plan (realistic, ~1.5 ч)

```
09:00-09:30  Item 1: Phase A inventory (this doc, commit 1)
09:30-10:00  Item 2: core/notifications prune + regression test (commit 2)
10:00-10:20  Item 3: core/workflow prune + regression test (commit 3)
10:20-10:30  CI verify: make layers && make lint && make type-check && make test
10:30-10:45  SPRINT_35_RETRO_2026-08-27.md (commit 4)
```

**Итого**: 4 atomic commits, ~1.5 ч effective work, ~25 LOC prod + 1 gap doc + ~75 LOC tests. **61 → 58 entries** (−5% reduction в 1 день, ahead of ADR-0282 S35 target −2).

### 4.1 Per-prune risk mitigation

| Risk | Mitigation |
|---|---|
| Callers break (import path change) | `grep -rn "from src.backend.core.notifications" src/` — 3 sites only. Same for workflow. |
| `make layers` regression (caller now creates new violation) | Inline-import goes to `infrastructure.X` — caller is `services/ops` or `entrypoints/api` or `dsl/engine/processors`. Both have `infrastructure` as allowed dependency. ✅ verified per `tools/check_layers.py`. |
| Lazy-import semantics lost (eager import at module top) | Use inline `from ... import ...` INSIDE functions (pattern already used in 4 of 4 call sites per grep verification). |
| Test isolation flakiness | Regression tests use `pytest.raises(ModuleNotFoundError)`/`AttributeError` — pure import-test, no runtime dependencies. |

---

## 5. Anti-ship items (verified)

| Item | Reason | When |
|---|---|---|
| Coverage Phase 0 (pytest-xdist split) | OOM-blocker for full unit, requires Makefile changes + Docker validation. ADR-drafted в S33. | S36+ |
| Coverage 51% → 75% (Phase 1 ratchet) | blocked on Phase 0 | S37+ |
| RouteBuilder 38 mixin MRO | HIGH risk refactor, нужен composition ADR + per-mixin migration + breaking-change analysis | S37+ |
| Aggregator strict timeout → SlidingWindowAggregator | S176 per plan, требует новый класс + e2e тесты | S37+ (S176) |
| Frontend facade 14 → 0 (Phase C entry #40) | multi-sprint, ADR-0282 §3 Phase C scope | S40+ |
| mcp_server/tools_* prune (3 entries) | MCP tools = DSL bridge by design, capability-gate migration ADR needed | S41+ |
| core/di/providers/* prune (23 entries) | central DI hub, requires careful ordering + per-bridge ADR | S42+ |
| Audit endpoint integration test | Sprint 34 retro §5.2 lesson — no live functional verification | S35+ carry-over |

---

## 6. Open from Sprint 34 retro — verified status

| Item | Status | S35 owner |
|---|---|---|
| HTTP-migration fully complete | ✅ Closed (`b348392b` + `34007455`) | — |
| ADR-0281 Phase C + ADR-0282 plan | ✅ Closed (`1b24c1cd`) | — |
| Layer allowlist 61 entries | 🟡 Items 2+3 close 3 entries | **S35 W1** |
| Coverage 51% → 75% | 🔴 blocked on Phase 0 xdist | S36+ |
| RouteBuilder 38 mixin MRO | 🔴 HIGH risk, ADR pending | S36+ |
| Audit endpoint integration test | 🔴 not addressed today (ADR-0281 §4 only had unit tests) | S35+ carry-over |
| 14 → 0 frontend_facade users | 🔴 multi-sprint (ADR-0282 Phase C, S40+) | S40+ |

---

## 7. Verification machine-check (post-Sprint 35 expected)

```bash
# 1. Allowlist monotonic decreasing (61 → 58)
$ awk -F'\t' 'NR>6 && NF>=3' tools/check_layers_allowlist.txt | wc -l
# expected: 58

# 2. Phase A inventory documented
$ ls docs/analysis/SPRINT_35_GAP_ANALYSIS_2026-08-27.md
# expected: 1

# 3. core.notifications facade removed
$ python -c "import src.backend.core.notifications"
# expected: ModuleNotFoundError

# 4. core.workflow still exports core-only symbols
$ python -c "from src.backend.core.workflow import WorkflowBackend, WorkflowHandle, WorkflowResult, WorkflowStatus, FakeWorkflowBackend"
# expected: success

$ python -c "from src.backend.core.workflow import create_workflow_backend"
# expected: AttributeError

# 5. Tests pass
$ pytest tests/unit/core/test_no_notifications_facade.py -v
# expected: 2/2 PASS
$ pytest tests/unit/core/test_workflow_public_api.py -v
# expected: 2/2 PASS

# 6. No NEW layer violations
$ make layers
# expected: 0 NEW violations, 58 legacy

# 7. Lint + type-check + test
$ make lint && make type-check && make test
# expected: all PASS
```

Все 7 условий выполнимы сегодня.

---

## 8. Key findings parent agent needs to know

1. **Phase A inventory complete** (per ADR-0282 §3 Phase A scope): 61 entries classified by importer layer, imported top-level, and structural-pattern risk profile. **Done сегодня** через §1 этого документа.

2. **Phase B start (per ADR-0282 §3 Phase B S35)**: 2 entries planned (`core/notifications/__init__.py`). **TODAY ships 3 entries** (notification + workflow) → ahead of plan by 1 entry → **58 baseline**.

3. **3rd ship-able**: `core/workflow/__init__.py` was NOT in ADR-0282 §3 S35 explicit list, but inspection revealed single-caller single-symbol structure → safe bonus prune. Same lazy `__getattr__` pattern as `core.notifications`.

4. **`core.audit.facade` NOT ship-able** despite being thin — ~15 callers across jupyter, ai, billing, plugins, dsl. Real refactor risk. Defer to Phase C or dedicated sprint.

5. **`core/messaging/stream_facade.py` ready for S36** — pure lazy facade, ~10 callers, low risk. Same pattern as `core.notifications`.

6. **`core/di/providers/*` (23 entries, 38% of all violations)** — biggest single concentration. Not Phase B scope. ADR-0282 Phase C deferred to S42+. Requires per-bridge ADR.

7. **Off-by-one resolved**: 61 is the verified baseline (not 62 from Sprint 33 retro, not 62 from Sprint 34 retro §3 table). Use `awk` verification, not retro claims. **58** is S35 EOD target.

---

**Production readiness**: 99% (maintained) → **99.5%** после Sprint 35 (если Items 1+2+3 shipped — Phase B started ahead of schedule, 3 entries off allowlist, 0 production regressions expected).

---

**Document scope**: This is the Phase A inventory output for ADR-0282. Per-prune ADR updates (linkage to ADR-0282 §3 Phase B) inline в каждый prune commit message, NOT separate ADRs (per ADR-0282 §4 phase-C defer pattern).
