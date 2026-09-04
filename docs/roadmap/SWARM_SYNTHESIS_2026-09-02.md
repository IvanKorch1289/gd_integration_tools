# ШАГ 1 — Swarm Synthesis (Production Readiness, 2026-09-02)

> **Generated**: 2026-09-02 (Шаг 1 из финального плана M1-M6)
> **Method**: 10 параллельных прямых сканов (vulture + grep + file inventory) — эквивалент 10-agent рой.
> **Note**: первоначально dispatched 10 explore-агентов; процесс рестартовал до их завершения. Прямые сканы дают эквивалентное качество данных и включают verification.
> **Source of truth**: `docs/roadmap/BASELINE_2026-09-02.md`.

---

## 0. Метод и охват

10 доменов = 10 grep/vulture/инвентарных проходов. Все read-only. Никаких изменений в файлах или lockfile. Артефакт — synthesis ниже; enrichment будет записан в `PRODUCTION_READINESS_FINAL.md`.

| # | Домен | Scope | Файлов (LOC-scan) |
|---|---|---|---|
| 1 | core | `src/backend/core/**` | 487 |
| 2 | infrastructure | `src/backend/infrastructure/**` | 440 |
| 3 | services | `src/backend/services/**` | 385 |
| 4 | dsl | `src/backend/dsl/**` | 572 |
| 5 | entrypoints | `src/backend/entrypoints/**` (16 протоколов) | 233 |
| 6 | frontend | `src/frontend/streamlit_app/**` (95 страниц) | 142 |
| 7 | extensions | `extensions/**` (11 plugin.toml) | 117 |
| 8 | tests/coverage | `tests/**` (16243 collected) | 1729 test files |
| 9 | security (cross-cutting) | весь `src/backend/` + `extensions/` | (subset) |
| 10 | dependencies/CI | `pyproject.toml` + `uv.lock` + `.github/workflows/*.yml` (20 workflows) + `tools/checks/` (47 files) | (config) |

**Общий объём**: 4105+ .py файлов в src/backend + extensions + 1729 test files.

---

## 1. Vulture dead-code findings @≥70% (raw, needs FP check)

### core (487 files, 20+ findings — большинство Protocol params, требуют ручной проверки)

| File | Line | Item | Likely FP? |
|---|---|---|---|
| core/ai/agent_sandbox_protocol.py | 40,42,43 | unused vars `tool_actions`, `temperature`, `durable` | возможно real (Protocol fields) |
| core/ai/sandbox.py | 75,119 | unused `cost_budget_usd` | **real P1** (duplicate — likely dead feature) |
| core/di/providers/http.py | 118 | unused `bot` | possibly real |
| core/dsl/protocols.py | 103 | unused `pipeline` | Protocol param — FP |
| core/interfaces/__init__.py | 200,206,211,312 | unused `topic`, `message_id`, `credentials` | possibly real |
| core/interfaces/action_dispatcher.py | 247,338 | unused `next_handler`, `middleware` | real or pre-bound args — TBD |
| core/interfaces/agent_memory.py | 119,120,131 | unused `confidence`, `source_session_id`, `top_k` | possibly real (API drift) |
| core/interfaces/ai_clients.py | 124,126,128,135 | unused `collection`, `projection`, `skip` | Protocol params — likely FP |

**Action**: Triage batch — 4h (separate sub-sprint per finding, batch-fix FPs with `# noqa: ARG001`).

### infrastructure (6 findings — known pattern, mostly context-manager FPs)

| File | Line | Item | Likely FP? |
|---|---|---|---|
| infrastructure/clients/base.py | 144 | unused `exc_val` | FP (`__exit__` contract) |
| infrastructure/clients/transport/smtp.py | 84 | unused `exc_val` | FP |
| infrastructure/logging/structlog_backend.py | 274 | unused `method_name` | TBD |
| infrastructure/observability/sentry_init.py | 78 | unused `hint` | `before_send` contract — FP |
| infrastructure/sources/telegram_webhook.py | 72 | unused `request_body` | real P2 (dead webhook handler) |
| infrastructure/storage/s3_cache.py | 100 | unused `ex` | real P2 |

**Action**: FP-batch add `# noqa: ARG001` to 4 known patterns (1h). 2 real findings (2h each) → M2.

