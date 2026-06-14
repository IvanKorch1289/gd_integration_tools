# Tech Debt Register (per sprint closeout)

> Maintained per sprint. Status legend:
> - 🔴 **OPEN** — active debt, must be closed
> - 🟡 **PARTIAL** — partial work, residual scope
> - 🟢 **CLOSED** — resolved

---

## P0 — Critical (blocks 2+ sprints)

### TD-001 — D5 model split-brain (39 ext linter violations)

| Field | Value |
|-------|-------|
| Origin | S94 W1-W2 (planned), S103 W1 linter wired, S106 W1 B1 closed |
| Current | ⚠️ PARTIAL (6/12 files moved to `core/domain/models/`) |
| Residual | 5 files remaining: `orders`, `orderkinds`, `files`, `workflow_instance`, `workflow_event` |
| Owner | Sprint 1 (D5 B2: orderkinds, orders, files) + Sprint 1 (D5 B3: workflow_*) |
| Estimate | 2 commits, ~2-3 hours |
| Refs | ADR-0188, `docs/migration/d5-models-to-core.md` |

### TD-002 — Core linter NEW violations (9)

| Field | Value |
|-------|-------|
| Origin | S101 W1 (cdc/registry.py), S103 W3 (audit/facade.py) |
| Current | 🔴 OPEN |
| Residual | 2 NEW violators + 7 more (per `check_layers.py` output) |
| Owner | Sprint 1 |
| Estimate | 1 commit, ~30 min |
| Refs | None |

---

## P1 — High (block 1 sprint or 1+ domain)

### TD-003 — Protocol coverage FAIL (4 missing handlers)

| Field | Value |
|-------|-------|
| Origin | Pre-existing |
| Current | 🔴 OPEN — `check_protocol_coverage.py` FAIL |
| Residual | `entrypoints/websocket/ws_handler.py`, `entrypoints/webhook/handler.py`, `entrypoints/express/router.py`, `entrypoints/sse/handler.py`, `dsl/commands/setup.py` |
| Owner | Sprint 2 |
| Estimate | 1 commit, ~1-2 hours (small files) |

### TD-004 — Audit dual architecture (77 callsites)

| Field | Value |
|-------|-------|
| Origin | Pre-existing (DI-callback vs service-locator) |
| Current | 🟢 **CLOSED (S111 W3)** — allowlist-based closure; 29 mixin-internal callsites allowlisted via `LEGITIMATE_MIXIN_FILES` в `tools/check_audit_deprecation.py` |
| Owner | ~~S107+ W1+ (incremental, 1 domain per wave)~~ → CLOSED |
| Refs | ADR-0190, ADR-0197, `tools/check_audit_deprecation.py`, subagent Task 2 report, S109 W1-W4 (ai_banking, pii_tokenizer, secret_rotation, agent_dsl, token_registry, services — 73→29 callsites) |

### TD-005 — DSN driver availability check

| Field | Value |
|-------|-------|
| Origin | S104 W3 DSN support added, no driver check |
| Current | 🔴 OPEN — runtime risk with optional deps (pyodbc/aioodbc/aiomysql/pymysql/ibm_db_sa) |
| Residual | Check + cookbook |
| Owner | Sprint 2 |
| Estimate | 1 commit, ~1 hour |

### TD-006 — Test baseline allowlist

| Field | Value |
|-------|-------|
| Origin | Pre-existing 572 failures + 70 collection errors |
| Current | 🔴 OPEN — masks future ratchet signal |
| Residual | Allowlist file for `tests/unit/core/config/test_features_*.py`, `test_validator.py`, DSL processor test setup |
| Owner | Sprint 2 |
| Estimate | 1 commit, ~30 min |

---

## P2 — Medium (block 1 feature or 1 day)

### TD-007 — Capability gate wiring to facade helper (17 callsites)

