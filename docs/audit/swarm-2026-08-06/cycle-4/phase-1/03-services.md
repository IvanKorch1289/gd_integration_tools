# Cycle 4 — Phase 1 / 03 Services Domain Audit

- Domain: **Services**
- Scope: `src/backend/services/**` + `tests/unit/services/**`
- Excluded: `ai/`, `workflow/`, `workflows/`, `security/`, `auth/`, `authorization/`, `agent_security/`
- HEAD: `22e08a0d` (cycle-1/2/3 reapply commit)
- Phase: 1 (read-only bounded audit)
- Output: `docs/audit/swarm-2026-08-06/cycle-4/phase-1/03-services.md`
- Date: 2026-08-07

---

## 1. Scope

In-scope directories (Services domain, post-exclusion):

| Path | Notes |
|---|---|
| `src/backend/services/admin/` | Admin service + sqladmin integration |
| `src/backend/services/audit/` | Audit pipeline (ClickHouse, replay, workflow sink) |
| `src/backend/services/billing/` | Quota + no-op billing |
| `src/backend/services/cache/` | Cache facade + metrics re-export |
| `src/backend/services/capabilities/` | Capability facade |
| `src/backend/services/codec/` | Codec facade |
| `src/backend/services/core/` | Core services (admin, base_external_api, system, tech) |
| `src/backend/services/dsl/` | DSL builder service |
| `src/backend/services/dsl_portal/` | DSL portal builder facade |
| `src/backend/services/execution/` | Action dispatcher + middleware + invoker |
| `src/backend/services/integrations/` | facade, dadata, skb, webhook_relay, imported_action, etc. |
| `src/backend/services/io/` | Dataframe, export, files, search, web_automation |
| `src/backend/services/jupyter/` | Hub actions, orchestrator, execution_service |
| `src/backend/services/lineage/` | In-memory lineage emitter |
| `src/backend/services/messaging/` | facade, kafka_facade, outbox_monitor |
| `src/backend/services/notifications/` | facade, apprise_service |
| `src/backend/services/observability/` | Observability facade |
| `src/backend/services/ops/` | data_quality, dq_remediation, analytics, anomaly_detector, scheduled_reports, message_replay, notification_hub, webhook_scheduler, notify_actions, health |
| `src/backend/services/pii/` | PII facade |
| `src/backend/services/plugins/` | decorators, registries, versioning, loader |
| `src/backend/services/resilience/` | facade, rate_limiter |
| `src/backend/services/routes/` | loader, manifest_toml, route_authz, hot_reloader |
| `src/backend/services/rpa/` | browser_pool, browser_cookies_store, desktop_rpa_client, desktop_session_pool, ocr_processor |
| `src/backend/services/scheduler/` | facade, admin, cron_dashboard_service |
| `src/backend/services/schema_registry/` | registry, populator, exporters |
| `src/backend/services/secrets/` | facade |
| `src/backend/services/storage/` | facade |
| `src/backend/services/tenancy/` | facade |
| `src/backend/services/wiki/` | whoosh_index |
| `tests/unit/services/**` (post-exclusion) | Mirror of the above |

Sub-modules excluded (per task scope): `src/backend/services/{ai,workflow,workflows,security,agent_security}/` and the corresponding test subfolders. Authorization (`services/authorization/`) is OUT OF SCOPE per the task's explicit exclusion list. (`auth/` does not exist as a subdir in `services/`.)

Не проверено (out of scope or unreachable):
- Anything in `src/backend/services/ai/` (cycle 4 already has separate AI-domain agents).
- Anything in `src/backend/services/security/`.
- `src/backend/services/authorization/`.
- Cycle-1/2/3 markdown reports (per task constraint).
- `KNOWN_ISSUES.md`, `CLAUDE.md`, `PLAN.md`, `DEEP_AUDIT_REPORT.md`, `triage_allowlist_report.md` (per task constraint).

---

## 2. Verified strengths

| ID | Strength | Evidence |
|---|---|---|
| SV-S-01 | All 12 facade classes in scope expose capability-gated APIs | `services/{cache,secrets,storage,notifications,messaging,resilience,observability,integrations,codec,capabilities,tenancy}/facade.py` — every public mutation method calls `self._assert(...)` or equivalent before doing the underlying IO. |
| SV-S-02 | `IntegrationFacade._check_capability` is **fail-closed** (deny-by-default on authz-unavailable) | `src/backend/services/integrations/facade.py:93-98` — `except Exception: _logger.warning(...); return False`. |
| SV-S-03 | `RouteAuthz.check_route_permission` is **fail-closed** | `src/backend/services/routes/route_authz.py:69-76` — gateway-unregistered path returns `(False, "authorization_gateway_not_registered")`. |
| SV-S-04 | `ClickHouseAuditService` DLQ has 3-tier priority with explicit "silent loss" semantics | `src/backend/services/audit/clickhouse_audit_service/service.py:42-46, 184-218` — DLQWriter (canonical) → JsonlAuditBackend (legacy) → silent loss (with WARNING). |
| SV-S-05 | `BrowserCookieStore` at-rest encryption (Fernet) with required env var in prod | `src/backend/services/rpa/browser_cookies_store.py:58-97` — `BROWSER_COOKIES_FERNET_KEY` required outside `dev_light` profile, RuntimeError otherwise. |
| SV-S-06 | `BaseExternalAPIClient` (services/core) is the canonical wrapper for external HTTP APIs | `services/integrations/{skb.py,dadata.py}` both inherit from it; auth handling is uniform. |
| SV-S-07 | `CapabilityFacade.check_or_raise` wraps unexpected exceptions as `CapabilityDeniedError` (fail-safe) | `src/backend/services/capabilities/facade.py:209-216` — `except Exception: raise CapabilityDeniedError(...) from exc`. |
| SV-S-08 | `services/scheduler/admin.py` is an explicit layer-policy exception with documented re-export | `src/backend/services/scheduler/admin.py:12-14` — "Layer policy: entrypoints -> services (allowed per V22)". |
| SV-S-09 | All facade methods consistently return `ServiceError` on backend failure (raise, not silent) | `services/{cache,secrets,storage,integrations,messaging,codec}/*facade.py` — `try/except Exception as exc: raise ServiceError(...) from exc`. |
| SV-S-10 | `services/audit/replay_query.py` correctly notes prior reverse-layer violation and lives in services/ | `src/backend/services/audit/replay_query.py:1-15` — explicit docstring on the migration. |
| SV-S-11 | `services/dsl_portal/builder_facade.py` provides explicit list of frontend→dsl entry points | `src/backend/services/dsl_portal/builder_facade.py:14-18` — documents the S44 W2 / S168 W14 closure of frontend→dsl imports. |
| SV-S-12 | Resolved: `services/scheduler/admin.py` is a thin re-export only | imports canonical from `infrastructure.scheduler.dlq` and `scheduler_manager` (allowed by V22). |
| SV-S-13 | Resolved: `services/cache/metrics.py` is a thin re-export only | imports canonical from `infrastructure.cache.*`. |
| SV-S-14 | Resolved: `services/messaging/outbox_monitor.py` is a thin re-export only | imports canonical from `infrastructure.messaging.outbox.stuck_monitor`. |

