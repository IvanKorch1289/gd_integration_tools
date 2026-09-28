# Release evidence — cee4c33e5d3c1e033b2b2b5f4fe54c12ddee4fb6

Generated 2026-09-28. Every status below comes from a command actually run against
this SHA in this environment. Statuses use
`PASS | FAIL | ENV_FAILURE | TOOL_FAILURE | NOT_VERIFIED`.

**Verdict: NOT production-ready.** Blocking: coverage is 17.75 points below the
project's own bar, ~27 unit tests fail for real reasons, the test suite is not
isolation-safe, and 12–14 pre-existing frontend layer violations keep the
architecture gates red. Nothing here is inferred from an earlier SHA.

## Environment

- Python 3.14, `uv run`, virtualenv at `.venv`
- No Vault, no PostgreSQL, no Redis, no OTEL collector, no ZAP container, no
  network access to the vulnerability DB. Checks needing any of these are
  `ENV_FAILURE` or `NOT_VERIFIED`, never `PASS`.

## Claim ledger

| # | Check | Command | Exit | Status |
|---|---|---|---:|---|
| 1 | Byte-compile | `python -m compileall -q src/backend` | 0 | PASS |
| 2 | Architecture layers | `tools/check_layers.py` | 0 | PASS (0 new; 22 legacy) |
| 3 | Docstrings | `tools/checks/check_docstrings.py` | 0 | PASS |
| 4 | Privacy lifecycle | `tools/checks/check_privacy_lifecycle.py --strict` | 0 | PASS |
| 5 | Optional-tenant gate | `tools/checks/check_no_new_optional_tenant.py --strict` | 0 | PASS (123 = 123) |
| 6 | Tenant isolation | `tools/checks/check_tenant_isolation.py --strict` | 0 | PASS (static) |
| 7 | Migration chain | `uv run alembic heads` | 0 | PASS (single head `f1a2b3c4d5e6`) |
| 8 | Migration history | `uv run alembic history` | 0 | PASS (25 revisions, linear) |
| 9 | Migration apply | `uv run alembic upgrade head` | 1 | ENV_FAILURE |
| 10 | CI composite | `make ci` | 0 | PASS |
| 11 | Readiness | `make readiness-check` | 0 | PASS |
| 12 | Pre-production | `make pre-prod-check` | 2 | **FAIL** (1 of 37) |
| 13 | Coverage gate | `make coverage-gate-fast` | 2 | **FAIL** (52.25% < 70%) |
| 14 | Unit test suite | `pytest tests/unit` | 1 | **FAIL** (206 failed, 7 errors) |
| 15 | Privacy contract suite | `pytest tests/unit/core/privacy …` | 0 | PASS (81 passed) |
| 16 | Tooling test suite | `pytest tests/unit/tools/` | 1 | **FAIL** (10 failed / 931 passed) |
| 17 | HTTP cURL matrix | — | — | NOT_VERIFIED |
| 18 | Playwright browser E2E | — | — | NOT_VERIFIED |
| 19 | Container image / SBOM for this SHA | — | — | NOT_VERIFIED |
| 20 | cURL `/health`, `/docs`, `/redoc`, GraphQL | — | — | NOT_VERIFIED |

## Blocking failures

### 1. Coverage 52.25% against a 70% bar (check 13)

Measured, not estimated: `pytest tests/unit --cov=src/backend` gave
`62374/119376` lines = **52.25%**. `tests/unit` is 20162 of the 20711 collected
tests.

The gate did not previously know this. `.github/workflows/test.yml` invoked
`check_coverage_gate.py` with a flat argument list, but the tool had been
migrated to a Typer subcommand CLI (`main`, `per-layer`); Typer rejects unknown
top-level options with exit 2, so the CI step exited on a usage error without
measuring anything. Separately, `.baselines/coverage.json` held
`coverage_percent: 0`, which disables drop-detection entirely (`baseline - current`
is always negative when baseline is 0). Fixed in `4baf3a345` and `cee4c33e5`.

Note `make pre-prod-check` labels this check "01 coverage ≥50%" while the target
enforces 70. The enforcement is stricter than the label, which fails safe, but
the label is wrong.

The measured run had 206 failing tests, so 52.25% is a lower bound.

### 2. Failing unit tests (check 14) — corrected accounting

`pytest tests/unit`: 19683 passed, 206 failed, 7 errors.

The 206 is **not** 206 broken tests. Running each directory on its own shows
most of the failures are cross-test pollution: the suite is not
isolation-safe, and tests that pass alone fail when neighbours run first.

| Directory | Combined run | Isolated | Verdict |
|---|---:|---:|---|
| `frontend/api_clients` | 36 | 36 | real — **fixed in 22be1cb13** |
| `infrastructure/repositories` | 24 | **0** | pollution |
| `frontend/streamlit_app` | 19 | 3 | 16 pollution, 3 real |
| `dsl/engine` | 19 | **0** (2423 passed) | pollution |
| `dsl/blueprints` | 17 | **0** (72 passed) | pollution |
| `infrastructure/clients` | 8 | 2 | 6 pollution, 2 real |
| `entrypoints/mcp` | 8 | did not finish in 20 min | pathological |
| `services/ai` | 5 | 5 | real |
| `core/config` | 4 | **0** (563 passed) | pollution |
| `services/execution` | 3 | 3 | real |
| `infrastructure/database` | 3 | 3 | real |
| `entrypoints/grpc` | 3 | 3 | real |
| `infrastructure/security` | 2 | **0** (121 passed) | pollution |
| `dsl/agents` | 2 | **0** (3 passed) | pollution |
| `core/interfaces` | 2 | **0** (200 passed) | pollution |

