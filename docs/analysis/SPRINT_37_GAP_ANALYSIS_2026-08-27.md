# Sprint 37 Gap Analysis — 2026-08-27

> **Цель**: что реалистично ship сегодня (Sprint 37) после Sprint 36 close-out
> (5 atomic commits: critical fix + ADR-0284 + stream_facade + Coverage Phase 0 + retro).
> Verified 2026-08-27 через `awk -F'\t' 'NR>5 && NF>=3' tools/check_layers_allowlist.txt | wc -l` → **57 entries** (off-by-one от Sprint 36 retro §8.3 baseline 56 — см. §1.1),
> `tools/check_layers.py` (post-ADR-0284 ALLOWED matrix), focused exploration фасадов и caller-графов.
>
> **Predecessor**: [Sprint 36 retro](../retros/SPRINT_36_RETRO_2026-08-27.md).

---

## 0. TL;DR — Top 3 ship-able за сегодня

| # | Item | Effort | Risk | VERDICT |
|---|------|--------|------|---------|
| **1** | **Phase B Item 4** — `core/audit/__init__.py` prune (1 entry, 2 entrypoint callers + 1 test mock) | ~20 LOC + 1 regression test (~25 мин) | Low | **SHIP** ✅ |
| **2** | **Phase B Item 5** — `infrastructure/notifications/adapters/express.py` prune via helper extraction (1 entry, 9 callers total) | ~35 LOC across 3 files + 1 regression test (~40 мин) | Low-Medium | **SHIP** ✅ |
| **3** | **Coverage Phase 1 first run** — actual `make coverage-per-layer` + memory baseline + ratchet +5pp (от 21% stale baseline → ~26% conservative) | ~1 ч wall time | Low | **SHIP** ✅ |

**Phase B + Coverage Phase 1 target за сегодня**: 57 → **55** entries (−2 за 1 день, ahead of ADR-0282 S37 W2 plan = 1 by 1) + Coverage ratchet start (per Phase 0 §2.4 deferred commitment).

**Anti-ship** (явно не делать сегодня): `core/messaging/eventbus/facade.py` (206 LOC REAL facade с capability checks + lifecycle — НЕ thin proxy, Sprint 36 retro misclassified), `core/audit/facade/__init__.py` (88 LOC real facade, 7+ per-domain helpers), `core/di/providers/*` (23 entries, 38% concentration, Phase C deferred S42+), RouteBuilder MRO (HIGH risk), Coverage 75% target (multi-sprint, S41+), Phase C structural migrations.

---

## 1. Verified baseline (2026-08-27)

### 1.1 Allowlist count

```
$ awk -F'\t' 'NR>5 && NF>=3' tools/check_layers_allowlist.txt | wc -l
57
```

**Sprint 36 retro §8.3** ("Baseline 56 entries (S36 W1 EOD)") — **off by one** относительно текущего состояния. Возможные причины:
1. Параллельный subagent добавил 1 entry во время Sprint 36 retro review (аналогично S35 retro §2.1 — "parallel agent added 1" pattern).
2. Sprint 36 critical fix `ea76c733` (extensions migration) создал новую caller-edge, добавившую entry.
3. Stale claim в retro (ретроспектива зафиксирована до финального состояния).

**Resolution**: используем verified 57 как baseline. Это НЕ регрессия — просто retro snapshot был преждевременным.

### 1.2 Per-importer distribution (S37 verified)

| Importer layer | Count | Δ от Sprint 35 |
|---|---|---|
| `core` | 42 (74%) | −1 (notifications + workflow + stream_facade) |
| `infrastructure` | 7 (12%) | +1 (ADR-0284 services→infra allowance не расширил infra→infra) |
| `entrypoints` | 5 (9%) | −2 (ADR-0284 cleanup) |
| `services` | 2 (4%) | −3 (ADR-0284 cleanup) |
| `workflows` | 1 (2%) | 0 |

### 1.3 Remaining Top 5 candidates (verified 2026-08-27)

