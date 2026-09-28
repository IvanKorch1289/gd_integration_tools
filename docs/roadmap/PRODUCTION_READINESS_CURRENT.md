# Production Readiness — CURRENT (canonical)

> **This is the canonical current-status document for the repository.**
> Generated 2026-09-28. It supersedes every earlier readiness snapshot.
>
> - Predecessor snapshots (kept as historical records, **do not read as current**):
>   [`PRODUCTION_READINESS.md`](PRODUCTION_READINESS.md) (snapshot 2026-09-01),
>   [`PRODUCTION_READINESS_FINAL.md`](PRODUCTION_READINESS_FINAL.md) (snapshot 2026-09-02).
> - Per-SHA machine evidence lives in `artifacts/release/<sha>/EVIDENCE.md`.
> - `.audit/last_run.json` mirrors the machine-readable status of this file.
>
> **Rule:** a PASS here applies **only** to the SHA named in the table. It is
> never carried forward to another commit.

---

## Verdict: NOT production-ready

Blocking items, in priority order:

1. **Coverage is far below the project's own bar** — 52.25% measured against a
   70% threshold. The gate now reports this honestly instead of silently
   passing.
2. **The test suite is not isolation-safe** — a full-suite run reports failures
   that do not reproduce in isolation, so no "suite is green" claim is possible.
3. **No HTTP-level evidence exists for any current SHA** — no cURL matrix, no
   Playwright, no browser verification, because no application was ever started.
4. **No release artifact for this SHA** — no container image, no SBOM, no
   signature.
5. **Known observability defect** — `exc_info=True` through the project's
   `StructlogLogger` attaches **no traceback** to the emitted `LogRecord`; the
   flag only appears as a key in the rendered event dict.

---

## Status by area

Statuses: `PASS` / `FAIL` / `ENV_FAILURE` / `TOOL_FAILURE` / `NOT_VERIFIED`.
`ENV_FAILURE` means the environment prevented the check, **not** that the code is
wrong; an incomplete environment is never reported as `PASS`.

| Area | Status | Evidence |
|---|---|---|
| Byte-compile `src/backend` | PASS | `compileall` exit 0 |
| Docstrings | PASS | `check_docstrings.py` exit 0, 0 missing |
| Architecture layers (backend) | PASS with debt | `check_layers.py`: **0 new**, 22 legacy |
| Architecture layers (frontend) | **FAIL** | 12–13 Streamlit pages imported `src.backend.services`; 6 fixed in `f681c4ed7`, remainder open. `make check_layers` does **not** cover the frontend |
| Privacy lifecycle gate | PASS | `check_privacy_lifecycle.py --strict` exit 0, 5/5 backends have executing contract tests |
| Optional-tenant gate | PASS | `check_no_new_optional_tenant.py --strict` exit 0, 123 baseline = 123 current |
| Tenant isolation (static) | PASS | `check_tenant_isolation.py --strict` exit 0 |
| Tenant isolation (runtime) | **NOT VERIFIED** | static classification only; no cross-tenant runtime test against live backends |
| Object authorization | PASS | 117 callsites, 0 unknown |
| CI composite | PASS | `make ci` exit 0 at `f681c4ed7` |
| Readiness guards | PASS | `make readiness-check` exit 0 |
| Pre-production | **FAIL** | `make pre-prod-check` exit 2 — 25/37 PASS, 1 FAIL (coverage), 8 WARN, 3 SKIP |
| Coverage gate | **FAIL** | 52.25% vs 70% threshold; gate correctly reports FAIL |
| Migration chain integrity | PASS | `alembic heads` single head, `alembic history` 25 linear revisions |
| Migration apply / rollback | ENV_FAILURE | `alembic upgrade head` aborts in config load (`redis AuthenticationError`); no Redis/Vault here |
| Privacy integration (PG/Redis/MinIO/Qdrant/LangMem) | NOT VERIFIED | backends not running |
| Tooling test suite | **FAIL** | `tests/unit/tools/`: 10 failures, all reproduce on a clean `HEAD` worktree |
| Unit test suite (per-directory) | **FAIL** | all clusters green in isolation except `tests/unit/entrypoints/mcp`, which cannot finish a run |
| Unit test suite (whole-tree) | **FAIL** | reports failures that do not reproduce in isolation (test-isolation defect) |
| HTTP / cURL matrix | NOT VERIFIED | no application started |
| Browser / Playwright | NOT_VERIFIED | no application started, no `artifacts/e2e/` for this SHA |
| Container image + SBOM | NOT VERIFIED | not built for this SHA |
| Signature / cosign | NOT VERIFIED | no image to sign |