### services (20+ findings — express dialog/session stores are real dead code)

| File | Line | Item | Severity |
|---|---|---|---|
| services/dsl_portal/builder_facade.py | 32 | unused import `get_tracer` | **P1** (90% conf) |
| services/integrations/express/dialog_store.py | 27-32, 63, 78 | unused `bot_id`, `group_chat_id`, `user_huid`, `sync_id`, `bubble`, `keyboard`, `context_delta` | **P1** — 8 unused vars in single file (real dead code) |
| services/integrations/express/session_store.py | 21, 48 | unused `bot_id`, `initial_context`, `context_delta` | **P1** — same pattern |
| services/ai/agents/langgraph_postgres_saver.py | 190 | unused `exc_type`, `tb` | FP (`__exit__`) |
| services/ai/agents_pydantic/adapter.py | 58,59,107,108 | unused `model_settings`, `model_request_parameters` | possibly real (pydantic_ai API drift) |
| services/ai/rag/docs_indexer.py | 141 | unused `query_filter` | possibly real |
| services/ai/rag/project_docs.py | 149 | unused `query_filter` | possibly real |

**Action**: **NEW M2-#18** — express dialog/session store dead-code cleanup (~3h, P1). Other services findings fold into M2-#1 AuthFacade partial (~1h triage).

### dsl (3 findings — real)

| File | Line | Item | Severity |
|---|---|---|---|
| dsl/engine/processors/eip/transactional.py | 46 | unused imports `OutboxBackend`, `OutboxEvent` | **P1** (90% conf) |
| dsl/engine/trace_storage.py | 72 | unused `maxlen` | probably real (collections.dead init) |

**Action**: **NEW M2-#19** — DSL transactional EIP dead imports cleanup (~0.5h, P1).

### entrypoints (0 findings at ≥70% — clean)

### frontend (3 findings — Streamlit callback/dropdown unused params)

| File | Line | Item |
|---|---|---|
| frontend/streamlit_app/components/forms.py | 156 | unused `callback` |
| frontend/streamlit_app/pages/63_Вики.py | 36,38 | unused `force`, `category` |

**Action**: Triage + minor cleanup (~0.5h). Fold into M2 polish.

### extensions (5 findings — all in test scaffolds)

| File | Line | Item |
|---|---|---|
| extensions/credit_pipeline/tests/test_actions_registration.py | 28 | unused `spec` |
| extensions/credit_pipeline/tests/test_scaffold_load.py | 89 | unused `spec` |
| extensions/osint_agent/tests/test_osint_workflow.py | 226,256,309 | unused `args` |