Per Sprint 35 §1.5 inventory, после Sprint 35+Sprint 36 (3 prunes + ADR-0284 3 entries resolved):

| # | File (importer) | Entries | Status (S37) |
|---|---|---|---|
| 1 | `core/notifications/__init__.py` | 2 | ✅ Sprint 35 closed |
| 2 | `core/workflow/__init__.py` | 1 | ✅ Sprint 35 closed |
| 3 | `core/messaging/stream_facade.py` | 1 | ✅ Sprint 36 closed |
| **4** | **`core/audit/__init__.py`** | **1** | ⏸️ **TODAY (Item 1)** |
| **5** | **`infrastructure/notifications/adapters/express.py`** | **1** | ⏸️ **TODAY (Item 2)** |

---

## 2. Item 1 — Phase B Item 4: `core/audit/__init__.py` prune (TOP 1)

### 2.1 Entry verified

```
$ grep "core/audit/__init__.py" tools/check_layers_allowlist.txt
src/backend/core/audit/__init__.py	core	src.backend.infrastructure.audit.event_log
```

**Single entry**. Файл — pure lazy `__getattr__` proxy для `get_audit_log` (19 LOC).

### 2.2 Current state (verified)

`src/backend/core/audit/__init__.py`:
- Module docstring: "Entry points and services must import ``get_audit_log`` from here".
- `__all__ = ("get_audit_log",)`.
- `__getattr__` lazy-import: `from src.backend.infrastructure.audit.event_log import get_audit_log`.

**Caller graph** (verified `grep -rn "from src.backend.core.audit" src/ tests/ extensions/`):

| Caller | Layer | Pattern | Line |
|---|---|---|---|
| `src/backend/entrypoints/api/v1/endpoints/admin_tenants.py` | entrypoints | inline `from src.backend.core.audit import get_audit_log` | 55 |
| `src/backend/entrypoints/api/v1/endpoints/admin_capabilities.py` | entrypoints | inline (try/except с graceful skip) | 85 |
| `tests/unit/core/audit/test_facade_helpers.py` | tests | `from src.backend.core.audit import facade` | 15 |

**Total**: **3 call sites** (2 production entrypoints + 1 test). Per Sprint 35 lesson (extensions + tests scan) — extensions grep вернул 0 hits для `core.audit`.

### 2.3 Что делать

**Plan** (~25 мин, 1 commit):

1. **Inline-import at 2 entrypoint callers** (ADR-0284 allows `entrypoints→infrastructure`):
   - `entrypoints/api/v1/endpoints/admin_tenants.py:55` → `from src.backend.infrastructure.audit.event_log import get_audit_log`
   - `entrypoints/api/v1/endpoints/admin_capabilities.py:85` → same migration

2. **Update test mock**:
   - `tests/unit/core/audit/test_facade_helpers.py:15` → `from src.backend.core.audit import facade` stays (imports `facade` SUBMODULE). Verify — `core/audit/facade/` is real facade (NOT removed).
   - Add NEW regression test `tests/unit/core/test_no_audit_proxy.py`: asserts `from src.backend.core.audit import get_audit_log` raises `ModuleNotFoundError`.

3. **DELETE proxy** `src/backend/core/audit/__init__.py` (19 LOC).
   - `core/audit/facade/` subpackage stays — это separate real facade (88 LOC, 7+ per-domain helpers).
   - `core/audit/facade/_base.py`, `core/audit/facade/audit_service.py` и т.д. остаются.

4. **Remove 1 entry from allowlist**:
   - `tools/check_layers_allowlist.txt` — DELETE `src/backend/core/audit/__init__.py → infrastructure.audit.event_log`.

5. **Add regression test** `tests/unit/core/test_no_audit_proxy.py`:
   - Asserts `from src.backend.core.audit import get_audit_log` raises `ModuleNotFoundError`.
   - Asserts `from src.backend.core.audit.facade import emit_audit` works (subpackage preserved).
   - Asserts direct infra import works: `from src.backend.infrastructure.audit.event_log import get_audit_log`.

