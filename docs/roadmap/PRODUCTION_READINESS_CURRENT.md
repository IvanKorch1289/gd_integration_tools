# Production Readiness — CURRENT (canonical)

> **This is the canonical current-status document for the repository.**
> Generated 2026-09-28, last updated for SHA `98698dd51`.
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

1. **Every gzip response was silently dropped.** The GZip middleware rebuilt
   `http.response.start` with `str` headers, which ASGI forbids; uvicorn raised
   `TypeError: cannot use a bytes pattern on a string-like object` and closed
   the connection **with no response**. Any body over 500 bytes, to any client
   offering gzip — that is, to every browser. Fixed in `2a347ee70`.
2. **`/docs` and `/redoc` returned HTTP 200 with an empty page.** The project
   `Content-Security-Policy` (`default-src 'self'`) was applied to the
   documentation routes, which load their assets from a CDN and run inline
   scripts. This is why nobody noticed the missing `securitySchemes`: the page
   could not be opened at all. Fixed in `2a347ee70`.
3. **Swagger UI shows 14 of 443 operations and 3 of 92 tags.** Diagnosed: Swagger
   UI 5 stops rendering silently past ~72 operations. Reproduced on a static
   file server with no application and no CSP, so it is a third-party limit, not
   a defect here — and not a regression from the CSP/gzip fixes, which moved
   `/docs` from 0 rendered operations to 14. `/redoc` renders the full
   specification and is the working browser view.
4. **Coverage is far below the project's own bar** — ~52% measured against a
   70% threshold. The gate reports this honestly instead of silently passing.
   Two independent measurements agree within 0.36 p.p.
5. **The test suite is not isolation-safe** — the gRPC cluster is fixed
   (`9227f6ded`), but the frontend `shared/test_components.py` cluster still
   fails only in combined runs, so no "suite is green" claim is possible yet.
6. **`make ci` never runs the tests.** It ends at `test-collection-check`, which
   calls `pytest --co`. Exit 0 means "tests import", not "tests pass".
7. **No release artifact for this SHA** — no container image, no SBOM, no
   signature.
8. **Tooling suite is red** — 10 failures in `tests/unit/tools/` that reproduce
   on a clean worktree.
9. **Per-operation auth is only probed on 10 of 443 endpoints.** The spec now
   declares the contract for all of them, but the runtime behaviour was
   verified on 10 paths, not 443.

Every defect above that is marked *fixed* was found by **running the
application**, not by the test suite: the traceback loss, the corrupted
`timestamp` field, the step-up token corruption, the missing auth description
in the OpenAPI spec, the dropped gzip responses and the blanked documentation
pages. Static analysis and `curl` without `Accept-Encoding` saw none of them.

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
| CI composite | PASS with caveat | `make ci` exit 0 at `98698dd51` — but it does not execute tests |
| Application starts and serves | PASS | live uvicorn, `dev_light` profile, `/health` → 200 |
| Unauthenticated data access | PASS | 12 endpoints → 401/403, no payload returned |
| Login credential enforcement | PASS | 2 wrong-password probes → 401, identical message (no user enumeration) |
| OpenAPI auth declaration | PASS | 443/443 operations declare `security`, 4 schemes, 0 unresolved refs, 0 mismatches with the runtime guard (`bbadf108a`) |
| OpenAPI integrity | PASS | 0 masking artifacts in the served spec (was 16) |
| CSP scoping | PASS | relaxed only for `/docs` and `/redoc`; `/openapi.json` and API responses keep `default-src 'self'` |
| Readiness guards | PASS | `make readiness-check` exit 0 |
| Pre-production | **FAIL** | `make pre-prod-check` exit 2 — 25/37 PASS, 1 FAIL (coverage), 8 WARN, 3 SKIP |
| Coverage gate | **FAIL** | ~52% vs 70% threshold; gate correctly reports FAIL (exit 2) |
| Migration chain integrity | PASS | `alembic heads` single head, `alembic history` 25 linear revisions |
| Migration apply / rollback | ENV_FAILURE | `alembic upgrade head` aborts in config load (`redis AuthenticationError`); no Redis/Vault here |
| Privacy integration (PG/Redis/MinIO/Qdrant/LangMem) | NOT VERIFIED | backends not running |
| Tooling test suite | **FAIL** | `tests/unit/tools/`: 10 failures, all reproduce on a clean `HEAD` worktree |
| Unit test suite (per-directory) | **FAIL** | all 16 clusters under `tests/unit/entrypoints/` re-measured at `9227f6ded`: green except `mcp` (8 failed / 98 passed, 305 s) |
| Unit test suite (whole-tree) | **FAIL** | reports failures that do not reproduce in isolation; gRPC half fixed at `9227f6ded`, frontend `shared/test_components.py` half still open |
| HTTP / cURL matrix | PASS | `artifacts/release/98698dd51.../curl_matrix.txt`, 8 groups |
| Route inventory | PASS | 414 paths / 443 operations, from the live `openapi.json` |
| gzip / ASGI response validity | PASS | `openapi.json` + gzip → 200 / 58 150 B with `content-encoding: gzip` (was 000 / 0 B) |
| Per-operation auth (runtime) | **PARTIAL** | 10 endpoints probed → 401/403; the other 433 verified only through the spec |
| Browser / Playwright | PASS with caveat | Playwright run: 7 PASS, 1 PARTIAL, 0 FAIL, zero console errors. `/docs` loads and Authorize works; `/redoc` renders all 443 operations. Swagger UI alone renders 14 — third-party limit, diagnosed |
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

