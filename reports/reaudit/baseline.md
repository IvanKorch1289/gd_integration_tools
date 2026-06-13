# Baseline — re-audit `gd_integration_tools` (post-S109)

**Date:** 2026-06-13
**Repository:** https://github.com/IvanKorch1289/gd_integration_tools.git
**Commit:** `4dc2a7ac` (S109 closure)
**Branch:** `master`
**Working tree:** clean (no uncommitted changes)

## Quantitative baseline

| Metric | Count |
|--------|-------|
| Total Python files | **3 713** |
| Python LOC (src + tests + tools + extensions) | **161 849** |
| Test files (`tests/test_*.py`) | **1 214** |
| Documentation files (`.md`/`.rst`) | **1 648** |
| ADRs (`docs/adr/`) | **147** |
| Extension files (`extensions/**/*.py`) | **74** |
| Frontend files (TS/TSX/Python) | **813** |
| Tools (`tools/*.py`) | **136** |
| Git commits (all branches) | **2 209** |
| Git commits (master, 2209 history) | HEAD = `4dc2a7ac` |

## Top-level tree (depth 1)

```
ai_policies/      analysis/        artifacts/        config/
config_profiles/  dashboards/      deploy/           dev/
dev_storage/      dist/            docs/             extensions/
frontend/         reports/         src/              tests/
tools/            CHANGELOG.md     CLAUDE.md         PLAN.md
README.md         AGENTS.md        pyproject.toml    uv.lock
```

## src/backend tree (key domains, depth 2)

| Domain | Sub-domains | Notes |
|--------|-------------|-------|
| `core/ai/` | `gateway_pipeline_mixin/`, `guardrails/`, `policy/`, `ai.py`, `pydantic_ai_client.py` | AI gateway + policy enforcer |
| `core/audit/` | `facade/`, `schema/`, `sinks/`, `audit.py` | TD-004 fully migrated (S109 closure) |
| `core/auth/` | `saml/`, `ldap_client_factory.py` | Multi-method auth |
| `core/cdc/` | `registry.py`, `source.py` | CDC abstraction layer |
| `core/config/` | `base/`, `external_apis/`, `external_databases/`, `features/`, `services/`, `validator/` | Stage-based config |
| `core/database/` | session manager + repositories | SQLAlchemy + asyncpg |
| `core/di/` | `providers/`, `container.py` | DI DSL (Sprint 40) |
| `core/middleware/` | global middleware | rate-limit, correlation, audit |
| `core/plugin_runtime/` | `BasePlugin`, `PluginLoader` | Plugin lifecycle |
| `core/resilience/` | `BreakerPolicy`, `ResilienceCoordinator`, `backpressure/` | R6 hardening |
| `core/security/` | `authorization_gateway/`, `capabilities/`, `pii_*`, `secret_rotation.py` | K1 domain |
| `dsl/builders/` | 12K LOC, 25+ builder modules | RouteBuilder + 80/20 chainable |
| `dsl/engine/processors/` | **223 processors** | Largest DSL surface |
| `entrypoints/` | `api/v1/`, `graphql/`, `grpc/`, `middlewares/`, `mcp/` | 8+ protocol auto-registration |
| `infrastructure/` | `database/`, `cache/`, `storage/`, `messaging/`, `cdc/`, `sources/`, `sinks/`, `workflow/`, `clients/`, `secrets/`, `resilience/`, `observability/`, `security/`, `repositories/`, `notifications/` | All infrastructure adapters |
| `services/` | `ai/`, `audit/`, `auth/`, `core/`, `integrations/`, `io/`, `notebooks/`, `ops/`, `plugins/`, `routes/`, `workflows/`, `admin/` | Application layer |
| `services/ai/` | `multi_agent/`, `ai_agent/`, `gateway/`, `pii/`, `agents/`, `rag/` | AI/RAG runtime |
| `services/notebooks/` | JupyterHub + notebook indexer | JupyterHub integration |
| `services/workflows/` | workflow facade | DSL → Temporal bridge |

## Extensions tree

```
extensions/
├── core_entities/   (orders, orderkinds, users, files — 4 domain plugins)
├── credit_pipeline/ (agents, workflows, services, routes — 1 credit product)
├── example_plugin/  (scaffold)
└── test_plug/       (test scaffold)
```

## Linter state

| Linter | Latest | Tool path | Status |
|--------|--------|-----------|--------|
| Layer policy | S103 W1 → S106 W3 | `tools/check_layers.py` | **200 stale allowlist entries; 36 NEW violations in extensions; 15 NEW in services** |
| Docstring ratchet | S100 W3 | `tools/check_docstrings.py` | Baseline 1641 violations (allowlist) |
| Audit deprecation | S109 W4 | `tools/check_audit_deprecation.py` | 29 callsites remaining (mixin internals — S106 W5 dual-emit) |
| Stdlib logging | S100 W4 | `tools/audit_stdlib_logging.py --ci` | 8 legitimate files locked |

## Test baseline

- **1 214 test files**, 100+ test directories
- 18-entry allowlist for pre-existing failures
- 0 NEW regressions as of S109 (S107 W5 + S108 + S109 all green)

## Architecture score (per ADR-0195 closure)

**9.8/10** (incremental over S108 9.8, pure tech-debt cleanup, no new feature flags).