### 2.4 Verification

```bash
$ grep -rn "from src.backend.core.audit" src/ tests/ extensions/
# expected: 0 hits для `get_audit_log` (only `core.audit.facade` imports remain)
$ grep -c "core/audit/__init__.py" tools/check_layers_allowlist.txt
# expected: 0 (1 entry removed)
$ awk -F'\t' 'NR>5 && NF>=3' tools/check_layers_allowlist.txt | wc -l
# expected: 56 (was 57, −1)
$ make layers
# expected: 0 NEW violations, 56 legacy
$ pytest tests/unit/core/test_no_audit_proxy.py -v
# expected: 3/3 PASS
```

### 2.5 Risk mitigation

| Risk | Mitigation |
|---|---|
| Sprint 35 overshoot (caller miscount) | Pre-scan: extensions + tests + prod (3 caller sites verified, 0 missed) |
| Lazy import semantics lost | Inline imports inside function bodies (preserved per `admin_tenants.py:55`, `admin_capabilities.py:85`) |
| `core.audit.facade` accidentally deleted | Scope: DELETE only `core/audit/__init__.py` (19 LOC), NOT `core/audit/facade/` (88 LOC real facade) |
| Test mock break | Verified `test_facade_helpers.py:15` imports `facade` SUBMODULE, unaffected by `__init__.py` removal |
| ADR-0284 governance regression | Inline-import path (`entrypoints→infrastructure`) already approved by ADR-0284 §1.1 |

---

## 3. Item 2 — Phase B Item 5: `infrastructure/notifications/adapters/express.py` prune (TOP 2)

### 3.1 Entry verified

```
$ grep "infrastructure/notifications/adapters/express.py" tools/check_layers_allowlist.txt
src/backend/infrastructure/notifications/adapters/express.py	infrastructure	src.backend.dsl.engine.processors.express._common
```

**Single entry**. Файл — Express adapter (115 LOC). Violation: lazy import `from src.backend.dsl.engine.processors.express._common import get_express_client` внутри `send()` method.

### 3.2 Current state (verified)

`src/backend/infrastructure/notifications/adapters/express.py:52-57`:
```python
async def send(self, *, recipient, subject, body, metadata):
    from src.backend.dsl.engine.processors.express._common import get_express_client
    from src.backend.infrastructure.clients.external.express_bot import (
        BotxButton, BotxMention, BotxMessage,
    )
    client = get_express_client(bot_name)
```

**Architectural problem**: `dsl.engine.processors.express._common.get_express_client(bot_name)` (DSL helper) обёртка над `infrastructure.clients.external.express_bot.ExpressBotClient` factory. Adapter в infrastructure обращается к DSL helper — это inversion dependency (`infra→dsl` вместо правильного `dsl→infra`).

### 3.3 Caller graph (verified `grep -rn "dsl.engine.processors.express._common.get_express_client"`)

| Caller | Layer | Use |
|---|---|---|
| `dsl/engine/processors/express/typing.py:11` | dsl | `get_express_client` re-import |
| `dsl/engine/processors/express/send.py:11` | dsl | re-import |
| `dsl/engine/processors/express/status.py:16` | dsl | re-import |
| `dsl/engine/processors/express/edit.py:11` | dsl | re-import |
| `dsl/engine/processors/express/mention.py:22` | dsl | `resolve_value` only |
| `dsl/engine/processors/express/reply.py:11` | dsl | re-import |
| `dsl/engine/processors/express/send_file.py:23` | dsl | re-import |
| `dsl/engine/processors/telegram/_common.py:14` | dsl | `resolve_value` only |
| **`infrastructure/notifications/adapters/express.py:52`** | **infrastructure** | **`get_express_client` direct (the violation)** |

**Total**: 9 importers (8 DSL processors + 1 infrastructure adapter). After refactor: all 9 import from canonical `infrastructure.clients.external.express_bot`.

