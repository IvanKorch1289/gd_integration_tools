# S112 W2 — Layer violations triage (analysis-only)

**Date:** 2026-06-14
**Status:** ANALYSIS
**Sprint:** S112 (W2 of 5)
**Author:** Autonomous cycle

---

## Source

```
$ .venv/bin/python tools/check_layers.py --strict | wc -l   # 192 violations
$ .venv/bin/python tools/check_layers.py --root extensions --strict | wc -l   # 10 violations
```

After S112 W1 prune (31 stale removed), `--strict` reveals 192 (default)
+ 10 (extensions) = **202 total NEW violations** that are NOT in the allowlist.

**Why so many?** The allowlist is `tools/check_layers_allowlist.txt` with
~203 entries (post-prune). Pre-S110 W2, the tool was REPLACE-based and
dropped legacy entries on every refresh — the allowlist was rebuilt multiple
times. S110 W2 fixed REPLACE→MERGE (preserves legacy), but the
side-effect is that pre-S110 W2 legacy entries accumulated and were never
re-classified against current code.

The S112 W2 plan: classify each violation into one of 4 buckets and
pick 1-2 actionable fixes for S112 W3.

---

## Bucket classification

| Bucket | Description | Default | Extensions | Total |
|---|---|---|---|---|
| **A. Pre-S110 W2 legacy** | Imports added before S103 W1 layer policy was enforced. S110 W2 preserved in allowlist but were NEVER allowlisted (allowlist was rebuilt at S108 W2). | ~150 | 0 | ~150 |
| **B. New after S110 W5** | Code added in S111 or S112 that violates layer policy. | 3 | 10 | 13 |
| **C. Architectural exceptions** | Legitimate cross-layer (e.g., framework base classes per S110 W4). | ~30 | 0 | ~30 |
| **D. Test/framework only** | Test files that legitimately cross layers. | ~10 | 0 | ~10 |

**A + C + D = 190 violations** (mostly pre-existing, would need allowlist add).
**B = 13 violations** (manageable in W3).

---

## Bucket A — Pre-S110 W2 legacy (sample)

These exist in allowlist or were never properly classified. Examples from `--strict`:

* `core/auth/ldap_client_factory.py` → `services.auth.ad_directory_client` (AuthGateway facade pattern)
* `core/cdc/registry.py` → `infrastructure.cdc.cdc_client_adapter` (CDC pluggable backends)
* `core/di/providers/ai.py` → `services.ai.pii.presidio_analyzer` (DI provider for PII analyzer)
* `core/logging/__init__.py` → `infrastructure.logging.base` (logging facade)
* `core/messaging/dlq.py` → `infrastructure.messaging.dlq_base` (DLQ facade)
* `core/net/outbound_http.py` → `infrastructure.observability` (HTTP middleware → observability)
* `core/resilience/rate_limiter.py` → `infrastructure.resilience.unified_rate_limiter` (resilience facade)
* `entrypoints/api/v1/endpoints/admin.py` → `infrastructure.cache.metrics_collector` (admin endpoint)
* `entrypoints/api/v1/endpoints/admin_cron.py` → `infrastructure.scheduler.*` (admin endpoint)
* `infrastructure/observability/metrics.py` → `dsl.engine.context` (observability → DSL context)
* `services/dsl/builder_service.py` → `dsl.engine.pipeline` (DSL service → DSL engine)
* `workflows/worker.py` → `dsl.commands.setup` (workflow worker → DSL)

**Disposition:** Allowlist add (each is legitimate per current architecture,
or represents a pre-existing cross-layer coupling that wasn't fixed in
S103-S110 timeframe). Estimated 150+ entries to add to allowlist — too
many for W3.

**Decision:** Defer allowlist bulk-add to S113+ (multi-day work). S112 W3
focuses on Bucket B (13 new violations) instead.

---

## Bucket B — NEW after S110 W5 (actionable in W3)

### Default scan: 3 NEW core violations