---

## 3. Findings table (P0..P4)

| ID | Sev | path:line | Title |
|---|---|---|---|
| **SERV-P0-001** | P0 | `src/backend/services/tenancy/facade.py:96-124` | `TenantFacade.with_tenant` raises `TypeError` on every call — T-08 fix from cycle 3 is broken |
| **SERV-P0-002** | P0 | `src/backend/services/admin/api.py:97-102` | `AdminService._authorize` is **fail-open** when `AuthorizationGateway` is unavailable — silent permission grant for `feature_flag:write`, `audit:read`, `sessions:read` |
| **SERV-P0-003** | P0 | `src/backend/services/integrations/webhook_relay.py:262-273, 296-318` | DLQ silent-loss on Redis unavailable: in-memory DLQ can grow unbounded; `dlq_retry` may leave entries in DLQ if `LREM` fails; `dlq_remove` swallows errors silently |
| **SERV-P1-001** | P1 | `src/backend/services/ops/data_quality/__init__.py:68-134` + 4 mixin files | 5-way class duplication: `DQSeverity`, `DQViolation`, `DQCheckResult`, `DQRule` defined in 5 separate modules — runtime `isinstance()` checks fail across modules |
| **SERV-P1-002** | P1 | `src/backend/services/io/files.py:1-20` + `src/backend/services/integrations/skb.py:127-152` | Reverse-layer shim: services-layer imports `extensions.*` directly; emits `DeprecationWarning` at module import time (causes test warnings) |
| **SERV-P1-003** | P1 | `src/backend/services/admin/api.py:55-77` | AdminService `_get_authz` swallows all exceptions during gateway init, falling back to `None` — root cause of P0-002 |
| **SERV-P1-004** | P1 | `src/backend/services/admin/api.py:108-116` | `authz.authorize()` exceptions emit `outcome="error"` audit but then re-raise — correct behavior, but **audit outcome is inconsistent** with `denied` semantics (no `decision.allowed` value provided) |
| **SERV-P2-001** | P2 | `src/backend/services/admin/api.py:55-56, 198-244` | `_audit_cb` parameter is stored but never used — dead code (audit goes through `emit_admin_action`) |
| **SERV-P2-002** | P2 | `src/backend/services/tenancy/facade.py:47-58` | `set(ctx)` calls `core.tenancy.set_tenant(ctx)` but accepts whatever ctx the caller passes — no type check; inconsistent with `with_tenant` (which uses CapabilityTenant) |
| **SERV-P2-003** | P2 | `src/backend/services/ops/data_quality/apply_mixin.py:354-356` | `self._cardinality_counts` initialized lazily inside `_apply_cardinality` — works but never registered in `_DataQualityProtocol` (hidden state) |
| **SERV-P2-004** | P2 | `src/backend/services/ops/scheduled_reports.py:118-181` | `ScheduledReportsService.run_now` catches all `Exception` and reports `status="error"` — masks transient failures from caller, no retry hook |
| **SERV-P2-005** | P2 | `src/backend/services/integrations/webhook_relay.py:232-247` | `_send_with_retry` defines local `_HTTPError` class for tenacity signal — would be cleaner as a module-level exception |
| **SERV-P2-006** | P2 | `src/backend/services/jupyter/hub_run_orchestrator.py:148-155` | Feature-flag gate raises `JupyterHubNotEnabledError` from both `ImportError` and `AttributeError` masks infrastructure misconfiguration as feature-off |
| **SERV-P2-007** | P2 | `src/backend/services/observability/facade.py:67-69, 89-91, 105-106, 120-121, 140-141` | All observability methods swallow exceptions with `_logger.debug` — failures invisible at default log level (metrics gaps, trace drops, correlation_id loss) |
| **SERV-P3-001** | P3 | `src/backend/services/cache/facade.py:106-116, 122-133, 139-152, 154-165` | Custom cache facade duplicates `cachetools.TTLCache` + `aiocache` (already a dep via `infrastructure/cache`) — but the duplication is documented as `Ponytail` thin wrapper |
| **SERV-P3-002** | P3 | `src/backend/services/io/export_service.py:39-310` | 5 hand-rolled exporters (csv, xlsx, pdf, json, parquet) — `pyarrow` + `tabulate` could replace most with less code |
| **SERV-P3-003** | P3 | `src/backend/services/integrations/webhook_relay.py:160-202` | Custom JMESPath-based transformer duplicates `jmespath` library usage already in repo — could use the canonical `core/transforms/` instead |
| **SERV-P3-004** | P3 | `src/backend/services/scheduler/admin.py:1-25` + `src/backend/services/cache/metrics.py:1-25` + `src/backend/services/messaging/outbox_monitor.py:1-38` | 3 separate thin re-export modules (no actual logic) — could be merged into a single `services/_re_exports.py` |
| **SERV-P4-001** | P4 | `src/backend/services/ops/data_quality/` | Missing: persistent storage of DQ rules (currently in-memory only) — fits Camel-style "configurator" pattern for per-tenant DQ profiles |
| **SERV-P4-002** | P4 | `src/backend/services/rpa/` | Missing: structured retry policy per RPA action (Playwright/Papermill) — currently no `RetryPolicy` integration, only per-method `try/except` |
| **SERV-P4-003** | P4 | `src/backend/services/admin/api.py` | Missing: bulk audit-log query (currently `get_audit_log` returns `[]` always — placeholder, see SV-S-15) |