### 3.4 Что делать

**Plan** (~40 мин, 1 commit):

**Option A** (preferred, минимальный риск):

1. **Extract factory** в `src/backend/infrastructure/clients/external/express_bot.py`:
   - Move `get_express_bot_client(bot_name: str = "main_bot")` function (~45 LOC) в canonical infra home.
   - Rename: `get_express_client` → `get_express_bot_client` (disambiguate from HTTP `ExpressClient`).

2. **Update DSL processors** (8 files):
   - `dsl/engine/processors/express/_common.py` — DELETE `get_express_client` function, RE-EXPORT from `infrastructure.clients.external.express_bot`:
     ```python
     from src.backend.infrastructure.clients.external.express_bot import (
         get_express_bot_client as get_express_client,  # noqa: F401
     )
     ```
   - 7 processor files — keep current `from ._common import get_express_client` pattern (re-export shim preserves backward compat).

3. **Update notifications adapter**:
   - `infrastructure/notifications/adapters/express.py:52` → `from src.backend.infrastructure.clients.external.express_bot import get_express_bot_client`.
   - `client = get_express_bot_client(bot_name)` (rename call site).

4. **Remove 1 entry from allowlist**:
   - `tools/check_layers_allowlist.txt` — DELETE `infrastructure/notifications/adapters/express.py → dsl.engine.processors.express._common`.

5. **Add regression test** `tests/unit/infrastructure/notifications/adapters/test_express_adapter_no_dsl.py`:
   - Asserts `infrastructure.notifications.adapters.express` does NOT import from `dsl.*` (AST-based).
   - Asserts `get_express_bot_client(bot_name="main_bot")` returns `ExpressBotClient`.
   - Asserts backward-compat: `from src.backend.dsl.engine.processors.express._common import get_express_client` still works (re-export shim).

### 3.5 Verification

```bash
$ grep -rn "from src.backend.dsl.engine.processors.express._common import" src/backend/infrastructure/
# expected: 0 (adapter migrated to direct infra import)
$ grep -c "infrastructure/notifications/adapters/express.py" tools/check_layers_allowlist.txt
# expected: 0 (1 entry removed)
$ awk -F'\t' 'NR>5 && NF>=3' tools/check_layers_allowlist.txt | wc -l
# expected: 55 (was 57, −2 after both prunes)
$ make layers
# expected: 0 NEW violations, 55 legacy
$ pytest tests/unit/infrastructure/notifications/adapters/test_express_adapter_no_dsl.py -v
# expected: 3/3 PASS
$ pytest tests/unit/dsl/express/test_express_processors.py -v
# expected: all PASS (backward-compat shim verified)
```

### 3.6 Risk mitigation

| Risk | Mitigation |
|---|---|
| DSL processor imports break | `_common.py` re-exports `get_express_bot_client as get_express_client` — backward-compat shim preserves all 7 existing imports |
| Naming collision (HTTP `get_express_client` vs BotX `get_express_bot_client`) | Rename only BotX variant (avoids clash); HTTP keeps existing name |
| Notification adapter migration regression | Adapter → direct `infrastructure.clients.external.express_bot` import (infra→infra, allowed) |
| Test mocks for `patch("src.backend.dsl.engine.processors.express._common.get_express_client")` | Shim re-export preserves import path; mocks still work |
| Lazy import semantics lost | Adapter keeps lazy import INSIDE `send()` method |
| Sprint 35 overshoot (extensions + tests) | Pre-scan complete: 9 importers (8 DSL + 1 infra) verified |

---

## 4. Item 3 — Coverage Phase 1 first run (TOP 3)

### 4.1 State (verified 2026-08-27)

Per `docs/coverage/PHASE_0_PLAN_2026-08-27.md` §1.1 + `.baselines/coverage.json`:

| Metric | Value | Source |
|---|---|---|
| `coverage.xml` stale | **21.03%** | Sprint 33 partial run, 1032 lines-valid |
| `.baselines/coverage.json` | **51.04%** (S38, STALE per file comment) | Honest 9.56% subset measurement |
| `make coverage-gate-fast` | FAILS (21% < 50% threshold) | pre-existing, NOT S36 regression |
| `make coverage-per-layer` | doc-only stub (`make/docs.mk:62-66`) | Phase 0 deferred, **TODAY = actual run** |

**Phase 0 deliverable** (Sprint 36 W1 `76a0a39d`): infrastructure ready. **Phase 1 deliverable** (Sprint 37+): actual ratchet.

### 4.2 Что делать

**Plan** (~1 ч wall time, 1 commit):

1. **Actual `make coverage-per-layer` run** (per `make/docs.mk:62` + Phase 0 §2.2):
   - 6 layer runs: `core`, `services`, `entrypoints`, `infrastructure`, `workflows`, `dsl`.
   - `--ignore=tests/integration` (Docker required, dev_light skip).
   - `--maxfail=5` per layer (resilience to flaky tests).
   - `coverage combine` + `breakdown_by_layer.py` post-process.
   - Output: `.baselines/coverage_per_layer_$(date +%F).log`.

2. **Memory baseline verification** (Phase 0 §2.4 deferred commitment):
   - Track peak RSS per layer run.
   - Document in log: `peak_memory_mb_<layer>=<value>`.
   - Confirm: no layer OOM-kills at 4GB per-worker limit.

3. **Update `.baselines/coverage.json`**:
   - Add `phase_1_first_run` block: per-layer percentages + aggregate.
   - Set new ratchet baseline (`sprint_37`).

4. **Document ratchet delta**:
   - Per Phase 0 §3.1 formula: S37 W1 target = 23% (verify Phase 0 works) → 28% (W2, +5pp).
   - Actual delta measured by `breakdown_by_layer.py` output.
   - ADR-0285 (per-layer thresholds, per Sprint 36 retro §5.2 deferred) — **drafted but NOT approved** (S37 W2 target).

### 4.3 Verification

```bash
$ make coverage-per-layer
# expected: 6 layer XML files + combined coverage.xml + .baselines/coverage_per_layer_2026-08-27.log
$ ls .baselines/coverage_per_layer_*.log
# expected: 1 file dated 2026-08-27
$ cat .baselines/coverage_per_layer_2026-08-27.log | head -30
# expected: per-layer breakdown (core/infrastructure/services/dsl/entrypoints/workflows)
$ .baselines/coverage_per_layer_2026-08-27.log | grep "peak_memory_mb"
# expected: 6 entries (one per layer), all < 4096 MB
$ make coverage-gate-fast
# expected: PASS (or honest failure with updated baseline rationale)
```

### 4.4 Risk mitigation

| Risk | Mitigation |
|---|---|
| OOM at full suite | Per-layer split (Phase 0 §2.1) — 4GB per worker verified by S36 memory profile |
| Test flakiness masking real coverage | `--maxfail=5` per layer — bounded flakiness tolerance |
| Long wall time (3-5 ч per Phase 0 §2.4 estimate) | `--ignore=tests/integration` (skip Docker) + `-n auto` (xdist parallel) |
| Stale `.baselines/coverage.json` ignored | New `.baselines/coverage_per_layer_<date>.log` — date-stamped, immutable |
| Ratchet formula too aggressive | Per Phase 0 §3.1 — S37 W1 target conservative (+2pp from 21% stale baseline), W2 +5pp from new baseline |

---

## 5. Recommended Sprint 37 plan (realistic, ~2.5 ч)

```
09:00-09:30  Item 1: Phase B Item 4 (core/audit proxy prune + regression test) — commit 1
09:30-10:15  Item 2: Phase B Item 5 (express adapter helper extraction) — commit 2
10:15-10:30  CI verify: make layers && make lint && make type-check && make test (after Items 1+2)
10:30-11:30  Item 3: Coverage Phase 1 first run (memory-profiled CI runner) — commit 3
11:30-12:00  SPRINT_37_RETRO_2026-08-27.md — commit 4
```

