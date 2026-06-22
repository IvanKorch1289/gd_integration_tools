# ADR-0250 — Sprint 45: Audit Backlog QW10 + S1 Closure

**Дата**: 2026-06-22
**Sprint**: 45
**Status**: ✅ ACCEPTED (2 atomic commits merged)
**Depends on**: ADR-0248, ADR-0249

## Context

Sprint 44 (ADR-0249) закрыл facades + migrations для S2 + S7 + SDK gap. Sprint 45
продолжает audit backlog с QW10 (services/audit shim) и S1 (entrypoints→infra).

## Decision

2 atomic commits с facades pattern + backward-compat shim deletion.

### Commit 1: `40b811a` — refactor(s45-w1): delete audit shim (QW10)

**Проблема**: `services/audit/audit_service.py` (18 LOC) был backward-compat shim
per ADR-0199 (S113 W1). Deprecation cycle истёк — shim можно удалить.

**Fix**:
- DELETE `src/backend/services/audit/audit_service.py` (18 LOC shim)
- DELETE `tests/unit/core/audit/test_audit_service_shim.py` (47 LOC shim-specific test)
- 4 source consumers migrated: `unified_sink_factory.py`, `agent_dsl/_base.py`,
  `gateway_pipeline_mixin/observability_mixin.py`, `di/providers/ai.py`
- 5 test files updated: `test_audit_service_unified.py`, `test_gateway.py` (2x),
  `test_gateway_pipeline_mixin.py`, `test_facade.py`, `test_facade_split.py`
- `services/audit/__init__.py` updated to import from canonical
- 1 docstring updated: `infrastructure/security/token_registry.py`
- 2 stale allowlist entries pruned (core→services.audit.audit_service)

**Verification**:
- 27 audit tests pass
- Canonical `AuditService` is same object across all import paths (verified `is` operator)
- Identity tests in test_facade.py + test_facade_split.py updated to verify canonical identity
  (trivially True после удаления shim)

### Commit 2: `63339e7` — refactor(s45-w2): S1 entrypoints→infra migration

**Проблема**: 9 entrypoints→infra imports нарушали V22 invariant. Audit backlog S1.

**Fix**:
- 5 new services facades (pure re-export, ~15 LOC each):
  - `services/workflow/__init__.py` (workflow_registry)
  - `services/security/__init__.py` (signatures)
  - `services/resilience/rate_limiter.py` (rate_limiter)
  - `services/scheduler/admin.py` (DLQ + manager)
  - `services/cache/metrics.py` (cache + RAG metrics)
- 8 entrypoints files migrated: `mcp/workflow_tools.py`, `dependencies/rate_limit.py`,
  `middlewares/ws_rate_limit.py`, `middlewares/webhook_signature.py`,
  `api/v1/endpoints/admin_scheduler_dlq.py`, `rag_cache_admin.py`, `admin.py`,
  `admin_workflows/facade.py`
- 1 test patch target update: `test_admin_scheduler_dlq.py`
- 7 allowlist entries added (services→infra facade exception, consistent with
  outbox_monitor from S44 W3)
- 9 stale allowlist entries pruned (200 legacy baseline, was 209)

**S1 BACKLOG CLOSED**: 8/8 entrypoints→infra imports migrated через services facades.

## Verification Summary

| Метрика | S44 | S45 | Net |
|---|---|---|---|
| Atomic commits | 5 | 2 | 7 (S44+S45) |
| Files touched | 235 | 27 | 262 |
| Layer linter | 0 NEW | 0 NEW | 0 NEW |
| Legacy baseline | 204 | 200 | -4 (pruned) |

## Out of scope (deferred → S46+)

| ID | Item | Причина defer |
|---|---|---|
| S13 | Circuit breaker middleware → shared state | High risk, K8s multi-pod |
| S7 | 4 BLOCKED файлов в foreign WIP | После foreign WIP merge |
| 1 entry | `admin_plugins/helpers.py` | В foreign WIP (UP-9) |

## Cross-references

- ADR-0248 (S43 deep-audit-quick-wins) — основа для audit
- ADR-0249 (S44 audit-followup-facades) — facade pattern
- ADR-0199 (S113 W1: audit shim policy) — QW10
- ADR-0196 (S110 W4: framework exceptions) — extensions facade model
- `docs/audit/DEEP-AUDIT-2026-06-22.md` — full audit (S43 W1)