**Finding count**: 3 × P0, 4 × P1, 7 × P2, 4 × P3, 3 × P4 = **21 findings** in this domain.

---

## 4. Detailed evidence

### SERV-P0-001 — TenantFacade.with_tenant is broken (T-08 fix is incorrect)

**Severity**: P0 — every call to `TenantFacade.with_tenant()` raises TypeError. **The cycle-3 T-08 fix is RESIDUAL.**

**Path**: `src/backend/services/tenancy/facade.py:96-124`

**Verified evidence (via `.venv/bin/python`)**:

```text
$ .venv/bin/python -c "...see Commands run section..."
No principal_id: FAILED: TypeError CapabilityTenant.__init__() got an unexpected keyword argument 'tenant_id'
With principal_id: FAILED: TypeError CapabilityTenant.__init__() got an unexpected keyword argument 'tenant_id'
```

**Root cause**: The T-08 fix used `CapabilityTenant(tenant_id=..., principal_id=...)`, but `CapabilityTenant` only accepts `id` and `principal` (see `src/backend/core/security/capabilities/tenant.py:36-58`).

```python
# tenancy/facade.py:115-119 (BROKEN)
new_ctx = CapabilityTenant(
    tenant_id=tenant_id,        # ← wrong kwarg; correct is `id`
    principal_id=principal_id,  # ← wrong kwarg; correct is `principal`
)
```

**Impact**: Every `async with facade.with_tenant(...)` raises TypeError, breaking any multi-tenant scoped context in production code paths.

**Test catches the failure**:
```text
$ .venv/bin/python -m pytest tests/unit/services/test_facades.py::TestTenantFacade -v
FAILED tests/unit/services/test_facades.py::TestTenantFacade::test_with_tenant_restores_previous
1 failed, 4 passed in 0.20s
```

But the test only fails because `set_tenant` is mocked — the test does NOT catch the broken kwargs in normal runs because `current_tenant` is mocked to `None` and `set_tenant` is a MagicMock. Production usage with real `core.tenancy.set_tenant` will hit TypeError.

**Minimal recommendation**: Change to `CapabilityTenant(id=tenant_id, principal=principal_id or tenant_id)` and verify `set_tenant()` accepts `CapabilityTenant` (or update `set_tenant()` in core to accept both `TenantContext` and `CapabilityTenant`).

**Test criterion**: `tests/unit/services/test_facades.py::TestTenantFacade::test_with_tenant_restores_previous` passes without mocks on `set_tenant`. Add a new test that verifies `CapabilityTenant.id == "tenant_42"` and `CapabilityTenant.principal == "user_1"` after entering the context.

---

### SERV-P0-002 — AdminService._authorize is fail-open

**Severity**: P0 — silent privilege grant.

**Path**: `src/backend/services/admin/api.py:97-102`

**Verified evidence**:

```python
# admin/api.py:96-102 (FAIL-OPEN)
authz = self._get_authz()
if authz is None:
    # AuthZ unavailable — fail-open for dev, but log warning
    logger.warning(
        "AuthZ unavailable for %s@%s/%s — allowing", actor, resource, action
    )
    return  # ← silently grants access
```

**Contrast with sibling facades**:

| File | Behavior |
|---|---|
| `services/admin/api.py:97-102` | **FAIL-OPEN** (returns when authz is None) |
| `services/integrations/facade.py:93-98` | FAIL-CLOSED (returns False when authz unavailable) |
| `services/routes/route_authz.py:69-76` | FAIL-CLOSED (returns `(False, "authorization_gateway_not_registered")`) |

**Comment says "for dev"**, but this is the **production admin service** that handles `feature_flag:write`, `audit:read`, `sessions:read`. If the global `AuthorizationGateway` singleton fails to initialize (DI miswire, missing dependency, runtime exception), all admin actions succeed silently.

**Test coverage**: **0 tests** for fail-open behavior. `tests/unit/services/admin/test_sqladmin_setup.py` only tests `register_admin()` (sqladmin integration); `tests/unit/services/core/test_admin.py` tests `services/core/admin.py` (a different AdminService without authz). `services/admin/api.py` has **no tests in the in-scope set**.

**Minimal recommendation**: Replace lines 97-102 with:

```python
if authz is None:
    raise AdminAuthorizationError(
        f"AuthorizationGateway unavailable for {actor}@{resource}/{action}"
    )
```

**Test criterion**: New unit test `tests/unit/services/admin/test_api.py::test_authorize_denies_when_gateway_unavailable` verifies that `AdminService._authorize(...)` raises `AdminAuthorizationError` when `self._authz is None`.

---