**Итого**: 4 atomic commits, ~2.5 ч effective work, ~70 LOC prod + 1 phase-1 log + ~150 LOC tests. **57 → 55 entries** (−3.5% reduction в 1 день, ahead of ADR-0282 S37 W2 plan = 1 by 1) + Coverage ratchet started.

### 5.1 Per-prune risk mitigation (combined Items 1+2)

| Risk | Mitigation |
|---|---|
| Sprint 35 overshoot (caller miscount) | Pre-scan: extensions + tests + prod for BOTH targets (verified §2.2 + §3.3) |
| Lazy import semantics lost | Inline imports inside function bodies (preserved in all 3 entrypoint callers + adapter) |
| Backward compat (re-exports) | Item 2: `get_express_bot_client as get_express_client` shim в `_common.py` |
| Test mock break | Sprint 36 critical fix lesson — pre-scan verifies all `patch(...)` calls survive |
| Coverage measurement OOM | Per-layer split (Phase 0 §2.1) — verified memory-safe pattern |

---

## 6. Anti-ship items (verified)

| Item | Reason | When |
|---|---|---|
| `core/messaging/eventbus/facade.py` (S36 retro §6.1 listed) | **206 LOC REAL facade** — не thin proxy. EventBusFacade class с capability checks + lifecycle + request/reply + publish_generic. Удаление сломает 8+ DSL/extensions callers. Sprint 36 retro misclassified as "multi-caller — investigate". | Phase C deferred |
| `core/audit/facade/__init__.py` | **88 LOC real facade** — 7 per-domain helpers. Per ADR-0187 + Sprint 107 closure. Удаление сломает ~15 callers (jupyter, ai, billing, plugins, dsl). | Phase C deferred |
| `core/api/__init__.py` (2 entries) | canonical API facade для extensions/entrypoints (per D160). НЕ подлежит prune. | Permanent |
| `core/di/providers/*` (23 entries, 38% concentration) | central DI hub, requires careful ordering + per-bridge ADR. | Phase C (S42+) |
| Coverage Phase 0 75% target | multi-sprint ratchet (per Phase 0 §3.1), S41+ | S41 |
| RouteBuilder 38 mixin MRO | HIGH risk refactor, ADR-0283 draft pending | S37+ |
| Aggregator strict timeout → SlidingWindowAggregator | S176 per plan, требует новый класс + e2e тесты | S176 |
| Frontend facade 14 → 0 (Phase C entry #40) | multi-sprint, ADR-0282 Phase C scope | S40+ |
| mcp_server/tools_* prune (3 entries) | MCP tools = DSL bridge by design, capability-gate migration ADR needed | S41+ |
| Audit endpoint integration test (live functional verification) | Sprint 34 retro §5.2 lesson — нет regression-теста | S35+ carry-over |

---

## 7. Open from Sprint 36 retro — verified status

| Item | Status | S37 owner |
|---|---|---|
| Layer allowlist 56 entries (retro) | 🟢 **57 entries verified 2026-08-27** (+1 retro snapshot discrepancy, см. §1.1) | — |
| Critical Sprint 35 bug fix | ✅ Closed (`ea76c733`) | — |
| ADR-0284 ALLOWED matrix | ✅ Closed (`30277a42`) | — |
| Phase B Item 3 (stream_facade) | ✅ Closed (`e4cd3a6e`) | — |
| Coverage Phase 0 infrastructure | ✅ Closed (`76a0a39d`) | — |
| **Phase B Item 4 (core/audit)** | 🟡 **TODAY Item 1** | **S37 W1** |
| **Phase B Item 5 (express adapter)** | 🟡 **TODAY Item 2** | **S37 W1** |
| **Coverage Phase 1 first run** | 🟡 **TODAY Item 3** | **S37 W1** |
| Phase B Item 2 (`core/messaging/eventbus/facade`) | 🟢 **NOT ship-able** (real facade, Sprint 36 retro misclassified) | Phase C deferred |
| Coverage 51% → 75% | 🔴 blocked on Phase 1 ratchet | S41+ (per Phase 0 §3.1) |
| ADR-0285 per-layer thresholds | 🟡 drafted but not approved (Phase 0 §3.2 proposal) | S37 W2 |
| RouteBuilder 38 mixin MRO | 🔴 HIGH risk, ADR pending | S37+ |
| Audit endpoint integration test | 🔴 not addressed today | S35+ carry-over |
| 14 → 0 frontend_facade users | 🔴 multi-sprint (ADR-0282 Phase C) | S40+ |

---

## 8. Verification machine-check (post-Sprint 37 expected)

```bash
# 1. Allowlist monotonic decreasing (57 → 55)
$ awk -F'\t' 'NR>5 && NF>=3' tools/check_layers_allowlist.txt | wc -l
# expected: 55

# 2. Phase B Item 4 closed
$ python -c "from src.backend.core.audit import get_audit_log"
# expected: ModuleNotFoundError
$ python -c "from src.backend.core.audit.facade import emit_audit"
# expected: success (subpackage preserved)

# 3. Phase B Item 5 closed (DSL bridge removed)
$ grep -rn "from src.backend.dsl.engine.processors.express._common import" src/backend/infrastructure/
# expected: 0
$ python -c "from src.backend.dsl.engine.processors.express._common import get_express_client"
# expected: success (backward-compat shim)
$ python -c "from src.backend.infrastructure.clients.external.express_bot import get_express_bot_client"
# expected: success (canonical home)

# 4. Coverage Phase 1 first run
$ ls .baselines/coverage_per_layer_2026-08-27.log
# expected: 1 file
$ make coverage-per-layer
# expected: 6 layer XML files + combined + breakdown log

# 5. Tests pass
$ pytest tests/unit/core/test_no_audit_proxy.py -v
# expected: 3/3 PASS
$ pytest tests/unit/infrastructure/notifications/adapters/test_express_adapter_no_dsl.py -v
# expected: 3/3 PASS
$ pytest tests/unit/dsl/express/test_express_processors.py -v
# expected: all PASS (backward-compat verified)

# 6. No NEW layer violations
$ make layers
# expected: 0 NEW violations, 55 legacy
```

Все 6 условий выполнимы сегодня.

---

## 9. Key findings parent agent needs to know

1. **Allowlist baseline verified 57 entries** (Sprint 36 retro §8.3 said 56 — off-by-one discrepancy documented §1.1). NOT regression.
2. **Phase B Item 4 (`core/audit/__init__.py`) SHIP-ABLE сегодня**: 19 LOC pure lazy proxy, 2 entrypoint callers (allowed by ADR-0284) + 1 test mock (not affected by proxy removal). Low risk. ~25 мин.
3. **Phase B Item 5 (`infrastructure/notifications/adapters/express.py`) SHIP-ABLE via helper extraction**: refactor `dsl.engine.processors.express._common.get_express_client` (BotX variant) → `infrastructure.clients.external.express_bot.get_express_bot_client` (canonical infra home) + backward-compat shim. Touches 3 files + 1 regression test. ~40 мин.
4. **`core/messaging/eventbus/facade.py` NOT ship-able**: 206 LOC REAL facade (Sprint 36 retro misclassified).
5. **`core/audit/facade/__init__.py` NOT ship-able**: 88 LOC real facade, separate concern.
6. **Coverage Phase 1 first run ready**: actual `make coverage-per-layer` + memory baseline + ratchet start. Per Phase 0 §2.4 deferred commitment + Sprint 36 retro §6.1 explicit commitment.
7. **Per-prune workflow v2 verified applied**: extensions + tests pre-scan выполнен для ОБОИХ targets.

---

**Production readiness**: maintained **99%** → **99.5%** после Sprint 37 (Phase B ahead of schedule на 1 entry + Coverage ratchet started).