### Found by actually running the application (`e91fb91fe` … `2a347ee70`)

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

- **Every gzip response was dropped with no reply** (`2a347ee70`). The GZip
  middleware rebuilt `http.response.start` from `MutableHeaders.items()`, which
  yields `(str, str)`, while ASGI requires `(bytes, bytes)`. Uvicorn raised
  `TypeError: cannot use a bytes pattern on a string-like object` and closed the
  connection without a response. Reproduced with plain curl:
  `GET /openapi.json` with `Accept-Encoding: gzip` → **HTTP 000, 0 bytes**;
  without gzip → 200 / 494 406 bytes. After the fix → 200 / 58 150 bytes with
  `content-encoding: gzip`. Any body over 500 bytes was affected, to any client
  offering gzip — that is, to every browser.
- **`/docs` and `/redoc` served an empty page under HTTP 200** (`2a347ee70`).
  The project CSP (`default-src 'self'`) was applied to the documentation
  routes, which load assets from a CDN and run inline scripts. The console
  showed five blocked loads. This is the reason the missing `securitySchemes`
  went unnoticed for so long: the page could not be opened. The relaxation is
  scoped to `/docs` and `/redoc` only; `/openapi.json` and every API response
  keep `default-src 'self'`.

Browser verification on this SHA: `/docs` 200, Authorize button present and
selectable, `/redoc` renders the security contract, **zero console errors**.
Screenshots and the machine-readable report are in `artifacts/e2e/`.
---

## Known open defects

- **Swagger UI renders 14 of 443 operations across 3 of 92 tag sections.**
  Diagnosed by bisection: the break is between 71 and 72 operations. Ruled out
  — slow rendering (unchanged after 120 s), truncated download (400 KB and
  522 KB arrive whole), a specific `requestBody` (four mutations all still
  fail), and the application itself (reproduced on a static server with no app
  and no CSP). Swagger UI 5 limitation; `/redoc` shows the full spec, so the
  contract is still browsable.
- **Per-operation auth is probed on 10 of 443 endpoints.** The spec states the
  contract for all of them, but runtime behaviour was only verified on 10 paths.
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
- Test isolation, gRPC cluster — **fixed at `9227f6ded`**.
  `test_file_stream.py::_install_protobuf_stubs()` installs an empty
  `FileServiceServicer = type("Stub", (), {})` at module level, and the servicer
  imported under it inherits that base permanently: rolling back `sys.modules`
  cannot help once the class object exists. The 4 RPCs of `files.proto`
  (`DeleteFile`, `DownloadFile`, `GetFile`, `UploadFile`) and the 1 of
  `invoker.proto` (`Invoke`) were missing from the MRO, so three tests in
  *sibling* files failed. Those tests were correct; the stub was wrong.
  Before `3 failed, 63 passed` (3 random seeds at HEAD) → after `66 passed`
  (5 random seeds), and each of the 7 files also passes standalone.
  Only the poisoning fixture changed; no assertion was edited.
- Test isolation, frontend cluster — still open. The
  `shared/test_components.py` cluster fails only in combined runs. Needs
  fixtures, not test edits.
- `tests/unit/entrypoints/mcp` has 8 pre-existing failures
  (`test_http_server_auth_wrap.py` ×4, `test_http_transport.py` ×2,
  `test_workflow_tools.py` ×2); measured `8 failed, 98 passed, 1 xfailed` in
  305 s at `9227f6ded`. The run needs ~5 min, so short timeouts can make it
  look like a hang — earlier notes here said it "cannot complete a run",
  which this measurement corrects.
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