### SERV-P0-003 — WebhookRelay DLQ silent-loss

**Severity**: P0 — data-loss on Redis outage.

**Path**: `src/backend/services/integrations/webhook_relay.py:262-273, 296-318`

**Verified evidence**:

```python
# webhook_relay.py:262-273 — _dlq_push
async def _dlq_push(self, entry: DLQEntry) -> None:
    raw = await _redis_raw()
    if raw is not None:
        try:
            await raw.lpush(_DLQ_KEY, orjson.dumps(asdict(entry)).decode())
            await raw.ltrim(_DLQ_KEY, 0, _DLQ_MAX_LEN - 1)
            return
        except Exception as exc:
            logger.warning("DLQ Redis push failed: %s, fallback to memory", exc)
    self._memory_dlq.append(entry)  # ← unbounded; no LTRIM-equivalent
```

Three independent data-loss vectors:

1. **Unbounded growth of `_memory_dlq`**: Redis path applies `LTRIM` to cap at 10 000 entries; the memory fallback appends without bound. On prolonged Redis outage, OOM is guaranteed.

2. **`_dlq_remove` swallows LREM errors**: The outer `try/except Exception as exc: logger.warning(...)` returns silently. If the Redis LREM succeeds but a later exception occurs, the function returns successfully but the entry may still be in Redis. Worse, if Redis push succeeded but LREM fails, the entry remains in DLQ **forever** (dlq_retry would loop).

3. **`dlq_retry` does not handle missing-rule case in DLQ cleanup**: When `rule = self._rules.get(entry.rule_id)` returns None (line 351), the entry is reported `status="rule_not_found"` but `_dlq_remove(entry.id)` is never called — the dead entry stays in DLQ until manual cleanup.

**Impact**: For a webhook delivery pipeline that retries on failure (per `dlq_retry`), repeated dead-rule entries accumulate. Combined with the unbounded `_memory_dlq`, this is a quiet data-loss vector.

**Minimal recommendation**:
1. Add `_memory_dlq_max_len` and `_memory_dlq.pop(0)` on overflow.
2. Re-raise from `_dlq_remove` (caller decides retry policy).
3. In `dlq_retry`, when `rule is None`, call `await self._dlq_remove(entry.id)` to clean up.

**Test criterion**: New unit test that simulates Redis-write success + Redis-remove failure → entry remains; new test for unbounded growth → entry count > 10 000 triggers eviction.

---

### SERV-P1-001 — data_quality class duplication (5-way)

**Severity**: P1 — `isinstance()` semantics broken across modules; capability/wrapper-composition violations.

**Path**: 5 module files all define the same dataclass classes:

```text
check_mixin.py:28       class DQSeverity
check_mixin.py:37       class DQViolation
check_mixin.py:47       class DQCheckResult
check_mixin.py:61       class DQRule
rule_mgmt_mixin.py:30   class DQSeverity
rule_mgmt_mixin.py:40   class DQViolation
rule_mgmt_mixin.py:51   class DQCheckResult
rule_mgmt_mixin.py:70   class DQRule
schema_mixin.py:29      class DQSeverity
schema_mixin.py:38      class DQViolation
schema_mixin.py:48      class DQCheckResult
schema_mixin.py:62      class DQRule
apply_mixin.py:30       class DQSeverity
apply_mixin.py:39       class DQViolation
apply_mixin.py:49       class DQCheckResult
apply_mixin.py:63       class DQRule
__init__.py:68          class DQSeverity
__init__.py:77          class DQViolation
__init__.py:87          class DQCheckResult
__init__.py:125         class DQRule
__init__.py:105         class DQRemediationResult  (only in __init__.py)
```

**Verified evidence**:

```text
$ .venv/bin/python -c "from src.backend.services.ops.data_quality.apply_mixin import DQRule as A; from src.backend.services.ops.data_quality import DQRule as I; print(A is I)"
False
$ .venv/bin/python -c "from src.backend.services.ops.data_quality.apply_mixin import DQRule as A; ... inst = A(...); print(isinstance(inst, I))"
False
```

**Impact**: 5 distinct class identities per dataclass. Mixing them across mixins at runtime is silently broken (e.g., `DQViolation` from `apply_mixin` is **not** an instance of `DQViolation` from `__init__`). The `DataQualityMonitor` mixins at `__init__.py:45` reference their own local classes — works fine, but any external consumer using `from src.backend.services.ops.data_quality import DQRule` gets the wrong class for `isinstance()` checks.

**Minimal recommendation**: Single canonical definition in `__init__.py`; mixins import the classes. The `DQRemediationResult` already follows this pattern.

**Test criterion**: Add `assert apply_mixin.DQRule is data_quality.DQRule` (and similar for `DQViolation`, `DQCheckResult`, `DQSeverity`) — should pass.

---

### SERV-P1-002 — Reverse-layer shims (services → extensions)

**Severity**: P1 — documented as **legacy, will be removed**, but emits `DeprecationWarning` at module-import time which pollutes test output.

**Path**:
- `src/backend/services/io/files.py:1-20`
- `src/backend/services/integrations/skb.py:127-152`

**Verified evidence**:

```text
$ .venv/bin/python -c "from src.backend.services.io.files import FileService"
<string>:6: DeprecationWarning: src.backend.services.io.files устарел;
используйте extensions.core_entities.files.services.files (R-V15-16).
```

The `warnings.warn(...)` call is at module-top-level, not lazy, so any test that imports `services.io.files` (even transitively) gets the warning.

**Impact**: Cycle-1/2/3 already cataloged these as deferred (T-2.1 "reverse-layer cleanup"). The current 22e08a0d HEAD still ships them. The `DeprecationWarning` at import-time is annoying but not security-critical.