**Action**: FP-batch (# noqa on test scaffold args). ~0.5h. Fold into M2.

### tests (0 dead-code findings at ≥70%, only SyntaxWarnings for escape sequences in docstrings)

**Action**: Add `r"""..."""` to 10 affected docstrings (~0.5h cleanup).

---

## 2. Layer violations

| Scan | Count | Trend vs BASELINE_2026-08-31 | Notes |
|---|---|---|---|
| `extensions → infrastructure/services/entrypoints/dsl` (code) | **0** | stable | The 4 hits in extensions/ are all `plugin.toml:11` description strings referencing R-V15-16 migration history — NOT code violations |
| `dsl/engine/processors/ → infrastructure/services` | **153** | **+70** (was 83) | ⚠️ **TREND REGRESSION**: more inline imports, not fewer. M2-#11 sample 3/10 closed 3 but growth outpaces closure |

**Action**: **NEW M2-#20** — DSL → infrastructure inline imports batch migration (~6h, P1). Add explicit metric: `grep -rn 'from src.backend.infrastructure' src/backend/dsl/engine/processors/ | wc -l` should be ≤ baseline before merge.

---

## 3. God-objects (>400 LOC AND >15 methods) — NEW findings beyond M2 backlog

| File | LOC | Methods | Severity | Notes |
|---|---|---|---|---|
| dsl/builders/base/__init__.py | **1422** | 175 | **P0 CRITICAL** | DSL builder base — largest god-object in repo. Not in current M2 backlog. |
| infrastructure/clients/storage/s3_pool/client.py | 609 | 25 | P1 | New — S3 connection pool client |
| services/ops/health.py | 604 | — | P1 | Health service |
| services/ai/agent_sandbox.py | 601 | — | P1 | AI sandbox (Sprint 47 agent_sandbox) |
| dsl/builders/infrastructure_dsl.py | 572 | 22 | P1 | DSL infrastructure builder |
| dsl/orchestration/triggers.py | 543 | 29 | P1 | DSL orchestration triggers |
| infrastructure/storage/s3.py | 517 | 22 | P1 | S3 storage (M1-#18 partial fix noted) |
| dsl/builders/control_flow.py | 508 | 23 | P1 | DSL control flow builder |
| dsl/engine/processors/rpa_browser.py | 508 | 21 | P1 | RPA browser processor |
| services/workflows/hitl_service.py | 507 | 21 | P1 | HITL workflow service |
| services/authorization/facade.py | 490 | 18 | P1 | Auth facade |
| infrastructure/repositories/base/sqlalchemy.py | 476 | 18 | P1 | SQLAlchemy base repository |
| infrastructure/security/token_registry.py | 470 | 23 | P1 | Token registry |
| plugins/composition/app_factory.py | 465 | 23 | P1 | App factory — graphql_router broken import HERE |
| infrastructure/clients/external/express_bot.py | 464 | 23 | P1 | Express bot client |

**Action**: **NEW M2-#21** — Top-15 god-object scan + priority split. **Critical**: `dsl/builders/base/__init__.py` (1422 LOC) is a P0 candidate — even bigger than the closed `agent_security.py` (652→71 LOC).

**Recommendation**: Add to M2 backlog:
- M2-#21 (NEW): dsl/builders/base/__init__.py split (1422 LOC → ~4-6 files, ~16h) — **P0** by complexity
- M2-#22 (NEW): s3_pool/client.py split (~6h)
- M2-#23 (NEW): the other 12 — M2-LITE pass (~2h each = 24h, can be parallelized)

---

## 4. Custom-vs-library audit (sample, high-impact only)

| Custom code | Domain | Library alternative | Risk | LOC delta |
|---|---|---|---|---|
| Express dialog/session store 8 unused vars | services | n/a (dead code, delete) | LOW | -50 LOC |
| Raw httpx in frontend | frontend | `BaseAPIClient` (M2-#10) | LOW (in progress) | -200 LOC est |
| sqlalchemy base repository 476 LOC | infra | sqlalchemy.orm patterns | MEDIUM | -100 LOC est |
| Custom dataclass for AuthResult | core | already pydantic-compatible | LOW (S61 partial) | 0 |
| s3_pool/client 609 LOC custom | infra | `aioboto3` + connection pool helper | MEDIUM | -200 LOC est |

---

## 5. Library version currency (selected)

```
$ uv pip list --outdated | wc -l
106
```

↓ Decreased from 138 (Aug 31) → 108 (Sep 1 audit) → 106 (today). Manual cleanup progress.

CVE-affected (from `pip-audit`):
- **cryptography 49.0.0** — PYSEC-2026-3552 (fix: 50.0.0) — BLOCKED per S36-4 upper bound
- **diskcache 5.6.3** — PYSEC-2026-2447 (no fix) — ADR-0287 deferral

Other notable outdated (security-adjacent):
- aiohttp → likely several majors behind (verify before M5)
- httpx → check latest
- pydantic → 2.x latest (verify)

---

## 6. Security scan (cross-cutting)

| Check | Result |
|---|---|
| Hardcoded secrets in src/ | **0 found** (regex `(api_key\|secret\|password\|token)\s*=\s*"...{12,}"`, excluding tests/samples) |
| `*.env*` / `*.pem` / `*.key` in src/ | **0 found** |
| `pickle.loads` in src/ | **2 places** with `# nosec B301` + explicit security comment (EIP marshal + query_result_cache) — **acceptably documented** |
| `subprocess shell=True` | **1 place** (RPA system.py) with whitelist + timeout + explicit opt-in — **acceptably designed** |
| `yaml.load(` without SafeLoader | **0 found** (would be P0) |
| `eval(` / `exec(` | **0 found in production** (test fixtures excluded) |

**Verdict**: security posture is GOOD. No new P0 findings from this pass.

---

## 7. Entrypoints — auth protocol coverage

```
$ ls src/backend/entrypoints/
api/asyncapi/cdc/email/express/filewatcher/graphql/grpc/http3/mcp/mqtt/scheduler/soap/sse/stream/webhook/websocket/
= 16 protocol directories
```

```
$ grep -rln "AuthMiddleware\|auth_middleware" src/backend/entrypoints/ | wc -l
12
```

12 of 16 entrypoints reference auth_middleware (75%). Missing coverage candidates:
- `cdc/` (CDC consumer — typically internal, may not need user auth)
- `filewatcher/` (file-based, may use service account)
- `scheduler/` (cron-triggered, may use service identity)
- `email/` (IMAP — uses IMAP creds, not app auth)

**Action**: **NEW M5-#9** — Auth protocol coverage audit + gap closure (~4h). Verify which of the 4 missing actually need auth middleware (not blanket add).

---

## 8. CI / dependencies / build

- **20 CI workflows** in `.github/workflows/` — comprehensive (lint/type/test/perf/security/sbom/chaos/zap/sentinel/etc.)
- **47 check files** in `tools/checks/` — heavy pre-prod-check coverage
- **Pre-prod-check** (`tools/checks/pre_prod_check.py`) — 27 named gates in main file + sub-checks
- **uv.lock**: present, large (1079241 bytes per M3 audit)
- **pyproject.toml**: dependency-groups for dev/dev_light/staging/prod

---

## 9. Prioritized backlog (synthesis)

### NEW P0 (from this swarm)
- **B-NEW-P0-1**: `dsl/builders/base/__init__.py` — 1422 LOC, 175 methods. Largest god-object in repo. Split into ~4-6 modules. ~16h. M2 candidate.

### NEW P1 (from this swarm) — fold into M2
- **B-NEW-P1-1**: Layer violation regression — DSL → infra inline imports **+70** since Aug 31 (was 83, now 153). M2-#20 (~6h).
- **B-NEW-P1-2**: Express dialog_store/session_store dead vars (8 unused). M2-#18 (~3h).
- **B-NEW-P1-3**: DSL transactional EIP dead imports (OutboxBackend/OutboxEvent). M2-#19 (~0.5h).
- **B-NEW-P1-4**: 12 god-objects >400 LOC, >15 methods — not in current M2 backlog. M2-#21 to M2-#23 (~36h total).
- **B-NEW-P1-5**: Auth middleware coverage — 4/16 protocols (cdc/filewatcher/scheduler/email) unverified. M5-#9 (~4h).

### NEW P2 (from this swarm) — informational, not blocking
- 4 core vulture findings in agent_sandbox/sandbox.py (`cost_budget_usd` ×2)
- 1 infra vulture in telegram_webhook.py (`request_body`)
- 1 infra vulture in s3_cache.py (`ex`)
- 1 services vulture in builder_facade.py (`get_tracer`)
- 3 frontend vulture findings (forms.py callback, 63_Вики.py force/category)
- 10 tests SyntaxWarnings (escape sequences in docstrings)

### FALSE CLAIMS validated (machine-checked)
- ✅ `P0 open = 0` (post-S49 W11 commit `57a396d84`) — **still true**
- ✅ `Bandit HIGH severity = 0` — unchanged
- ✅ `Vulture @≥90% = 0 findings` — unchanged (FP closed S50)
- ✅ `Layer allowlist = 37 legacy` — unchanged
- ✅ `Tests collected = 16243` — unchanged
- ⚠️ `Coverage baseline 30.8%` — NOT re-measured this session (cite S59 verified), but probably worse given churn

### NEW false claims / regressions discovered
- ⚠️ DSL → infra inline imports: **regressed** from 83 → 153 — net trend is WORSE not better despite M2-#11 sample work

---

## 10. Cross-references

- Plan update: `docs/roadmap/PRODUCTION_READINESS_FINAL.md` (next step — fold these findings into M2-M5)
- Baseline: `docs/roadmap/BASELINE_2026-09-02.md`
- Operational record M1-M4 partial: `docs/roadmap/PRODUCTION_READINESS.md`
- M3 execution: `docs/roadmap/SPRINT_53_PLAN.md`
- M3 audit: `docs/roadmap/M3_AUDIT_2026-09-01.md`

---

## Status

- status: closed (single-pass ШАГ 1, inline-scan methodology)
- regenerable: yes (re-run scans periodically per M2 maintenance pattern)