# ISOLATED_MODULES_DECISIONS — Consolidated registry

> **Audit 2026-09-21**: 39 изолированных core/ модулей найдены
> (zero production callers). Этот документ — **консолидированные рекомендации**
> по каждому модулю.
>
> **Per-module DEPRECATED.md файлы**: для high-priority модулей
> (см. `core/rate_limiter/DEPRECATED.md`, `core/idempotency/DECISION_NOTE.md`).
> Для остальных 37 — этот файл является единым decision registry.

## Methodology

Caller count = number of non-empty matches of `core.<module_name>` в .py файлах
вне самого пакета модуля. Tests included for visibility, но НЕ считаются
production usage.

Решение:
- **DELETE** — duplicate / dead code / уже есть mature alternative
- **WIRE** — потенциально полезно, может быть подключено через DI / facade
- **EXPERIMENTAL** — keep с явным feature flag или extensions/ subpath
- **PENDING** — требует owner review / multi-sprint work

## 39 isolated modules — decisions

| # | Module | Recommendation | Justification |
|---|---|---|---|
| 1 | `core.agent_eval` | EXPERIMENTAL | AI eval harness, Wave 3. Used для CI nightly gate (TODO). |
| 2 | `core.agent_governance` | EXPERIMENTAL | Agent policy. No runtime callers, deferred до AI prod load. |
| 3 | `core.ai_sandbox` | EXPERIMENTAL | AI execution sandbox. Security feature, deferred. |
| 4 | `core.api_graph` | EXPERIMENTAL | API dependency graph. Useful для impact analysis, но не critical path. |
| 5 | `core.api_importer` | PENDING | API spec importer. Unknown if needed. |
| 6 | `core.batch_ops` | WIRE | EIP-style batch ops. Worth wiring into action dispatcher. |
| 7 | `core.canary_deploy` | WIRE | Canary deployment logic. Worth wiring. |
| 8 | `core.canonical_map` | EXPERIMENTAL | Code-to-doc canonical mapping. Documentation tool. |
| 9 | `core.data_quality` | PENDING | DQ checks. Need to assess usage. |
| 10 | `core.dlq_replay` | PENDING | Dead Letter Queue replay utility. |
| 11 | `core.docs_generator` | EXPERIMENTAL | Auto docs. Deferred до manual doc consolidation. |
| 12 | `core.dsl_browser` | EXPERIMENTAL | Typed Playwright DSL. P4.18. |
| 13 | `core.dsl_lint` | WIRE | DSL lint rules. Could be wired в pipeline. |
| 14 | `core.error_explainer` | EXPERIMENTAL | AI-friendly error explanations. |
| 15 | `core.file_safety` | WIRE | File path safety checks. Could be wired. |
| 16 | `core.idempotency` | **DECISION-PENDING** (см. `core/idempotency/DECISION_NOTE.md`) | Parallel to existing middleware. |
| 17 | `core.inbox` | PENDING | Notification inbox. Unknown usage. |
| 18 | `core.incident_analyst` | EXPERIMENTAL | AI incident analysis. Deferred. |
| 19 | `core.integration_template` | EXPERIMENTAL | Integration template helpers. |
| 20 | `core.io` | PENDING | I/O abstractions. Could be foundational. |
| 21 | `core.lineage_graph` | EXPERIMENTAL | Data lineage tracking. |
| 22 | `core.middleware` | PENDING | Middleware utilities. Check if used elsewhere. |
| 23 | `core.migration_preview` | WIRE | Migration preview. Could be wired в release flow. |
| 24 | `core.migration_safety` | WIRE | Migration safety checks. |
| 25 | `core.observability_v2` | WIRE | New observability API. |
| 26 | `core.outbox_verify` | PENDING | Outbox transaction verification. |
| 27 | `core.rate_limiter` | **DELETE** (см. `core/rate_limiter/DEPRECATED.md`) | Duplicate of `core/resilience/rate_limiter.py`. |
| 28 | `core.retention_policy` | PENDING | Data retention policies. |
| 29 | `core.rls_verifier` | WIRE | RLS policy verifier. |
| 30 | `core.route_contract` | EXPERIMENTAL | Route contract testing. |
| 31 | `core.route_simulation` | EXPERIMENTAL | Route simulation. |
| 32 | `core.route_test_dsl` | WIRE | Route test DSL. |
| 33 | `core.rpa_recorder` | PENDING | RPA session recorder. |
| 34 | `core.rpa_workflow` | PENDING | RPA workflow automation. |
| 35 | `core.scaling` | EXPERIMENTAL | Auto-scaling logic. |
| 36 | `core.shadow_route` | EXPERIMENTAL | Traffic shadowing. |
| 37 | `core.streaming_parser` | DELETE | No near-term caller. |
| 38 | `core.tenant_memory` | PENDING | Tenant memory store. |
| 39 | `core.tool_sandbox` | EXPERIMENTAL | Tool sandboxing. |

## Summary

| Decision | Count | % |
|---|---|---|
| DELETE | 2 | 5% |
| WIRE | 9 | 23% |
| EXPERIMENTAL | 14 | 36% |
| PENDING (требует owner review) | 14 | 36% |
| **Total isolated** | **39** | **100%** |

## Sprint 37 action items

1. **Owner review**: 14 PENDING модулей — каждый требует ручной проверки
   "используется ли это в production через не-imported путь" (dynamic imports,
   plugin manifests, feature flags).
2. **WIRE candidates** (9): приоритизировать по business value:
   - HIGH: `batch_ops`, `dsl_lint`, `migration_preview`, `route_test_dsl`
   - MEDIUM: `canary_deploy`, `file_safety`, `observability_v2`, `rls_verifier`
   - LOW: `migration_safety`
3. **DELETE** (2): `core/rate_limiter`, `core/streaming_parser`
   - `core/rate_limiter` — DEPRECATED.md готов, git rm pending approval
   - `core/streaming_parser` — needs new DEPRECATED.md
4. **EXPERIMENTAL** (14): перенести в `extensions/experimental/` если возможно,
   или закрыть за feature flag.

## Tracking

| Sprint | Target | Status |
|---|---|---|
| 36 | Этот документ + 2 DEPRECATED notes | ✅ DONE |
| 37 | Owner review для 14 PENDING | TBD |
| 37 | 2 DELETE approvals | TBD |
| 37 | WIRE 4 HIGH-value модулей | TBD |
| 38 | Move 14 EXPERIMENTAL → extensions/ | TBD |

## Verification

```bash
# Re-scan isolated modules count:
python tools/checks/scan_isolated_modules.py --strict
# Exit 1 если изолированные модули ещё существуют.
```