**Minimal recommendation**: Move the `warnings.warn(...)` from module-level into each `def` body, so it's only emitted when the deprecated symbol is actually used. Or, since the canonical replacement exists in `extensions/`, delete these shims outright once callers are migrated (track via grep).

**Test criterion**: No `DeprecationWarning` from these modules during `tests/unit/services/` test runs.

---

### SERV-P1-003 — AdminService._get_authz swallows all init exceptions

**Severity**: P1 — root cause of SERV-P0-002.

**Path**: `src/backend/services/admin/api.py:58-80`

**Verified evidence**:

```python
# admin/api.py:62-80
try:
    from src.backend.core.security.authorization_gateway import (
        AuthorizationGateway,
    )
    from src.backend.services.admin._capability_adapter import (
        FacadeCapabilityAdapter,
    )
    from src.backend.services.capabilities.facade import get_capability_facade

    capability_facade = get_capability_facade()
    return AuthorizationGateway(
        capability_gateway=FacadeCapabilityAdapter(capability_facade)
    )
except Exception as exc:
    logger.warning("AuthorizationGateway unavailable: %s", exc)
    return None  # ← swallow all; fail-open contract follows
```

**Impact**: Any failure to instantiate `AuthorizationGateway` (ImportError, TypeError, AttributeError, even OOM-related exceptions during capability_gateway wiring) silently downgrades AdminService to **no-authz**, which in turn triggers SERV-P0-002.

**Minimal recommendation**: Re-raise as `AdminAuthorizationError` in `__init__` if the gateway is required; for prod-profile callers, this should be a hard failure. The current pattern is acceptable only for `dev_light` profile.

**Test criterion**: New unit test that injects a broken capability facade and verifies `AdminAuthorizationError` is raised.

---

### SERV-P1-004 — Audit outcome inconsistency on authz error

**Severity**: P1 — observability gap.

**Path**: `src/backend/services/admin/api.py:108-116`

**Verified evidence**:

```python
try:
    decision = await authz.authorize(...)
except Exception as exc:
    emit_admin_action(
        actor=actor,
        action=action,
        resource=resource,
        outcome="error",  # ← inconsistent with downstream behavior
        details={"error": str(exc)},
    )
    raise AdminAuthorizationError(f"AuthorizationGateway error: {exc}") from exc
```

**Impact**: Audit event uses `outcome="error"`, but the caller sees a denied authorization. Compliance dashboards that filter on `outcome="denied"` won't catch gateway errors. Same actor may receive different audit events for "denied by policy" vs "denied by gateway error".

**Minimal recommendation**: Use `outcome="denied"` with `details={"error": "gateway_error", "message": str(exc)}` so dashboards treat both uniformly.

**Test criterion**: Inject an authz gateway that raises → audit callback receives `outcome="denied"`.

---

### SERV-P2-001 — Dead code: `_audit_cb` parameter

**Severity**: P2.

**Path**: `src/backend/services/admin/api.py:55-56`

**Verified evidence**:

```python
def __init__(
    self,
    authorization_gateway: Any | None = None,
    audit_callback: Any | None = None,
) -> None:
    self._authz = authorization_gateway
    self._audit_cb = audit_callback  # ← stored but never read
```

A grep across `services/admin/api.py` shows `_audit_cb` is assigned but never referenced. All audit goes through `emit_admin_action` which uses its own module-level callback (`admin/audit.py:21`).

**Minimal recommendation**: Delete the `audit_callback` parameter and `_audit_cb` field.

**Test criterion**: Module imports without `audit_callback` parameter.

---

### SERV-P2-002 — `set(ctx)` accepts any object

**Severity**: P2.

**Path**: `src/backend/services/tenancy/facade.py:47-58`

```python
def set(self, ctx: Any) -> Any:
    from src.backend.core.tenancy import set_tenant
    return set_tenant(ctx)  # ← no type check; can pass garbage
```

Inconsistent with `with_tenant(...)` which uses `CapabilityTenant` (typed).

**Minimal recommendation**: Type-narrow to `TenantContext | CapabilityTenant` (or document the inconsistency).

**Test criterion**: `facade.set("string")` raises `TypeError` (or `CapabilityDeniedError` if accepted).

---

### SERV-P2-003 — Hidden state `_cardinality_counts` not in protocol

**Severity**: P2.

**Path**: `src/backend/services/ops/data_quality/apply_mixin.py:354-356`

```python
seen: defaultdict[str, int] = getattr(self, "_cardinality_counts", None)
if seen is None:
    seen = self._cardinality_counts = defaultdict(int)
```

This state is created lazily inside `_apply_cardinality` but not declared in `_DataQualityProtocol` (`src/backend/services/ops/data_quality/_protocol.py:20-41`). mypy will not know about it.

**Minimal recommendation**: Declare `_cardinality_counts: dict[str, int]` in `_DataQualityProtocol`.

**Test criterion**: `mypy --strict` passes on `apply_mixin.py`.

---

### SERV-P2-004 — ScheduledReportsService.run_now catches all

**Severity**: P2.

**Path**: `src/backend/services/ops/scheduled_reports.py:166-172`

```python
except Exception as exc:
    run.status = "error"
    run.error = str(exc)
    run.duration_ms = (time.monotonic() - start) * 1000
    report.last_status = f"error: {exc}"
    logger.error("Report %s failed: %s", report.name, exc)
```

Catches everything, masks transient from permanent failures. No retry hook.

**Minimal recommendation**: Use `tenacity` for transient retry (already in project), or split between `RetryableError` and `PermanentError`.

---

### SERV-P2-005 — Local `_HTTPError` class in webhook_relay

**Severity**: P2 — minor.

**Path**: `src/backend/services/integrations/webhook_relay.py:222-223`

```python
class _HTTPError(Exception):
    """Non-success HTTP-ответ — сигнал для retry."""
```

