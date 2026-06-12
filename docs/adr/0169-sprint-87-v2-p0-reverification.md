# ADR-0169: Sprint 87 — V2 P0 Re-Verification (Fact-Check, NO Code Changes)

**Status**: Accepted (investigation-only)
**Date**: 2026-06-12
**Sprint**: S87 (fact-check, no feature commits)
**Author**: Ivan (autonomous cycle)
**Supersedes**: implicit "V2 P0 is source of truth" assumption from S73+

## Context

User feedback (S86 v2): "surface-level re-check пропускає issues". V2 audit (FINAL_REPORT_V2)
був зроблений 2026-06-09 12:35, V2 НЕ перепровірявся після Sprint 37-86. Можливі хибні
verdicts. S87 — **investigation-only** (NO code changes), deep fact-check 6 remaining V2 P0:

| # | V2 P0 item | V2 verdict | S87 deep investigation result |
|---|---|---|---|
| #5 | GlobalRateLimit + SecurityHeaders middleware не підключені | **ЧАСТКОВО WRONG** |
| #6 | SQLAlchemyRepository без tenant auto-filter | **РЕАЛЬНИЙ** |
| #7 | `del context` у SkillInvokeProcessor (tenant/auth/trace loss) | **WRONG для skill_invoke, РЕАЛЬНИЙ для 6 інших processors** |
| #8 | Audit log client_id = "anonymous" (compliance) | **РЕАЛЬНИЙ** (fallback дизайн, не bug) |
| #9 | Release pipeline (semantic-release main→master) | **WRONG** (config вже на master, branch теж master) |
| #10 | Graceful shutdown без HTTP drain | **РЕАЛЬНИЙ** (worker drain Є, HTTP drain НЕМАЄ) |

## S87 deep investigation results

### #5: GlobalRateLimit + SecurityHeaders

* `GlobalRateLimitMiddleware` ЗАРЕЄСТРОВАНО в `setup_middlewares.py:99-104` (order=20).
* `SecurityHeadersMiddleware` ЗАРЕЄСТРОВАНО в `setup_middlewares.py:216` (order=860).
* **SecurityHeaders завжди ACTIVE** (немає feature flag) — V2 verdict WRONG.
* `GlobalRateLimitMiddleware` має feature flag `multi_tenant_rate_limit_enabled` —
  **default = False** (`sprints_18_21.py:136-137`). V2 каже "default-OFF → default-ON".
* **High severity**: відсутність default-ON rate-limit у prod = vulnerability.

### #6: Tenant isolation

* `SQLAlchemyRepository` (`base/sqlalchemy.py`) **НЕ має tenant auto-filter** — 0
  згадок `tenant` у файлі.
* `rule_engine_repository` має optional tenant filter (passes None → all tenants).
* `TenantContextRequiredError` (`core/errors.py:164`) існує, але не enforced
  в repository.
* **High severity**: відсутність auto-filter = data leak cross-tenant при помилці.

### #7: SkillInvokeProcessor `del context`

* `skill_invoke.py:76` — `async def _run(self, exchange, context)` — `context`
  **ВИКОРИСТОВУЄТЬСЯ** (line 87, 90, 95) — НЕ `del context`. **V2 verdict WRONG**.
* **Але**: 6 ІНШИХ processors МАЮТЬ `del context`:
  - `ml_predict.py:133`
  - `agent_dsl/mcp_tool.py:100`
  - `agent_dsl/guardrails_apply.py:99`
  - `agent_dsl/pii_unmask.py:70`
  - `agent_dsl/pii_mask.py:91`
  - `agent_dsl/agent_run.py:121`
  - `agent_dsl/plan_execute.py:92`
  - `agent_dsl/reflection_loop.py:100`
  - `agent_dsl/memory_store.py:83`
  - `agent_dsl/memory_recall.py:93`
* **Medium severity**: 10 processors не пропагують tenant/correlation/trace в context.

### #8: Audit log client_id = "anonymous"

* `audit_log.py:64`: `client_id = getattr(auth, "principal", None) or "anonymous"`
* `admin_audit.py:80`: те ж.
* Це **fallback дизайн**, не bug: `AuthContext(AuthMethod.NONE, "anonymous")` —
  нормальний стан для public endpoints.
* **V2 verdict ЧАСТКОВО**: compliance issue реальний, але тільки якщо `anonymous`
  пишеться для authenticated-but-unknown. Потребує **distinction**: pass-through
  endpoint vs failed auth.
* **Low severity**: design improvement, не security fix.

### #9: Release pipeline (semantic-release main→master)

* `pyproject.toml:881` — `branch = "master"`.
* `git branch` показує `* master`. Remote `origin/master` існує.
* **V2 verdict WRONG**: конфіг вже на master, branch = master. V2 audit не
  перевірив реальний branch.

### #10: Graceful shutdown без HTTP drain

* `worker.py:218` — graceful drain (probes → 503, чекаємо активні executions).
* `lifespan.py:591-718` — finally block з try/except для всіх сервісів.
* `app.state.infrastructure_ready = False` (line 593) — **ТІЛЬКИ СИГНАЛ**, не
  блокує нові HTTP requests.
* **V2 verdict РЕАЛЬНИЙ**: HTTP server **НЕ робить request drain** — при shutdown
  нові запити можуть приходити під час teardown сервісів.
* **Medium severity**: race condition, можливі 5xx errors під час deploy.

## Скоригований V2 P0 backlog (станом на 2026-06-12)

| V2 # | Status | What needs to be done | Severity |
|---|---|---|---|
| N1 | ✅ CLOSED S83 | DetachedInstanceError | — |
| #1 | ✅ CLOSED S85 | AIGateway enforcement | — |
| #2 | ✅ CLOSED S86 v2 | Temporal sandbox | — |
| #3 | ✅ CLOSED S84 | 274 logging.factory violations | — |
| **#5** | 🔴 ЧАСТКОВО WRONG (SecurityHeaders OK) | GlobalRateLimit default-ON у prod | High |
| **#6** | 🔴 РЕАЛЬНИЙ | SQLAlchemyRepository auto-filter by tenant | High |
| **#7** | 🟡 WRONG для skill_invoke, РЕАЛЬНИЙ для 10 інших | Add tenant/correlation propagation в `_run` | Medium |
| **#8** | 🟡 Fallback дизайн | Distinguish public-pass-through vs failed-auth в audit | Low |
| **#9** | 🟢 WRONG | N/A — V2 fact-check failure | — |
| **#10** | 🔴 РЕАЛЬНИЙ | HTTP server request drain (503 readiness flip) | Medium |

## Consequences

* S87 — **investigation-only**, NO code changes, 0 commits.
* S88 = V2 P0 #5 + #6 (HIGH severity) — обидва мають security/compliance impact.
* S89 = V2 P0 #7 + #10 (MEDIUM severity) — race condition + audit completeness.
* S90+ = V2 P0 #8 (LOW) + verify V2 P0 #9 не потрібен.
* V2 verdict ненадійний — **завжди fact-check** перш ніж робити feature commit.

## Follow-up

* S88 plan: GlobalRateLimit default-ON + TenantSQLAlchemyRepository (auto-filter
  через `current_tenant()` contextvar + JOIN через `tenant_id` column).
* S89 plan: 10 processors fix (`del context` → `context.set("_tenant_id", ...)`)
  + HTTP server drain (readiness middleware flip to 503 на signal).
* Створити skill `verify-analysis-claims` — pattern з S86 v2 + S87 (V2 verdicts
  unreliable, require deep code-level verification).
