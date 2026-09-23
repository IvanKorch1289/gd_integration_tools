# FEATURE_INVENTORY — Core module reachability registry

> **Generated**: 2026-09-23T08:05:07Z
> **Source**: `tools/checks/scan_isolated_modules.py --json`
> **DO NOT EDIT MANUALLY** — auto-generated from real scan.

---

## Summary

- **Total core/ modules**: 91
- **🟢 WIRED** (≥1 production caller): 51
- **🔴 ISOLATED** (zero production callers): 40
- **Total src caller references**: 2513
- **Total test caller references**: 1281

---

## Methodology

Caller criterion: any non-empty match of `core.<module_name>` (full dotted path) в .py file вне самого пакета модуля.
Tests included for visibility but do **not** count as production usage.

Решение per isolated module:
- **WIRE**: подключить через composition root / DI, добавить end-to-end test.
- **EXPERIMENTAL**: перенести в extensions/experimental или закрыть feature flag.
- **DELETE**: удалить duplicate или незадействованный код.

---

## All modules (sorted by isolation)

| Module | src callers | tests | Status | Recommendation |
|---|---:|---:|---|---|
| `core.actions` | 2 | 6 | 🟢 WIRED | low usage — consider consolidating |
| `core.ai` | 38 | 85 | 🟢 WIRED | production module |
| `core.api` | 78 | 36 | 🟢 WIRED | production module |
| `core.async_utils` | 26 | 19 | 🟢 WIRED | production module |
| `core.auth` | 69 | 85 | 🟢 WIRED | production module |
| `core.cache` | 3 | 2 | 🟢 WIRED | production module |
| `core.cdc` | 7 | 10 | 🟢 WIRED | production module |
| `core.cdc_control_plane` | 1 | 1 | 🟢 WIRED | low usage — consider consolidating |
| `core.clients` | 3 | 0 | 🟢 WIRED | production module |
| `core.clock` | 3 | 3 | 🟢 WIRED | production module |
| `core.config` | 317 | 273 | 🟢 WIRED | production module |
| `core.connectors` | 1 | 3 | 🟢 WIRED | low usage — consider consolidating |
| `core.contract_testing` | 2 | 1 | 🟢 WIRED | low usage — consider consolidating |
| `core.cost_attribution` | 1 | 4 | 🟢 WIRED | low usage — consider consolidating |
| `core.decorators` | 4 | 1 | 🟢 WIRED | production module |
| `core.di` | 248 | 103 | 🟢 WIRED | production module |
| `core.domain` | 30 | 30 | 🟢 WIRED | production module |
| `core.enums` | 19 | 7 | 🟢 WIRED | production module |
| `core.errors` | 32 | 18 | 🟢 WIRED | production module |
| `core.facades` | 1 | 1 | 🟢 WIRED | low usage — consider consolidating |
| `core.feature_flags` | 9 | 12 | 🟢 WIRED | production module |
| `core.frontend_facade` | 9 | 4 | 🟢 WIRED | production module |
| `core.integrations` | 2 | 1 | 🟢 WIRED | low usage — consider consolidating |
| `core.interfaces` | 182 | 112 | 🟢 WIRED | production module |
| `core.logging` | 807 | 7 | 🟢 WIRED | production module |
| `core.messaging` | 21 | 20 | 🟢 WIRED | production module |
| `core.models` | 18 | 4 | 🟢 WIRED | production module |
| `core.net` | 43 | 28 | 🟢 WIRED | production module |
| `core.observability` | 23 | 17 | 🟢 WIRED | production module |
| `core.orchestration` | 3 | 3 | 🟢 WIRED | production module |
| `core.plugin_runtime` | 15 | 20 | 🟢 WIRED | production module |
| `core.policy` | 3 | 4 | 🟢 WIRED | production module |
| `core.protocols` | 2 | 1 | 🟢 WIRED | low usage — consider consolidating |
| `core.providers_registry` | 7 | 2 | 🟢 WIRED | production module |
| `core.registry_explorer` | 3 | 4 | 🟢 WIRED | production module |
| `core.repositories` | 1 | 4 | 🟢 WIRED | low usage — consider consolidating |
| `core.request_context` | 26 | 19 | 🟢 WIRED | production module |
| `core.resilience` | 78 | 53 | 🟢 WIRED | production module |
| `core.scheduler` | 3 | 4 | 🟢 WIRED | production module |
| `core.secrets_sources` | 1 | 1 | 🟢 WIRED | low usage — consider consolidating |
| `core.security` | 75 | 84 | 🟢 WIRED | production module |
| `core.serialization` | 14 | 2 | 🟢 WIRED | production module |
| `core.sla_cockpit` | 1 | 2 | 🟢 WIRED | low usage — consider consolidating |
| `core.state` | 5 | 3 | 🟢 WIRED | production module |
| `core.storage` | 4 | 6 | 🟢 WIRED | production module |
| `core.svcs_registry` | 17 | 14 | 🟢 WIRED | production module |
| `core.tenancy` | 35 | 32 | 🟢 WIRED | production module |
| `core.types` | 84 | 21 | 🟢 WIRED | production module |
| `core.utils` | 119 | 39 | 🟢 WIRED | production module |
| `core.workflow` | 15 | 21 | 🟢 WIRED | production module |
| `core.workflow_registry` | 3 | 5 | 🟢 WIRED | production module |
| `core.agent_eval` | 0 | 1 | 🔴 ISOLATED — needs decision | decision needed: wire / experimental / delete |
| `core.agent_governance` | 0 | 1 | 🔴 ISOLATED — needs decision | decision needed: wire / experimental / delete |
| `core.ai_sandbox` | 0 | 1 | 🔴 ISOLATED — needs decision | decision needed: wire / experimental / delete |
| `core.api_graph` | 0 | 1 | 🔴 ISOLATED — needs decision | decision needed: wire / experimental / delete |
| `core.api_importer` | 0 | 1 | 🔴 ISOLATED — needs decision | decision needed: wire / experimental / delete |
| `core.batch_ops` | 0 | 1 | 🔴 ISOLATED — needs decision | decision needed: wire / experimental / delete |
| `core.canary_deploy` | 0 | 1 | 🔴 ISOLATED — needs decision | decision needed: wire / experimental / delete |
| `core.canonical_map` | 0 | 1 | 🔴 ISOLATED — needs decision | decision needed: wire / experimental / delete |
| `core.data_quality` | 0 | 1 | 🔴 ISOLATED — needs decision | decision needed: wire / experimental / delete |
| `core.dlq_replay` | 0 | 1 | 🔴 ISOLATED — needs decision | decision needed: wire / experimental / delete |
| `core.docs_generator` | 0 | 2 | 🔴 ISOLATED — needs decision | decision needed: wire / experimental / delete |
| `core.dsl_browser` | 0 | 1 | 🔴 ISOLATED — needs decision | decision needed: wire / experimental / delete |
| `core.dsl_lint` | 0 | 1 | 🔴 ISOLATED — needs decision | decision needed: wire / experimental / delete |
| `core.error_explainer` | 0 | 1 | 🔴 ISOLATED — needs decision | decision needed: wire / experimental / delete |
| `core.file_safety` | 0 | 1 | 🔴 ISOLATED — needs decision | decision needed: wire / experimental / delete |
| `core.idempotency` | 0 | 1 | 🔴 ISOLATED — needs decision | decision needed: wire / experimental / delete |
| `core.inbox` | 0 | 1 | 🔴 ISOLATED — needs decision | decision needed: wire / experimental / delete |
| `core.incident_analyst` | 0 | 1 | 🔴 ISOLATED — needs decision | decision needed: wire / experimental / delete |
| `core.integration_template` | 0 | 1 | 🔴 ISOLATED — needs decision | decision needed: wire / experimental / delete |
| `core.io` | 0 | 1 | 🔴 ISOLATED — needs decision | decision needed: wire / experimental / delete |
| `core.lineage_graph` | 0 | 1 | 🔴 ISOLATED — needs decision | decision needed: wire / experimental / delete |
| `core.middleware` | 0 | 0 | 🔴 ISOLATED — needs decision | decision needed: wire / experimental / delete |
| `core.migration_preview` | 0 | 1 | 🔴 ISOLATED — needs decision | decision needed: wire / experimental / delete |
| `core.migration_safety` | 0 | 1 | 🔴 ISOLATED — needs decision | decision needed: wire / experimental / delete |
| `core.observability_v2` | 0 | 1 | 🔴 ISOLATED — needs decision | decision needed: wire / experimental / delete |
| `core.outbox_verify` | 0 | 1 | 🔴 ISOLATED — needs decision | decision needed: wire / experimental / delete |
| `core.privacy` | 0 | 0 | 🔴 ISOLATED — needs decision | decision needed: wire / experimental / delete |
| `core.rate_limiter` | 0 | 1 | 🔴 ISOLATED — needs decision | decision needed: wire / experimental / delete |
| `core.retention_policy` | 0 | 1 | 🔴 ISOLATED — needs decision | decision needed: wire / experimental / delete |
| `core.rls_verifier` | 0 | 1 | 🔴 ISOLATED — needs decision | decision needed: wire / experimental / delete |
| `core.route_contract` | 0 | 1 | 🔴 ISOLATED — needs decision | decision needed: wire / experimental / delete |
| `core.route_simulation` | 0 | 1 | 🔴 ISOLATED — needs decision | decision needed: wire / experimental / delete |
| `core.route_test_dsl` | 0 | 1 | 🔴 ISOLATED — needs decision | decision needed: wire / experimental / delete |
| `core.rpa_recorder` | 0 | 1 | 🔴 ISOLATED — needs decision | decision needed: wire / experimental / delete |
| `core.rpa_workflow` | 0 | 1 | 🔴 ISOLATED — needs decision | decision needed: wire / experimental / delete |
| `core.scaling` | 0 | 6 | 🔴 ISOLATED — needs decision | decision needed: wire / experimental / delete |
| `core.shadow_route` | 0 | 1 | 🔴 ISOLATED — needs decision | decision needed: wire / experimental / delete |
| `core.streaming_parser` | 0 | 1 | 🔴 ISOLATED — needs decision | decision needed: wire / experimental / delete |
| `core.tenant_memory` | 0 | 1 | 🔴 ISOLATED — needs decision | decision needed: wire / experimental / delete |
| `core.tool_sandbox` | 0 | 1 | 🔴 ISOLATED — needs decision | decision needed: wire / experimental / delete |

---

## Regeneration

```bash
# Local:
python tools/checks/generate_feature_inventory.py

# Direct scan:
python tools/checks/scan_isolated_modules.py
python tools/checks/scan_isolated_modules.py --strict  # exit 1 if isolated
```