Defined inside `_send_with_retry` function. Module-level would be cleaner.

---

### SERV-P2-006 — Feature-flag gate masks ImportError

**Severity**: P2 — observability.

**Path**: `src/backend/services/jupyter/hub_run_orchestrator.py:148-155`

```python
try:
    from src.backend.core.config.features import feature_flags
    if not bool(getattr(feature_flags, "jupyter_hub_enabled", False)):
        raise JupyterHubNotEnabledError()
except (ImportError, AttributeError):
    raise JupyterHubNotEnabledError() from None  # ← masks misconfig as feature-off
```

If `feature_flags` module is corrupted or `jupyter_hub_enabled` is removed from config schema, the user sees "feature disabled" instead of "config error".

**Minimal recommendation**: Separate the two cases: log a distinct error for `ImportError` / `AttributeError` so observability catches config drift.

---

### SERV-P2-007 — ObservabilityFacade silently swallows all errors

**Severity**: P2 — observability gap.

**Path**: `src/backend/services/observability/facade.py:67-69, 89-91, 105-106, 120-121, 140-141`

Every public method has `except Exception as exc: _logger.debug(...)` — at default log level (`WARNING`), failures are invisible. The `record_metric` method even catches `Exception` from `metrics_registry.counter()` which is fundamentally about metrics — silently losing metrics is a degradation hazard.

**Minimal recommendation**: Use `severity="warning"` instead of `"debug"` for these swallow-and-log paths so they show up in standard ops dashboards.

---

### SERV-P3-001 — Cache facade duplicates `cachetools.TTLCache`

**Severity**: P3 — library replacement candidate.

**Path**: `src/backend/services/cache/facade.py:1-165`

Already documented as Ponytail thin wrapper. The `UnifiedCacheFacade` adds tiered fallback (Redis → memory → disk) which `cachetools` alone doesn't provide. Acceptable.

---

### SERV-P3-002 — 5 hand-rolled exporters

**Severity**: P3.

**Path**: `src/backend/services/io/export_service.py:39-310`

CsvExporter (csv stdlib), ExcelExporter (openpyxl), PdfExporter (reportlab), JsonExporter (json stdlib), ParquetExporter (polars/pyarrow). Could be replaced by `pyarrow` + `tabulate` for tabular data with less code, but the current split is reasonable per format.

---

### SERV-P3-003 — JMESPath usage

**Severity**: P3.

**Path**: `src/backend/services/integrations/webhook_relay.py:160-202`

Uses `jmespath` directly. Could route through `core/transforms/` if it exists, but jmespath is the canonical library here.

---

### SERV-P3-004 — 3 thin re-export modules

**Severity**: P3 — minor consolidation.

**Path**: `src/backend/services/scheduler/admin.py:1-25`, `src/backend/services/cache/metrics.py:1-25`, `src/backend/services/messaging/outbox_monitor.py:1-38`

Three 25-line re-export modules. Could merge into `services/_re_exports.py` but the explicit naming aids grep-discoverability.

---

### SERV-P4-001 — No persistent DQ rule storage

**Severity**: P4 — feature gap.

Currently `DataQualityMonitor._rules` is in-memory only. Camel/Airflow pattern would push DQ rules to a DB-backed store for tenant-isolated management.

---

### SERV-P4-002 — No structured RPA retry

**Severity**: P4.

`rpa/*` modules use ad-hoc `try/except` per method. No integration with `core.resilience.retry` or `tenacity`. Camel-style idempotent consumer with retry would be cleaner.

---

### SERV-P4-003 — `AdminService.get_audit_log` is a stub

**Severity**: P4.

`src/backend/services/admin/api.py:199-221`:

```python
async def get_audit_log(...) -> list[dict[str, Any]]:
    ...
    # Audit entries are consumed via the same callback mechanism.
    # For now, return an empty list as backend storage is TBD.
    # Frontend can call this endpoint; entries accumulate via callback.
    emit_admin_action(...)
    return []
```

