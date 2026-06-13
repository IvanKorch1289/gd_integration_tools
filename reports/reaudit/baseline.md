# Re-audit Baseline

**Date:** 2026-06-13
**Repo:** https://github.com/IvanKorch1289/gd_integration_tools.git
**HEAD commit:** `423cdadc3aaef6c2bdccb63424dfff613c01c4df`
**Branch:** `master`
**HEAD timestamp:** 2026-06-13 16:36:12 +0300

---

## Repository Identity

| Field | Value |
|-------|-------|
| Remote | https://github.com/IvanKorch1289/gd_integration_tools.git |
| Working dir | `/home/user/dev/gd_integration_tools` |
| Origin sync | 75+ commits ahead of origin/master (post-push) |
| Last push verified | `423cdadc` (W2 audit helpers) + `b1b090fe` (W1 D5 B1) + `abc14f83` (S105 closure) |

---

## File Inventory (post-S106 W2)

| Category | Count | Notes |
|----------|-------|-------|
| Python files (excl. venv/git) | 3700 | Main codebase |
| Test files | 1405 | 1281 unit + 40 integration + 84 testkit |
| ADRs (`docs/adr/0*.md`) | 140 | Sprint 67-105 closure docs |
| Cookbooks | 6 | `docs/cookbooks/01..05-*.md` |
| Tutorials | 18 | `docs/tutorials/00-08*.md` |
| How-to guides | 5 | `docs/how-to/*` |
| Frontend (Streamlit) | 119 | `src/frontend/streamlit_app/*.py` |
| Extensions | 74 | `extensions/<plugin>/*.py` |
| Routes | 0 (no .py) | Declarative YAML only |
| Tools (CI/dev) | 134 | `tools/*.py` |
| Migrations | 23 | Alembic versions |
| **Total tracked files** | **49 191** | Excl. .venv, .git, .run, logs, profiles |

---

## Top-Level Tree

```
gd_integration_tools/
├── AGENTS.md           # Kimi entry point
├── ARCHITECTURE.md     # Architecture doc
├── CHANGELOG.md        # 16 sprints (S93-S105) recorded
├── CLAUDE.md           # Full context для Claude Code
├── PLAN.md             # V22 roadmap
├── README.md
├── ai_policies/        # AI policy specs
├── analysis/           # V2 gap analyses
├── artifacts/          # RAG, SBOM, etc.
├── config/             # Vocabularies
├── config_profiles/    # dev/prod profiles
├── coverage*.xml/json  # Coverage reports
├── dashboards/         # Grafana
├── deploy/             # helm/k8s/windows-worker
├── dev/                # cocoindex dev data
├── docs/               # adr, analysis, api, architecture, bpmn, cookbooks, dsl, explanation, how-to, tutorials
├── extensions/         # core_entities, credit_pipeline, example_plugin, test_plug
├── frontend/           # public/ (HTML, CSS, JS)
├── gap-analysis/       # DEEP-RESEARCH report 2026-06-12
├── graphify-out/       # Code graph
├── logs/
├── make/               # 16 .mk files (split per section)
├── ops/                # Operational scripts
├── plugins/            # Builtin plugins
├── profiles/           # Profiling outputs
├── routes/             # Declarative YAML routes
├── scripts/            # Verification scripts (incl. verify_d5_migration_readiness.sh)
├── src/                # Main code
├── testkit/            # Test utilities
├── tests/              # 1405 tests
├── tools/              # 134 CI/dev tools
└── var/, vault/        # Runtime data
```

---

## Source Layer Layout (`src/backend/`)

```
src/backend/
├── ai/                 # AI Safety stack (4 mixins)
├── core/               # 40+ sub-packages (audit, auth, cdc, di, ...)
├── dsl/                # 26 sub-packages (builders, processors, workflow, ...)
├── entrypoints/        # REST/SOAP/WS/SSE/MCP entrypoints
├── infrastructure/     # 30+ sub-packages (db, cache, scheduler, security, ...)
├── ops/                # Health checks, observability
├── plugins/            # Builtin plugin system
├── schemas/            # Pydantic schemas
├── services/           # Application services
├── utilities/          # Admin panel, codecs
└── workflows/          # Temporal worker
```

---

## Linter / Audit State (post-S106 W2)

| Tool | State | Note |
|------|-------|------|
| `check_layers.py` (core) | **9 NEW violations** | New architectural violations (audit facade, cdc registry) |
| `check_layers.py` (extensions) | **39 NEW violations** | D5 B2/B3 backlog (orderkinds/orders/files) + general ext→svc imports |
| `check_docstrings.py` | allowlist 1636 | 0 NEW regressions, 0 stale |
| `audit_stdlib_logging.py` | 8 legit, 0 violations | Migration COMPLETE (S93-S98) |
| `check_audit_deprecation.py` | 22 files, 77 callsites | Soft-deprecation gate active (S105 W2 Path B) |
| `check_protocol_coverage.py` | **FAIL** | 5+ missing entrypoint bridges (ws/webhook/express/sse/_action_bridge) |

---

## Sprint Cadence

| S | Closed | Score | Notes |
|---|--------|-------|-------|
| S93 | ✅ | 8.6 | Critical fixes, auth/CDC/logging/DSL |
| S94 | ✅ | 8.7 | Logging codemod, ratchet, SSE |
| S95 | ✅ | 8.8 | DSL db_crud, AuthGateway, stdlib logging audit |
| S96 | ✅ | 8.9 | Auth relocation, SSE multi-stream, **RouteBuilder fix** |
| S97 | ✅ | 9.0 | RouteBuilder CRITICAL FIX, Telegram DSL |
| S98 | ✅ | 9.0 | Middleware closure, ratchet, stdlib cleanup |
| S99 | ✅ | 9.0 | DSL codegen/express/LangGraph TODOs closed, **9.0/10 TARGET** |
| S100 | ✅ | 9.1 | LangGraph Checkpointer, Py2 codemod (31 files), ratchet -10, stdlib audit |
| S101 | ✅ | 9.2 | CDC registry, docstring gate 3→8 dirs, TenantMixin 5/7 |
| S102 | ✅ | 9.3 | CDCClient bug, lint --strict, V2 P0 #6 7/7 verified |
| S103 | ✅ | 9.4 | D5 linter, D9 cron DSL, audit facade, V2 P0 #10 |
| S104 | ✅ | 9.4 | D21 RPA DSL, rate limit facade, DSN MSSQL/MySQL/DB2 |
| S105 | ✅ | 9.5 | D5 plan, D9 Temporal real, audit soft-deprecate |
| S106 W1 | ✅ | 9.5 | D5 B1 (6 Risk A models move) |
| S106 W2 | ✅ | 9.5 | Audit Path A (7 facade helpers) |
| S106 W3+ | 🔄 in-flight | — | Pre-commit hook + D5 B2 (orderkinds) |

**Cumulative:** 15 sprints closed, 16 commits ahead of origin/master (post-push), 322+ NEW tests, 12 ADRs (0175-0190), 295→1658→1636 docstring baseline reduction.

---

## Source of Truth for Project State

- `PLAN.md` (V22) — roadmap
- `CLAUDE.md` (V22) — agent rules
- `gap-analysis/DEEP-RESEARCH-gd_integration_tools-2026-06-12.md` — 22-domain audit (40 KB, 22 sub-claims, partially outdated)
- `docs/adr/INDEX.md` — ADR index
- `CHANGELOG.md` — sprint-by-sprint changes
