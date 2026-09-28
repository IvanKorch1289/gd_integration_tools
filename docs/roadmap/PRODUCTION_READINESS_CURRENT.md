# Production Readiness — CURRENT (canonical)

> **This is the canonical current-status document for the repository.**
> Generated 2026-09-28, last updated for SHA `bbadf108a`.
> It supersedes every earlier readiness snapshot.
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

1. **Coverage is far below the project's own bar** — ~52% measured against a
   70% threshold. The gate reports this honestly instead of silently passing.
   Two independent measurements agree within 0.36 p.p.
2. **The test suite is not isolation-safe** — a full-suite run reports failures
   that do not reproduce in isolation, so no "suite is green" claim is possible.
3. **`make ci` never runs the tests.** It ends at `test-collection-check`, which
   calls `pytest --co`. Exit 0 means "tests import", not "tests pass".
4. **No release artifact for this SHA** — no container image, no SBOM, no
   signature.
5. **Tooling suite is red** — 10 failures in `tests/unit/tools/` that reproduce
   on a clean worktree.

The `exc_info` traceback loss, the corrupted `timestamp` field and the step-up
token corruption and the missing auth description in the OpenAPI spec were
all confirmed by running the application, and are **fixed** — see
"What was fixed in this cycle".
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
| Tenant isolation (runtime) | **FAIL (negative)** | live run at `f013e7317`: empty/`null` `X-Tenant-Id` → 401, no data returned |
| Object authorization | PASS | 117 callsites, 0 unknown |
| CI composite | PASS with caveat | `make ci` exit 0 at `bbadf108a` — but it does not execute tests |
| Application starts and serves | PASS | live uvicorn, `dev_light` profile, `/health` → 200 |
| Unauthenticated data access | PASS | 12 endpoints → 401/403, no payload returned |
| Login credential enforcement | PASS | 2 wrong-password probes → 401, identical message (no user enumeration) |
| OpenAPI auth declaration | PASS | 443/443 operations declare `security`, 4 schemes, 0 unresolved refs, 0 mismatches with the runtime guard (`bbadf108a`) |
| OpenAPI integrity | PASS | 0 masking artifacts in the served spec (was 16) |
| Readiness guards | PASS | `make readiness-check` exit 0 |
| Pre-production | **FAIL** | `make pre-prod-check` exit 2 — 25/37 PASS, 1 FAIL (coverage), 8 WARN, 3 SKIP |
| Coverage gate | **FAIL** | ~52% vs 70% threshold; gate correctly reports FAIL (exit 2) |
| Migration chain integrity | PASS | `alembic heads` single head, `alembic history` 25 linear revisions |
| Migration apply / rollback | ENV_FAILURE | `alembic upgrade head` aborts in config load (`redis AuthenticationError`); no Redis/Vault here |
| Privacy integration (PG/Redis/MinIO/Qdrant/LangMem) | NOT VERIFIED | backends not running |
| Tooling test suite | **FAIL** | `tests/unit/tools/`: 10 failures, all reproduce on a clean `HEAD` worktree |
| Unit test suite (per-directory) | **FAIL** | all clusters green in isolation except `tests/unit/entrypoints/mcp`, which cannot finish a run |
| Unit test suite (whole-tree) | **FAIL** | reports failures that do not reproduce in isolation (test-isolation defect) |
| HTTP / cURL matrix | PASS | `artifacts/release/bbadf108a.../curl_matrix.txt`, 7 groups |
| Route inventory | PASS | 414 paths / 443 operations, from the live `openapi.json` |
| Per-operation auth (runtime) | **PARTIAL** | 12 endpoints probed → 401/403; the other 431 verified only through the spec |
| Browser / Playwright | NOT_VERIFIED | no longer blocked by the missing auth scheme, but still not executed |
| Container image + SBOM | NOT VERIFIED | not built for this SHA |
| Signature / cosign | NOT VERIFIED | no image to sign |

> **Port 8000 in this environment is a container running `/app`, started
> 2026-09-11.** It answers 200 on `/health` and serves its own `openapi.json`.
> It is not this SHA. All runtime evidence was taken from a local instance on
> port 8011 started from the working tree.

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

### Found by actually running the application (`e91fb91fe` … `bbadf108a`)

These four were invisible to the test suite and to static gates; each was
confirmed on a live instance, then fixed with a regression test.

- **`exc_info` never attached a traceback** (`e91fb91fe`). The structlog
  chain had no `format_exc_info`, so `exc_info=True` rendered as
  `{"exc_info": true}` with no stack and an empty `LogRecord.exc_info` —
  across 116 `exc_info` and 138 `.exception()` call sites. Placed before
  `_mask_pii`, so tracebacks are PII-scrubbed too.