So after `22be1cb13` roughly **27 genuinely failing tests remain** (plus 8 in
`entrypoints/mcp`, which could not be measured in isolation), and roughly 60
of the original 206 are pollution artefacts. The tail (~51) has not been
broken down per directory.

Two separate problems, not one:

- **Real failures** — still open, listed above.
- **Test isolation** — the suite passes largely because it is usually run
  per-directory, not as a whole. `frontend/streamlit_app` alone is 3 failed;
  inside `tests/unit/frontend` it is 26. A full-suite run therefore reports
  failures that do not exist in isolation, which undermines any "suite is
  green" claim. The root cause has not been identified.
- **`entrypoints/mcp`** did not complete a single-directory run in 20 minutes
  and had to be killed. A test directory that cannot finish in isolation is
  itself a defect.

### 3. Tooling test suite: 10 failures (check 16)

`pytest tests/unit/tools/`: 931 passed, 10 failed. This was 18 before this
release; the 8 coverage-gate failures are fixed.

The remaining 10 all reproduce on a clean `HEAD` worktree and are unrelated to
this release's changes:

- `test_check_audit_deprecation.py::test_real_codebase_finds_legacy_callsites`
- `test_check_audit_deprecation_allowlist.py` (3: strict exit zero, JSON
  allowlist count, scan returns zero results)
- `test_check_routebuilder_mro.py::TestCLIMain::test_cli_default_fails`
- `test_fix_except_bug_no_remaining.py::test_codemod_idempotent`
- `test_plugin_and_route_scaffolds.py::test_test_plug_plugin_module_resolves_base_plugin_via_core_interfaces`
- `test_sbom_canonical_path.py` (2: legacy SBOM absent, canonical SBOM crypto currency)
- `test_scaffold.py::TestScaffoldPaths::test_processor_path_includes_backend`

### 4. Pre-existing frontend layer violations

`tests/unit/frontend/test_layer_boundary.py`, `test_arch_ratchet.py` and
`test_plugin_marketplace_helpers.py` fail **identically** (7 failed /
14 passed) on a clean `HEAD` worktree and on the current tree — confirmed by
running both. They assert zero frontend→upper-layer imports, but 12–14
Streamlit pages import `src.backend.services` directly
(`33_DSL_Шаблоны`, `23_AI_Учёт_затрат`, `19_Saga_Компенсации`, `63_Вики`,
`96_Монитор_зависших_сообщений`, …), which `ARCHITECTURE.md` forbids
("Frontend imports only the public API + REST via api_client.py").

This is pre-existing debt, not a regression, and it is not counted among the
`tools/` failures above. Note that `make check_layers` reports "0 new"
violations, so the backend-side layer gate does not cover the frontend.

## Environment failures (not code defects)

- **Check 9** — `alembic upgrade head` aborts in config loading with
  `redis.exceptions.AuthenticationError: AUTH <password> called without any
  password configured`. The chain itself is verified valid (checks 7–8); actually
  applying it needs a reachable Redis/Vault. The `downgrade -1` / `upgrade head`
  round-trip is therefore **NOT_VERIFIED**.
- **Pre-prod skips** — `pip-audit` (no network), `OWASP ZAP` (no container),
  `perf-gate` (no app listening on :8000). `perf-gate` covers the startup and
  performance budgets, which is why W9-style performance claims remain
  unverified.

## Not verified

No live application was started, so there is **no** HTTP-level evidence for this
SHA: no cURL matrix, no `/health`, `/docs`, `/redoc`, no GraphQL introspection,
no Playwright run, no screenshots or traces. Endpoints were not even enumerated
from `openapi.json`, so no contract claim is made.

No container image was built and no SBOM was generated for this SHA, so
check 19 is unverified even though the repository contains SBOMs from earlier
SHAs.

Privacy integration tests requiring real PostgreSQL, Redis, S3/MinIO, Qdrant and
LangMem were not run. The privacy lifecycle gate (check 4) verifies that
executable contract tests exist and pass; it does not verify the backends
themselves.

## Changes in this release

- `f9307dabd` — PostgreSQL erasure actually executes; cross-tenant leak fixed
- `4baf3a345` — coverage gate restored in CI; orphan `coverage_budget.py` removed
- `993dfefcd` — optional-tenant gate identity no longer uses line numbers
- `9be6d62f9` — duplicate `per-layer` command, backtick escapes, duplicate make target
- `cee4c33e5` — measured coverage baseline 52.25%
- `22be1cb13` — frontend clients: safe-default contract restored for httpx
  errors (backend unreachable / 5xx), missing `list_workflow_templates` added;
  `tests/unit/frontend/api_clients` 36 failed → 0

## What would make this production-ready

1. Fix the ~27 real unit-test failures (`services/ai` 5, `streamlit_app` 3,
   `services/execution` 3, `infrastructure/database` 3, `entrypoints/grpc` 3,
   `infrastructure/clients` 2, `entrypoints/mcp` 8).
2. Make the suite isolation-safe, or run per-directory by default. A full-suite
   run currently reports failures that do not reproduce in isolation, so no
   "suite is green" claim is possible.
3. Investigate `tests/unit/entrypoints/mcp`, which cannot complete a
   single-directory run.
4. Remove the 12–14 frontend→`src.backend.services` imports so the frontend
   architecture gates go green.
5. Either raise real coverage to 70% or formally lower the declared threshold —
   the gap is 17.75 points and cannot be closed by tooling.
6. Run the full gate battery with infrastructure up (PostgreSQL, Redis, MinIO,
   Qdrant, Vault) to clear check 9 and the privacy integrations.
7. Start the app and produce cURL + Playwright evidence, including
   `artifacts/e2e/<sha>/`.
8. Build the image, generate SBOM, sign, and re-run pre-prod-check to exit 0.