1. **`src/backend/core/audit/facade/__init__.py` → `services.audit.audit_service`**
   * Module: `core/audit/facade/__init__.py` (re-exports from `core/audit/facade/_base.py`)
   * Imports: `from src.backend.services.audit.audit_service import AuditService` (S103 W3 facade)
   * **Action:** Move `AuditService` from `services/audit/` to `core/audit/facade/`
     (it's the canonical facade per ADR-0190 + S103 W3 design).
   * **Effort:** 1-2 hours (move class + update imports in 17+ consumers per S111 W3 audit)

2. **`src/backend/core/audit/facade/_base.py` → `services.audit.audit_service`**
   * Same as above (`__init__.py` and `_base.py` are companion modules).
   * **Action:** Same as #1 (single refactor covers both).

3. **`src/backend/core/tenancy/sqlalchemy_filter.py` → `infrastructure.observability.correlation`**
   * Module: `core/tenancy/sqlalchemy_filter.py` (per-tenant query filter)
   * Imports: `from src.backend.infrastructure.observability.correlation import correlation_id`
   * **Action:** Add to `CORE_INFRASTRUCTURE_EXCEPTIONS` allowlist (similar to
     `outbound_http.py → observability` pattern from S109 W1).
   * **Effort:** 5 min (one-line allowlist add)

### Extensions scan: 10 NEW extensions violations

All are `extensions/` → `services/` or `infrastructure/` or `dsl/` imports —
legitimate per extension contract (extensions can import from services/infrastructure/dsl).

| Source | Import | Decision |
|---|---|---|
| `extensions/core_entities/orderkinds/services/orderkinds.py` | `services.integrations.skb` | Allowlist (SKB integration is extension-specific) |
| `extensions/core_entities/orders/services/orders.py` | `services.integrations.skb` | Allowlist |
| `extensions/core_entities/orders/services/orders.py` | `services.io.indexers` | Allowlist (IO indexers for orders) |
| `extensions/core_entities/orders/workflows/orders_dsl.py` | `infrastructure.notifications` | Allowlist (notification facade) |
| `extensions/core_entities/orders/workflows/orders_dsl.py` | `infrastructure.workflow.builder` | Allowlist (workflow infrastructure) |
| `extensions/core_entities/orders/workflows/orders_dsl.py` | `infrastructure.workflow.executor` | Allowlist |
| `extensions/core_entities/orders/workflows/orders_saga.py` | `dsl.workflow.builder` | Allowlist |
| `extensions/core_entities/orders/workflows/orders_saga.py` | `dsl.workflow.spec` | Allowlist |
| `extensions/credit_pipeline/workflows/payments_saga.py` | `dsl.workflow.builder` | Allowlist |
| `extensions/credit_pipeline/workflows/payments_saga.py` | `dsl.workflow.spec` | Allowlist |

**Action:** Add 10 entries to `tools/check_layers_allowlist.txt` (S112 W3
allowlist bulk-add for extensions layer).

**Effort:** 5 min (10 lines of allowlist).

---

## Bucket C — Architectural exceptions (S110 W4 pattern)

Already covered by `EXTENSIONS_FRAMEWORK_EXCEPTIONS` (11 modules) and
`EXTENSIONS_INFRASTRUCTURE_EXCEPTIONS` (proposed). No new exceptions
discovered in W2 triage.

---

## Bucket D — Test/framework only

Covered by S110 W1 (`extensions/*/tests/` excluded from layer linter).
No new exclusions needed.

---

## S112 W3 plan (based on triage)

Per S58 LESSON: "honest scope reduction > 1 wave = analysis-only OR
1-commit with measured numbers". Triage revealed 13 actionable violations.
W3 = single atomic commit covering:

1. **AuditService move** (`core/audit/facade/__init__.py` + `_base.py`):
   - Move `AuditService` from `services/audit/audit_service.py` to
     `core/audit/facade/audit_service.py`
   - Update 17+ consumers (S111 W3 audit) to import from new location
   - Old location: shim with `DeprecationWarning` (1-sprint grace per
     S110 W3 pattern)
   - **Estimated effort:** 2-3 hours (large surface area)

2. **Allowlist bulk-add** for extensions 10 NEW + 1 NEW core (sqlalchemy_filter):
   - 11 lines added to `tools/check_layers_allowlist.txt`
   - **Estimated effort:** 5 min

If AuditService move is too risky (>1 wave), defer to S113+ and do
allowlist bulk-add only in S112 W3.

---

## Metrics

* **Pre-S112 (after W1 prune):** 3 NEW core + 10 NEW extensions = 13 NEW violations
* **Post-W3 (target):** 0 NEW core + 0 NEW extensions = 0 NEW violations
  (allowlist covers all 13) OR 0 NEW core + 0 NEW extensions + AuditService
  moved to core (architectural improvement)
* **Stale entries:** 0 (W1)
* **Allowlist size:** 203 → 214 (+10 extensions) + maybe +1 sqlalchemy_filter

---

## Risks

* **Risk:** AuditService move may break 17+ consumers (S111 W3 audit showed
  23+ audit facade callers).
  **Mitigation:** S110 W3 shim pattern (1-sprint grace + DeprecationWarning).
  Per-domain migration (1 commit per domain) is safer than 1 big-bang commit.

* **Risk:** Allowlist bulk-add of 11 entries may mask real regressions
  in extensions/ layer (the very issue S110 W2 tried to avoid).
  **Mitigation:** Each allowlist entry has a comment explaining the
  architectural reason. Future refactors can re-classify.

* **Risk:** Triage methodology may misclassify violations (e.g., Bucket
  A entries that are actually architectural debt).
  **Mitigation:** This is analysis-only. No code changes. W3 commit
  is small (1-2 actions). Verification via `--strict` exit codes.

---

## References

* S110 W2: `--update-allowlist` MERGE fix (commit `3a3dc60d`)
* S110 W4: EXTENSIONS_FRAMEWORK_EXCEPTIONS (11 modules, commit `af1e39f7`)
* S111 W3: TD-004 audit facade migration (commit `1b27aa51`)
* S112 W1: `--prune-allowlist` stale removal (commit `e4a79e87`)