- **Every log timestamp lost its date** (`9a1987f49`). `PHONE` matched an
  ISO-8601 date: `2026-09-28T14:39:40Z` → `<phone>T14:39:40Z`. Events could
  not be ordered by day. A narrow lookahead excludes only `19xx`/`20xx`
  dates, with a trailing guard that keeps masking fail-closed.
- **`DataMaskingMiddleware` kept private copies of the PII patterns**,
  bypassing the declared single source of truth (`32ef4f246`). The copy had
  drifted, so `/ready` answered `"timestamp":"+***0928T15:12:46.355395+00:00"`.
- **Step-up tokens were returned to the client corrupted** (`f013e7317`).
  `PIIMaskingResponseMiddleware` excluded only `/api/v1/auth/login`; the
  phone pattern ate digit runs inside the hex signature, so login answered
  401 for a token it had just issued. Measured **8 of 40** corrupt before
  the fix, **0 of 40** after.

- **The OpenAPI spec described no authentication at all** (`bbadf108a`).
  `components.securitySchemes` was empty and none of the 443 operations
  carried a `security` field, because the guard lives in pure-ASGI
  middleware that FastAPI does not emit. Swagger had no Authorize button,
  "Try it out" could not pass a token, and generated clients shipped
  without auth. The spec now declares the four credential schemes taken from
  the same verifiers `verify_request` uses, and derives the public flag from
  `is_path_public` — the same source the runtime guard uses. Measured on the
  live service: **443/443** operations annotated, 0 unresolved references,
  **0 mismatches** with the guard.
- **The published spec was silently corrupted in 16 places.** Both response
  maskers were rewriting field descriptions and summaries to `***`:
  `Семантический поиск` → `*** поиск` (`_RU_SURNAMES` treats any Russian word
  ending in `-ский` as a surname), a phone example in a description → `***`,
  and the description of a field named `token` → `***` (masking by key name).
  The spec is built from source annotations and carries no runtime or tenant
  data — all 414 paths are static and DSL route definitions never reach
  OpenAPI — so masking it bought no privacy and only destroyed the contract.
  `/openapi.json`, `/docs`, `/redoc` and `/docs/oauth2-redirect` are now
  exempt. **16 artifacts → 0** on the live service.

  `_RU_SURNAMES` is deliberately **not** narrowed: narrowing it would weaken
  the privacy surface. The new scheme descriptions are worded to avoid the
  false positive, and two tests pin that.

---

## Known open defects

- **Per-operation auth is probed on 12 of 443 endpoints.** The spec now states
  the contract for all of them, but the runtime behaviour was only verified
  on 12 paths. The other 431 are covered by the spec, not by observation.
- **`_RU_SURNAMES` false-positives on ordinary Russian adjectives.** Any word
  ending in `-ский` / `-ова` / `-ин` is masked as a surname, so
  `Семантический`, `Логистический`, `Диагностический` become `***` in any
  Russian text that passes through a response masker. Not narrowed here,
  because narrowing weakens privacy; it needs a proper design decision.
- **`make ci` does not execute tests** — `make/pipelines.mk:22` ends at
  `test-collection-check`, which runs `pytest --co` only.
- `/api/v1/auth/step-up-request` issues a token with no credential check. Not an authz
  bypass (login still verifies the password) — it is a CSRF/session guard, and the
  token is not single-use.
- `DataMaskingMiddleware` masks by key name at any depth, so the legitimate
  `deprecations.password` field in `/api/v1/auth/methods` arrives as `"***"`.
- Logs report `environment: 'production'` while the `dev_light` profile sets
  `app.environment: "development"`; the line prefix says `[development@...]`.
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

- **Coverage ~52%, measured twice, ~18 p.p. below the 70% bar.**
  - `52.25%` — full run on `tests/unit` at `cee4c33e5` (62374 / 119376 lines).
  - `51.89%` — a later run on essentially this code, stopped at ~97% and
    combined with `coverage combine`.
  The 0.36 p.p. spread means the ~52% figure is stable, not a one-off.

  **Correction of an earlier claim in this document.** The aborted runs were
  previously attributed to a repository defect ("pytest aborts in
  `pytest_sessionfinish` with `OSError: cannot send (already closed?)`").
  The kernel log shows the real cause:

  ```
  kernel: Out of memory: Killed process 2155624 ([pytest-xdist r)
          total-vm:10125828kB, anon-rss:6449748kB
  ```

  Each xdist worker accumulates **~6 GB** of coverage data on a 15 GB machine.
  It reproduced identically at `-n auto` (10 workers on 4 CPUs) and at `-n 4`.
  This is an **environment limit, not a code defect**. To get a clean number,
  split the run per top-level package and combine, so no single worker exceeds
  available RAM. Not done — so no clean single-run figure is quoted here.
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