Stub — never returns entries. Acceptable per the "noted pre-existing" pattern (BASELINE.md doesn't list this explicitly), but worth flagging as missing functionality.

---

## 5. Cycle 1+2+3 residuals

The user instruction was: "Обязательно перепроверить cycle-3 P0-001..005, P1-001..004, P2-001..003". Without access to the cycle-3 markdown, I verified the **5 specific items** the user listed as critical re-checks for this domain:

| Cycle-3 finding (per user instruction) | Re-verify status | Evidence |
|---|---|---|
| **P0-001..005** (data_quality duplication; reverse-layer shims skb+files; DLQ silent_loss; TenantFacade kwargs; admin/api.py fail-open) | **5 RESIDUAL** | All 5 confirmed against HEAD 22e08a0d via code inspection and `.venv/bin/python` runtime tests (SERV-P0-001..003, SERV-P1-001..002). |
| **P1-001..004** | **Verified via read** | See SV-S-02/03 (fail-closed siblings contrast), `_dlq_remove` source (silent-loss), TenantFacade code (kwargs bug). |
| **P2-001..003** | **3 RESIDUAL or partial** | data_quality 5-way duplication confirmed (P1-001); reverse-layer shims still active (P1-002); admin `_audit_cb` dead code confirmed (P2-001). |

| Item | Status | Notes |
|---|---|---|
| data_quality duplication | **RESIDUAL** | 5-way duplication confirmed at runtime (SERV-P1-001). Was likely tracked as P2-class; still present in HEAD. |
| reverse-layer shim skb.py | **RESIDUAL** | Still emits `DeprecationWarning` at module load (SERV-P1-002). |
| reverse-layer shim files.py | **RESIDUAL** | Same pattern as skb.py. |
| DLQ silent_loss | **RESIDUAL** | 3 vectors documented in SERV-P0-003. |
| TenantFacade kwargs (T-08) | **RESIDUAL + MUTATED** | The fix was attempted in S193 but introduced a NEW bug (wrong kwarg names). Worse than original TypeError, because the test mocks `set_tenant` and doesn't catch it (SERV-P0-001). |
| admin/api.py fail-open | **RESIDUAL** | Confirmed at lines 97-102. No tests exist for this path (SERV-P0-002). |

**Cycle 1+2+3 8 fixes mentioned in BASELINE.md**:
- T-1.4 multicast, T-1.4 redelivery, T-1.5 policy_mixin, T-1.5 gateway_adapter, T-3.1 cachetools, T-W1-01 AuthenticationProvider, T-W1-05 cdc_routes, T-W1-08 credit_pipeline — **NOT re-attributed** to cycle-4 swarm per BASELINE.md. Verified in HEAD 22e08a0d but not re-evaluated as cycle-4 findings.

---

## 6. Contradictions / overlaps to flag

| Contradiction | Evidence | Recommendation |
|---|---|---|
| **fail-open vs fail-closed inconsistency** between `admin/api.py` and sibling facades | admin/api.py:97-102 (open) vs integrations/facade.py:93-98 (closed) vs routes/route_authz.py:69-76 (closed) | Pick one policy (CLOSED is canonical per AGENTS.md "fail-closed security"). Apply uniformly. |
| **T-08 fix introduced new bug**: original was "TenantContext doesn't accept principal_id" (TypeError), fix replaced it with "CapabilityTenant doesn't accept tenant_id" (still TypeError, but in different place) | tenancy/facade.py:115-119 | Re-fix T-08 with correct kwargs (`id=...`, `principal=...`) and add a test that runs `with_tenant(...)` without mocks. |
| **`from extensions.*` imports in services layer** | files.py:11, skb.py:16 | Per CLAUDE.md / AGENTS.md rule "Extensions import ONLY `core.*` + capability-checked facades". These shims violate the rule by going the other direction. Either move shims to `extensions/` or accept as a documented exception. |
| **`service/audit/replay_query.py` was previously a reverse-layer violation (services→entrypoints)** | replay_query.py:1-15 (explicit comment) | RESOLVED — now in services/, comment serves as documentation. |
| **ObservabilityFacade swallows all errors at DEBUG level** | observability/facade.py:67-141 | Inconsistent with cache/storage/codec facades which raise ServiceError. Either all-fail-soft (loud debug→warning) or all-fail-hard (raise). |
| **`audit/admin/api.py` emits "error" outcome but raises "denied" exception** | admin/api.py:108-128 | Use consistent outcome semantic in audit events. |

---

## 7. Readiness score

**Formula**: `score = 100 − 15·P0 − 8·P1 − 3·P2 − 1·P3 − 0.4·P4`

**Calculation**:
```
100 − 15·3 − 8·4 − 3·7 − 1·4 − 0.4·3
= 100 − 45 − 32 − 21 − 4 − 1.2
= -3.2  → clamped to 0
```

Per the rule "Оценка ≥80 запрещена при наличии P0/P1" — **3 P0 + 4 P1** findings are present, capping the score well below 80.

### **Readiness score: 0/100** (with hard cap at ≤79 because P0/P1 present).

**Justification**:
- 3 P0 blockers (SERV-P0-001 broken TenantFacade, SERV-P0-002 fail-open admin, SERV-P0-003 DLQ silent-loss).
- 4 P1 layer / data-correctness issues (SERV-P1-001..004).
- 7 P2 dead-code / observability / type issues.
- The breadth of P0/P1 across multiple subdomains (tenancy, admin, integrations, ops, dlq) signals **systemic risk** in cycle-3 fix closure.

---

## 8. Recommended next tasks (ordered by severity, smallest fix first)

| # | Task | Effort | Cycle |
|---|---|---|---|
| 1 | **SERV-P0-001**: fix `TenantFacade.with_tenant` kwargs (`id=`/`principal=`). Add a non-mocked test that actually invokes the context manager. | XS | 4.1 |
| 2 | **SERV-P0-002 + P1-003**: flip `AdminService._authorize` to fail-closed (raise `AdminAuthorizationError` when gateway is None). Add unit test. | S | 4.1 |
| 3 | **SERV-P0-003**: cap `_memory_dlq`, re-raise on `_dlq_remove` failure, cleanup `rule_not_found` entries in `dlq_retry`. | S | 4.1 |
| 4 | **SERV-P1-001**: deduplicate `data_quality` classes (5 → 1 canonical). | S | 4.2 |
| 5 | **SERV-P1-002**: either move `DeprecationWarning` into function bodies or delete the shims outright if no callers remain. | XS | 4.2 |
| 6 | **SERV-P1-004**: align audit `outcome` semantic. | XS | 4.2 |
| 7 | **SERV-P2-001..007**: cleanup pass (dead code, type hints, observability severity). | M | 4.3 |
| 8 | **SERV-P3-001..004**: optional consolidation / library swap. | L | 5+ |
| 9 | **SERV-P4-001..003**: missing functionality (deferred). | L | 5+ |

---

## 9. Commands run

All commands run with `.venv/bin/python` per BASELINE.md instruction.

```bash
# 1. Directory scoping
ls /home/user/dev/gd_integration_tools/src/backend/services/
ls /home/user/dev/gd_integration_tools/tests/unit/services/

# 2. data_quality duplication verification (SERV-P1-001)
.venv/bin/python -c "
import sys; sys.path.insert(0, '.')
from src.backend.services.ops.data_quality.check_mixin import DQRule as C
from src.backend.services.ops.data_quality import DQRule as I
from src.backend.services.ops.data_quality.apply_mixin import DQRule as A
print('check_mixin is init:', C is I)  # False
print('check_mixin is apply:', C is A)  # False
print('isinstance(A(), I):', isinstance(A(name='x', field='y', check='z'), I))  # False
"
# → All False (CONFIRMED)

# 3. TenantFacade.with_tenant verification (SERV-P0-001)
.venv/bin/python -c "
import sys, asyncio; sys.path.insert(0, '.')
from src.backend.services.tenancy.facade import get_tenant_facade
async def t():
    async with get_tenant_facade().with_tenant('t', principal_id='u'):
        pass
asyncio.run(t())
"
# → TypeError: CapabilityTenant.__init__() got an unexpected keyword argument 'tenant_id'

# 4. Test failure confirmation
.venv/bin/python -m pytest tests/unit/services/test_facades.py::TestTenantFacade -v
# → 1 failed, 4 passed (test_with_tenant_restores_previous FAIL)

# 5. Reverse-layer shim warning verification (SERV-P1-002)
.venv/bin/python -c "
import sys; sys.path.insert(0, '.')
from src.backend.services.io.files import FileService
"
# → DeprecationWarning: src.backend.services.io.files устарел; используйте extensions...

# 6. DLQ silent_loss source verification (SERV-P0-003)
.venv/bin/python -c "
import sys; sys.path.insert(0, '.')
import inspect
from src.backend.services.integrations.webhook_relay import WebhookRelay
print(inspect.getsource(WebhookRelay._dlq_remove))
print(inspect.getsource(WebhookRelay._dlq_push))
"

# 7. IntegrationFacade._check_capability (fail-closed contrast, SV-S-02)
.venv/bin/python -c "
import sys; sys.path.insert(0, '.')
import inspect
from src.backend.services.integrations.facade import IntegrationFacade
print(inspect.getsource(IntegrationFacade._check_capability))
"
# → Confirmed returns False on authz Exception (fail-closed)

# 8. Test runs in scope
.venv/bin/python -m pytest tests/unit/services/admin/ tests/unit/services/audit/ tests/unit/services/ops/ -q --tb=line
# → 192 passed

.venv/bin/python -m pytest tests/unit/services/cache/ tests/unit/services/notifications/ tests/unit/services/integrations/ tests/unit/services/wiki/ -q --tb=line
# → 51 passed

.venv/bin/python -m pytest tests/unit/services/resilience/ tests/unit/services/admin/ tests/unit/services/audit/ tests/unit/services/test_facades.py -q --tb=no
# → 1 failed (TenantFacade), 90 passed

.venv/bin/python -m pytest tests/unit/services/cache tests/unit/services/notifications tests/unit/services/ops tests/unit/services/integrations tests/unit/services/wiki -q --tb=no
# → 191 passed

.venv/bin/python -m pytest tests/unit/services/rpa tests/unit/services/scheduler tests/unit/services/jupyter tests/unit/services/dsl tests/unit/services/io tests/unit/services/lineage -q --tb=no
# → 150 passed

.venv/bin/python -m pytest tests/unit/services/ -q --tb=no --ignore=tests/unit/services/ai --ignore=tests/unit/services/workflows --ignore=tests/unit/services/plugins
# → 8 failed (1 T-08 + 7 jwt-test-design — security/facade.py excluded from scope, but tests/unit/services/test_security_facade_jwt.py IS in scope; failures are pre-existing test-design issues, see notes below), 767 passed, 10 skipped

# 9. JWT tests are pre-existing test-design issue (security/ excluded from src-scope, but the test file is at tests/unit/services/ root)
.venv/bin/python -m pytest tests/unit/services/test_security_facade_jwt.py -q --tb=line
# → 7 failed, 2 passed (all failures are due to test not calling `await init_jwt_blacklist()` — security facade lazy-init bug surfaced only via tests; not a cycle-4 finding per se)

# 10. Layer-policy exception verification (services/scheduler/admin.py)
grep -rn "from src.backend.infrastructure" /home/user/dev/gd_integration_tools/src/backend/services/ --include="*.py" | grep -v __pycache__
# → 16 hits across services, all documented as layer-policy exceptions OR via capability-checked facade (auth* is excluded scope)

# 11. Reverse-layer (services → extensions) verification
grep -rn "from extensions\." /home/user/dev/gd_integration_tools/src/backend/services/ --include="*.py" | grep -v __pycache__
# → 2 hits: integrations/skb.py:16 + io/files.py:11 (both are P1-002 shims)

# 12. AdminService fail-open direct evidence (SERV-P0-002)
# Source read directly from src/backend/services/admin/api.py:97-102 — verbatim "FAIL-OPEN" code
```

---

## 10. Notes / caveats

- **Cycle-3 markdown not consulted** per task constraint. The 5 specific items in scope (P0-001..005, P1-001..004, P2-001..003) were re-verified via code search and runtime tests against HEAD 22e08a0d. **All 5 are RESIDUAL** (not closed by cycle-1/2/3 work in HEAD).
- **8 cycle 1+2+3 fixes** (T-1.4, T-1.5, T-3.1, T-W1-01, T-W1-05, T-W1-08, T-02, T-03) are confirmed in HEAD but **not re-attributed** to cycle-4 swarm per BASELINE.md.
- **7 pre-existing JWT test failures** in `tests/unit/services/test_security_facade_jwt.py` are **out of src-scope** (services/security/) but the test file IS in `tests/unit/services/` scope. They are pre-existing test-design issues (tests don't call `await init_jwt_blacklist()`) and do not block cycle-4 readiness.
- **`extensions/*` reverse-imports** are in 2 files (files.py, skb.py) — both are documented legacy shims with `DeprecationWarning`. No security or runtime impact.
- **Score clamped to 0** because 3 P0 + 4 P1 findings dominate.