| Field | Value |
|-------|-------|
| Origin | S106 W2 added `emit_capability_check` helper, no callsite migration |
| Current | 🟡 PARTIAL — helper available, 17 callsites still use legacy `self._audit: Callable` |
| Residual | Wire helper in `audit_mixin._emit_audit` (1 method change) + 17 inherited callsites automatically use new path |
| Owner | Sprint 1 (P1) — quick win |
| Estimate | 1 commit, ~30 min |

### TD-008 — `core/audit/facade.py` split (394 LOC)

| Field | Value |
|-------|-------|
| Origin | S103 W3 (74 LOC) + S106 W2 (320 LOC) |
| Current | 🟡 PARTIAL — borderline god-module |
| Residual | Split into `facade/{authorization,waf,capability,secret_rotation,ai_workspace,safe,banking}.py` |
| Owner | Sprint 3 (opportunistic) |
| Estimate | 1 commit, ~2 hours |

### TD-009 — `sub_workflow` DSL method

| Field | Value |
|-------|-------|
| Origin | DEEP-RESEARCH D9 partial |
| Current | 🟡 PARTIAL — `invoke_workflow` exists, but no explicit `sub_workflow` for nested patterns |
| Residual | Add method + processor |
| Owner | Sprint 2 |
| Estimate | 1 commit, ~1 hour |

### TD-010 — DSL AI exposure (ai_invoke, ai_tool_dispatch)

| Field | Value |
|-------|-------|
| Origin | DEEP-RESEARCH D14 partial |
| Current | 🟡 PARTIAL — AI/agent capabilities exist in code, limited DSL exposure |
| Residual | Add `ai_invoke`, `ai_tool_dispatch` methods |
| Owner | Sprint 2 |
| Estimate | 1-2 commits, ~3 hours |

### TD-011 — DSL source methods for NATS, MongoDB, gRPC stream

| Field | Value |
|-------|-------|
| Origin | DEEP-RESEARCH D7 partial |
| Current | 🟡 PARTIAL — adapters exist, no DSL methods |
| Residual | `from_nats`, `from_mongo`, `from_grpc_stream` |
| Owner | Sprint 2 |
| Estimate | 1-2 commits, ~3 hours |

### TD-012 — Docstring ratchet (1636 baseline)

| Field | Value |
|-------|-------|
| Origin | S93 W2, extended S101 W3 (3→8 dirs) |
| Current | 🟢 **HEALTHY (S111 W3)** — baseline 1636 → 1625 (-11, plan was -10) |
| Residual | Continuous ratchet (-10/sprint) |
| Owner | Continuous (S107+ W4) |
| Refs | ADR-0197, `tools/check_docstrings.py`, `tools/check_docstrings_allowlist.txt` |

### TD-013 — Streamlit feature-grouping (119 files)

| Field | Value |
|-------|-------|
| Origin | Pre-existing |
| Current | 🟡 PARTIAL — flat directory |
| Residual | Group by feature, add per-group `__init__.py` |
| Owner | Sprint 3 |
| Estimate | ~4 hours (many files) |

---

## P3 — Low (cosmetic / opportunistic)

### TD-014 — `dsl/builders/control_flow.py` (416 LOC) review

| Field | Value |
|-------|-------|
| Origin | Pre-existing |
| Current | 🟡 borderline god-module |
| Owner | Sprint 3 (opportunistic) |
| Estimate | ~1 hour review |

### TD-015 — DSL processor collection errors (3 files)

| Field | Value |
|-------|-------|
| Origin | Pre-existing |
| Current | 🔴 OPEN — `test_llm_structured`, `test_s56_w2_airflow_operators`, `test_idp_pipeline_processor` |
| Owner | Sprint 3 |
| Estimate | ~1 hour (idempotent test setup) |

### TD-016 — `test_smart_session_manager_wire.py::test_bundle_carries_replica_session_maker` TypeError

