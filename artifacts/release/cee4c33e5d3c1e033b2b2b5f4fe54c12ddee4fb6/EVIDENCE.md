# Release evidence — cee4c33e5d3c1e033b2b2b5f4fe54c12ddee4fb6

Generated 2026-09-28. Every status below comes from a command actually run against
this SHA in this environment. Statuses use
`PASS | FAIL | ENV_FAILURE | TOOL_FAILURE | NOT_VERIFIED`.

**Verdict: NOT production-ready.** One blocking FAIL (coverage far below the
project's own bar) and one large unaddressed FAIL (206 failing unit tests).
Nothing here is inferred from an earlier SHA.

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

### 2. 206 failing unit tests (check 14)

`pytest tests/unit`: 19683 passed, 206 failed, 7 errors, 184 skipped.

By directory:

| Count | Area |
|---:|---|
| 36 | `tests/unit/frontend/api_clients` |
| 24 | `tests/unit/infrastructure/repositories` |
| 19 | `tests/unit/frontend/streamlit_app` |
| 19 | `tests/unit/dsl/engine` |
| 17 | `tests/unit/dsl/blueprints` |
| 8 | `tests/unit/infrastructure/clients` |
| 8 | `tests/unit/entrypoints/mcp` |
| 5 | `tests/unit/services/ai` |
| 4 | `tests/unit/core/config` |
| 3 | `tests/unit/services/execution` |
| 3 | `tests/unit/infrastructure/database` |
| 3 | `tests/unit/entrypoints/grpc` |
| 2 | `tests/unit/infrastructure/security` |
| 2 | `tests/unit/dsl/agents` |
| 2 | `tests/unit/core/interfaces` |
| rest | scattered |

These reproduce outside the full-suite run, so they are not artefacts of
parallel scheduling or cross-test pollution. Not yet triaged individually.

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

## What would make this production-ready

1. Triage and fix the 206 failing unit tests.
2. Either raise real coverage to 70% or formally lower the declared threshold —
   the gap is currently ~18 points and cannot be closed by tooling.
3. Run the full gate battery with infrastructure up (PostgreSQL, Redis, MinIO,
   Qdrant, Vault) to clear checks 9 and the privacy integrations.
4. Start the app and produce cURL + Playwright evidence, including
   `artifacts/e2e/<sha>/`.
5. Build the image, generate SBOM, sign, and re-run pre-prod-check to exit 0.