---

## What was fixed in this cycle

Commits `f9307dabd` … `f681c4ed7`, each verified with `make ci` exit 0.

- **PostgreSQL erasure actually runs.** It returned `FAILED` on every call via
  `ModuleNotFoundError` on a module that never existed. Two further defects
  surfaced once it executed: a **cross-tenant leak** (the tenant probe degraded
  to "unscoped" on any error, deleting other tenants' rows — reproduced at
  `records_affected=2`), and an `evidence=` kwarg the result dataclass does not
  accept, whose `TypeError` was reported as `FAILED`. Empty tenant is now
  `FAILED` rather than unscoped.
- **Coverage gate was never measuring coverage.** CI invoked a flat CLI that no
  longer existed after the Typer migration and exited 2 on a usage error. The
  baseline was `0`, which disables drop-detection entirely. Both fixed; the gate
  now reports the true number.
- **Optional-tenant gate was false-green by construction.** It keyed findings on
  the line number, so moving a function produced a false `NEW` + `REMOVED` pair;
  the only way to "fix" it was to rewrite the baseline. Identity is now
  module + qualified name + argument, with `moved` / `changed` / `new` / `removed`
  reported separately, and the gate is actually wired into `make ci` (it previously
  had zero callers anywhere).
- **Frontend safe-default contract was dead.** Clients caught only builtin
  exceptions while `httpx.ConnectError` / `HTTPStatusError` — the real failure
  modes for "backend down" and "5xx" — are not builtin subclasses. "Show an empty
  state instead of crashing" therefore never held.
- **`DSLBuilderService` could never be constructed** — `NameError` on `YAMLStore`,
  caused by a PEP 562 module `__getattr__` proxy that cannot serve bare global
  lookups inside function bodies.
- **6 Streamlit pages** moved to the sanctioned `core.frontend_facade`; no
  `src.backend.services` import remains in any page.
- 17 stale tests repaired, including two that had been failing forever and one
  order-dependent **security-gate** test that passed only sometimes.

---

## Known open defects

- `exc_info=True` via `StructlogLogger` produces no traceback on the `LogRecord`.
  Observed on the webhook DLQ-remove error path; likely wider.
- Test isolation: `tests/unit/entrypoints/grpc/test_file_stream.py` and
  `test_grpc_server.py` replace protobuf module attributes without isolation,
  breaking sibling tests. The frontend `shared/test_components.py` cluster fails
  only in combined runs. Needs fixtures, not test edits.
- `tests/unit/entrypoints/mcp` cannot complete a single-directory run.
- 10 tooling-test failures (audit-deprecation ×4, SBOM ×2, scaffold, routebuilder
  MRO, codemod idempotency, plugin scaffold) — all reproduce at clean `HEAD`.
- 123 optional `tenant_id` contracts remain tracked, not removed.
- 22 legacy layer exceptions in the backend allowlist.

---

## Measurement notes and staleness

- **Coverage 52.25%** was measured on `tests/unit` at commit `cee4c33e5`
  (62374 / 119376 lines). A re-measurement at a later HEAD **did not complete**:
  pytest aborted in `pytest_sessionfinish` with `OSError: cannot send (already
  closed?)` and the run was cancelled, producing no `coverage.xml`. The 52.25%
  figure is therefore a **lower bound** — many tests fixed after `cee4c33e5` now
  pass — but no newer precise measurement exists. Do not quote a coverage number
  for HEAD without re-running the measurement.
- `make pre-prod-check` figures come from `cee4c33e5`, before the frontend and
  test fixes. Its coverage check additionally now reports "coverage.xml not
  found" rather than a number, because the file is a build artifact that the
  failed re-measurement removed.
- `make readiness-check` was last run at `cee4c33e5`.

---

## How to refresh this document

1. Re-measure coverage: `uv run pytest tests/unit --cov=src/backend --cov-report=xml`.
2. `uv run python tools/check_coverage_gate.py main --coverage-xml coverage.xml --baseline .baselines/coverage.json --threshold 70 --strict`.
3. Re-run `make ci`, `make readiness-check`, `make pre-prod-check`.
4. Write per-SHA evidence to `artifacts/release/<sha>/EVIDENCE.md`.
5. Update this file and `.audit/last_run.json` **only** with results from that
   same SHA. Do not copy numbers between commits.