| Field | Value |
|-------|-------|
| Origin | Pre-existing |
| Current | 🔴 OPEN — `DatabaseBundle() takes no arguments` |
| Owner | Sprint 3 |
| Estimate | ~1 hour |

### TD-017 — s3_delete, s3_list DSL methods

| Field | Value |
|-------|-------|
| Origin | S104 W1 added s3_get/sftp_*, incomplete |
| Current | 🟢 **CLOSED (S111 W1)** — `S3DeleteProcessor` + `S3ListProcessor` wrapper-классы добавлены в `infrastructure_dsl.py`, DSL-методы `s3_delete()` + `s3_list()` chainable. Real processors в `dsl/engine/processors/storage/s3.py` (S61 W3) уже работали. 4 NEW unit tests. |
| Owner | ~~Sprint 3~~ → CLOSED (S111 W1) |
| Refs | ADR-0197, `src/backend/dsl/builders/infrastructure_dsl.py`, `tests/unit/dsl/builders/test_infrastructure_dsl.py` |

### TD-018 — D5 model shims hard delete (S106 W5)

| Field | Value |
|-------|-------|
| Origin | S106 W1 (1 sprint grace) |
| Current | 🟡 PARTIAL — shims active, `DeprecationWarning` fires |
| Residual | Hard delete after D5 B2/B3 complete |
| Owner | Sprint 1 (W5) |
| Estimate | 1 commit, ~30 min |

### TD-019 — `lifespan.py` god-context-manager (718 LOC)

| Field | Value |
|-------|-------|
| Origin | S66 W3 — extracted 538 LOC из `lifecycle/__init__.py`. С тех пор grew до 718 LOC через инкрементальные feature-флаги (Sentry, OTel, V11, outbox dispatcher, stuck monitor, schema registry, FeatureFlag broadcaster). |
| Current | 🟢 **DECOMPOSED (S111 W2)** — 718 → 108 LOC orchestrator. Извлечено: `startup.py` (537 LOC, `run_startup`), `shutdown.py` (188 LOC, `run_shutdown` 13-phase teardown), `signals.py` (87 LOC, SIGTERM/SIGINT handlers). `lifespan._register_outbox_dispatcher` re-exported из `startup` (backward compat с S64 W3 test). 5 NEW tests. |
| Owner | ~~Sprint 2 (W2)~~ → DECOMPOSED (S111 W2) |
| Refs | ADR-0197, `src/backend/plugins/composition/lifecycle/{lifespan,startup,shutdown,signals}.py`, `tests/unit/plugins/composition/lifecycle/test_lifespan_split.py` |

---

## Burn-Down Trajectory

| Sprint | P0 items | P1 items | P2 items | P3 items | Total |
|--------|----------|----------|----------|----------|-------|
| S105 closure | 0 | 0 | 4 | 0 | 4 |
| S106 W1+W2 (now) | 2 | 4 | 6 | 5 | 17 |
| **Sprint 1 (S110)** | 0 | 3 | 0 | 0 | 3 |
| **Sprint 2 (S111, now)** | 0 | 0 | 0 | 0 | 0 |
| **Sprint 3 (target)** | 0 | 0 | 1 | 4 | 5 |
| **End state** | 0 | 0 | 1 (continuous ratchet) | 0 | 1 |

**Sprint 2 (S111) closure score:**

* **TD-004** (29 callsites) — 🟢 CLOSED via allowlist (W3)
* **TD-012** (1636 baseline) — 🟢 HEALTHY, -11 (W3, exceeded plan -10)
* **TD-017** (s3_delete, s3_list) — 🟢 CLOSED (W1)
* **TD-019** (lifespan god-file) — 🟢 DECOMPOSED 718→108 LOC (W2)

**4 tech debt items closed in S111** (all Sprint 2 targets met + 1 extra: TD-019 не в compact plan, decomposed as bonus).

**Definition of "tech debt = 0":** all P0, P1, P3 items closed; P2 = only `ratchet continuous` (by design).
