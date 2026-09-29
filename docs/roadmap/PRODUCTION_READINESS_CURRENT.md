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
4. **Coverage passes, but only for the subset that can run here** — 75.22%
   over unit segments (90988 / 120968), gate exit 0. The env-tier directories
   needing Docker/live servers are excluded, so no whole-tree figure exists
   yet. The old ~52% number was whole-`tests/unit` and is not comparable.
5. **The test suite is not isolation-safe** — the gRPC cluster (`9227f6ded`)
   and the frontend cluster (`3e1ff82ed`) are both fixed, but no whole-tree
   run has been completed on this machine, so no "suite is green" claim is
   possible yet.
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
| Architecture layers (frontend) | **PASS** | Closed at `0f36b7e9e`. No frontend file imports a non-facade backend module: the last 6 `src.backend.services` imports moved to `src.backend.core.frontend_facade` (which already exported every symbol used, so it was an import rewrite, not new API), 8 `registry_explorer` / `cost_attribution` symbols were re-exported through that facade, and `core.interfaces.import_gateway` was replaced by the facade's existing re-export. The two ratchet files go 5 failed → **17 passed**; `tests/unit/frontend` + `tests/unit/extensions` = 520 passed, 6 skipped. One case needed judgement: the "Операционные затраты" help snippet taught backend authors a backend import path, so rather than repointing it at a *frontend* facade, `track_cost` / `ResourceType` are now really exported from `core.api` and the example refers to that — true advice rather than a silenced string |
| Privacy lifecycle gate | PASS | `check_privacy_lifecycle.py --strict` exit 0, 5/5 backends have executing contract tests |
| Scheduler catchup wiring (W0) | **PASS** | all 5 W0 items verified at `12ead1617`: `add_job` present, `catchup*` keyword-only and never passed to APScheduler, `await materialize_window`, real executor via `run_pending`, facade integration against a real `AsyncIOScheduler` + SQLite. 147 tests pass. P3-13 closed by `test_pending_tick_executes_executor`, which asserts a real pending tick ran and fails with "P3-13 НЕ закрыт" otherwise |
| Scheduler backend contract | **FAIL** | `TemporalSchedulerBackend` declares `schedule_cron` / `schedule_oneshot` / `cancel` / `list_jobs` as `async` while `SchedulerBackend` declares them sync. The `isinstance` conformance test cannot detect it (`@runtime_checkable` checks names only, not signatures). With `scheduler_backend="temporal"`, `remove_job` discards an un-awaited coroutine and never cancels. Latent on the default `apscheduler` path. See the known-defects entry |
| Optional-tenant gate | PASS | `check_no_new_optional_tenant.py --strict` exit 0, 123 baseline = 123 current |
| Tenant isolation (static) | PASS | `check_tenant_isolation.py --strict` exit 0 |
| Tenant isolation (runtime) | **FAIL (negative)** | live run at `f013e7317`: empty/`null` `X-Tenant-Id` → 401, no data returned |
| Object authorization (classifier) | PASS | 117 callsites, 0 unknown (`classify_object_authorization.py` exit 0) |
| Object authorization (coverage gate) | **FAIL** | `check_object_authorization.py` prints 2 ❌ — ownership coverage 17/159 (10.7%, threshold 50%) and 127 service `.get(id)` without tenant filter. The gate is honest only under `--strict` (exit 1); `make check-object-auth` and `audit-2026-09-22` call it **without** `--strict`, so both report success. The classifier counts *classification completeness*, the gate measures *authorization coverage* — they are different properties |
| CI composite | **FAIL (not PARTIAL)** | Downgraded from PARTIAL at the first honest end-to-end observation. Both wiring debts are closed at `e59534f88`: `make ci` now ends at a real `unit-tests` step (`pytest tests/unit --timeout=120 -n auto --dist loadfile`) instead of `pytest --co`, and before that it executed **715 of 20 780 tests (3.4%)**, only the `check-ai-safety` subset. The layer gate is wired in (`$(MAKE) layers`), verified by injecting a real `services→dsl` violation and watching `make ci` exit 2 at `runtime.mk:5`. The composite now **fails, correctly**: `make unit-tests` exits 1 on the 41 reproducible defects. This is a truthful red, not a regression in the pipeline — the suite was always red, the gate simply never executed it. Measured on `54677e6b2`: every gate *before* the test step passes — `format-check lint-strict deps-check-strict secrets-check check-waf-coverage-strict check-task-registry check-tenant-isolation layers test-collection-check` → **exit 0** (layers 0 new / 22 legacy across 2554 files; optional-tenant 123 = 123, no drift). Pinned by `tests/unit/tools/test_ci_runs_layer_gate.py` (8 tests, mutation-verified) |
| CI time bound | PASS (was absent) | No per-test time bound existed: 12 `@pytest.mark.timeout(N)` were deliberate no-ops because `pytest-timeout` was not installed, so a hanging test could stall a pipeline indefinitely — the first whole-tree run died at 99% for exactly this reason. `pytest-timeout>=2.4.0,<2.5.0` added at `e59534f88`; 2.5.0 is **yanked on PyPI** ("accidental breaking change"), and 2.4.0 omits 3.14 from its classifiers, so it was verified empirically on Python 3.14.0 (marker fires with no global flag; all 12 existing markers still pass with timeouts live) |
| Deployment artifacts | PASS (were broken at HEAD) | `ops/compose/docker-compose.light.yml` shipped **two unresolved merge-conflict blocks** and did not parse as YAML; `runAsUser/Group/fsGroup` were `1000` in *both* k8s manifests while `values.yaml` and `ops/compose/Dockerfile:61` (`--uid 10001`) say `10001`. Fixed at `6da43abc8` to the side the in-file comments and the healthy sibling `docker-compose.yml:78-79` identify as correct. `tests/unit/deploy` 36 passed (was 32/1 failed/2 errors); mutation-verified in four directions |
| Application starts and serves | PASS | live uvicorn, `dev_light` profile, `/health` → 200 |
| Unauthenticated data access | PASS | 12 endpoints → 401/403, no payload returned |
| Login credential enforcement | PASS | 2 wrong-password probes → 401, identical message (no user enumeration) |
| OpenAPI auth declaration | PASS | 443/443 operations declare `security`, 4 schemes, 0 unresolved refs, 0 mismatches with the runtime guard (`bbadf108a`) |
| OpenAPI integrity | PASS | 0 masking artifacts in the served spec (was 16) |
| CSP scoping | PASS | relaxed only for `/docs` and `/redoc`; `/openapi.json` and API responses keep `default-src 'self'` |
| Readiness guards | PASS | `make readiness-check` exit 0 |
| Pre-production | **FLAKY — not a deterministic verdict** | `make pre-prod-check` has produced 25/37 with 1 FAIL and 26/37 with 0 FAILED on one unchanged SHA, observed by an independent verifier and by the owner minutes apart. Cause is check #19 `startup-time <3s`: the gate looks absolute (3.0s) but with a baseline present the verdict is `baseline × 1.30` = **2.145s** (`tools/checks/startup_time.py:181`, baseline 1.65s). 13 standalone measurements span 1.782–2.263s and exceed the limit on 1 of 13 (8%). After `08115534f` the tally is 27/37, 7 WARN, 3 SKIP. The startup gate is the flake, not the rest of the suite. **Flake addressed at `e59534f88`**: the gate now takes 3 passes and judges the median, budgets unchanged — re-measurement still pending, so the row stays FLAKY until a clean run is observed |
| Coverage gate | **PASS (partial)** | 75.22% vs 70% threshold, gate exit 0 — measured over unit segments only; env-tier dirs (smoke/rpa/chaos/e2e) excluded because they need Docker/live servers |
| Migration chain integrity | PASS | `alembic heads` single head, `alembic history` 25 linear revisions |
| Migration apply / rollback | ENV_FAILURE | `alembic upgrade head` aborts in config load (`redis AuthenticationError`); no Redis/Vault here |
| Privacy integration (PG/Redis/MinIO/Qdrant/LangMem) | NOT VERIFIED | backends not running |
| Tooling test suite | **FAIL** | `tests/unit/tools/`: 10 failures, all reproduce on a clean `HEAD` worktree |
| Unit test suite (per-directory) | **PASS** | at `44d7ae4c2` every cluster under `tests/unit/entrypoints/` is green: grpc 66, api 338, mcp 106, middlewares 575, websocket 65, scheduler 15, sse 36, stream 16, webhook 12 (run separately to stay under the RAM ceiling) |
| Unit test suite (whole-tree) | **FAIL — first complete number in existence** | Whole-tree run on a frozen SHA via the new `make unit-tests` (`e59534f88`): **19 814 passed / 152 failed / 11 errors / 187 skipped / 49 xfailed / 42 xpassed in 11m56s**, target exit 1. Replaces the earlier `PARTIAL (incomplete run)` row, which had no pytest summary because the run was killed at 99%. Triaged: re-running the affected files **in isolation** yields reproducible defects — the rest is cross-test pollution, not product bugs. The isolated count has fallen **41 → 25 → 16 → 13 → 10** as stale/wrong gates were corrected. Seven of them were blocking CI on valid code: `b7cb2a478` (the layer-violation test ran the gate on Python 3.12 and reported 163 unparseable files that are valid 3.14; it also pinned an obsolete baseline and a lower bound that failed the build for having *too few* legacy exceptions, inverting the "may only shrink" law), `cb5a9ea38` (the "Py2 except syntax" lint banned PEP 758, which 3.14 parses as a tuple and which catches every listed type — proven, not assumed), `5471623d1` (the schemas-only entry test read a nested `[plugin]` table removed by ADR-0343), `b1fbcdfd9` (the broken-YAML-refs test read an `activities[]` schema replaced by `steps[]`), `885c5b5aa` (the telegram test asserted a raw `httpx.AsyncClient`, so it passed *only* when the WAF facade was bypassed), `83f7ce8b4` (the DLQ migration test matched a file the provider had already left, and its S87 guard could not see an aliased direct import) and `122d2c7c0` (the docs scaffold test validated Sphinx, which B2/M10.2 removed in favour of mkdocs — recreating `docs/conf.py` would have resurrected a dropped tool). One further fix was a genuine product bug: `640610627`, where `StructlogLogger.name` returned `'BoundLoggerLazyProxy'` instead of the logger name because it probed `_logger` before the object's own `name`, and on an unbound lazy proxy `_logger` is `None`. The remaining 10 are: frontend layer violation 5, `hitl_service` deprecation 4, `credit_pipeline` extension unimportable 1. Note on the doc gate (`d4c5ced5a`): `find_missing()` returns paths **cited in docs** that do not exist — dangling links, not undocumented modules; the 146 + 8 entries are frozen in `.baselines/doc-references.baseline.json` and the gate now fails only on new ones |
| HTTP / cURL matrix | PASS | `artifacts/release/98698dd51.../curl_matrix.txt`, 8 groups |
| Route inventory | PASS | 414 paths / 443 operations, from the live `openapi.json` |
| gzip / ASGI response validity | PASS | `openapi.json` + gzip → 200 / 58 150 B with `content-encoding: gzip` (was 000 / 0 B) |
| Per-operation auth (runtime) | **PARTIAL** | 10 endpoints probed → 401/403; the other 433 verified only through the spec |
| MCP surface (mount + auth wrap) | PASS | `44d7ae4c2`: `/mcp` mounted in the live app, chain `McpAuthMiddleware -> StarletteWithLifespan`, inner route `/` (D-AUDIT-20812). Cluster 106 passed / 0 failed |
| MCP protocol round-trip | **NOT VERIFIED** | the outer `AuthRequiredMiddleware` answers 401 before `McpAuthMiddleware` runs; an authenticated `initialize` / `tools/list` needs an API key this environment cannot mint |
| Browser / Playwright | PASS with caveat | Playwright run: 7 PASS, 1 PARTIAL, 0 FAIL, zero console errors. `/docs` loads and Authorize works; `/redoc` renders all 443 operations. Swagger UI alone renders 14 — third-party limit, diagnosed |
| Container image + SBOM | PASS | `make sbom-diff-gate` exit 0, "No known vulnerabilities found", `RESULT: PASS` at `e6ad492fe` (measured again on `abeb41dd5`). The gate now regenerates its pip-audit input and rejects a report older than the dependency list, so a stale file can no longer fabricate CVEs |
| Signature / cosign | PARTIAL | `cosign verify-blob` on the SBOM reported Verified OK for `24c02ab06`; the mechanism is proven but nothing is signed **in a registry** (no registry :5000 available) |
| OWASP ZAP | **PARTIAL** | scan ran against the HEAD app, but the summary "FAIL-NEW 0, WARN-NEW 7, PASS 60" is not reproducible: the raw report has no `failNew` field, holds 12 alerts (4 Medium/High CSP + SRI) with empty `nodes`, and no gate in the tree computes that framing. See the measurement note |

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

### Found by running the failing tests and reading what they assert

`422b012b3`, `3fa6cd206`. Eleven failures across three files, and in every one
the **production code was correct** — the tests still asserted contracts that
had been deliberately replaced.

- `_FakeMcp.http_app()` took no kwargs, but the code calls
  `candidate(stateless_http=True, path="/")` (D-AUDIT-20812, a real
  Starlette `Mount` 404 fix). The `TypeError` was swallowed by a broad
  `except` and surfaced as a `RuntimeError` that looked like a FastMCP
  problem. The real signature was checked against vendor docs, not guessed.
- A test patched private `_verify_api_key`/`_verify_jwt` after S93 W3 had
  moved the middleware to the public `verify_request()`.
- `mock_row.status` was a `MagicMock` unrelated to the members of the
  `terminal` set, so `row.status in terminal` was always false. With
  `asyncio.sleep` mocked, the poll loop **hot-spun for the full 300 s
  timeout** — that is where the 301.92 s went.
- `_mount_mcp_http` had moved to `app_factory` and now takes the app as an
  argument; the tests still called `main._mount_mcp_http()`.
- Two smoke tests expected 200 from admin routers that the S202 audit fix had
  put behind `require_admin`. **The guard was not weakened** — the tests now
  inject an admin `AuthContext` through `request.state.auth`, the same
  channel production uses — and two negative tests were added that did not
  exist before, since the guard had no negative coverage.

Result: MCP cluster `8 failed / 305.74 s` → `4 failed / 1.75 s`; combined
affected set 15 failed → 4. The 87× speedup is itself evidence — it is the
removed 300 s spin.

### Installing fastmcp exposed a test that was green for the wrong reason

`44d7ae4c2`. `fastmcp 4.0.3` — the version `uv.lock` pins — is now installed,
so the MCP cluster is `106 passed, 0 failed` and `/mcp` is genuinely mounted
in the live app (`McpAuthMiddleware -> StarletteWithLifespan`, inner route
`/`).

Making that library available also let two previously-unrunnable tests execute,
and one of them was asserting nothing:

```python
patch("...ai_stack.mcp_settings", side_effect=ImportError)
```

`side_effect` fires only when the mock is **called**, and
`from ... import mcp_settings` merely binds a name — so no `ImportError` was
ever raised. The test was green only because `create_mcp_http_app()` happened
to fail for an unrelated reason and a broad `except` skipped the mount. It now
uses `patch.dict("sys.modules", {..., None})`, which makes the import really
raise.

The lesson generalises: **a test that asserts the right thing can still verify
nothing**, and this one would have kept passing in CI where fastmcp *is*
installed — for the same wrong reason. Green is not the same as checked.
---

## Known open defects

- **`TemporalSchedulerBackend` violates the `SchedulerBackend` Protocol on 4 of
  6 methods, and the conformance test cannot see it.** `SchedulerBackend`
  (`src/backend/core/interfaces/scheduler.py:81`) declares `schedule_cron`,
  `schedule_oneshot`, `cancel` and `list_jobs` as **sync**, and only `start` /
  `stop` as `async`. `APSchedulerBackend` matches that exactly.
  `TemporalSchedulerBackend` declares **all six** as `async`.

  The test that is supposed to catch this —
  `tests/unit/core/interfaces/test_scheduler_protocol.py:162`
  `assert isinstance(backend, SchedulerBackend)` — passes, because
  `@runtime_checkable` protocols verify only that the attribute *names* exist.
  They never compare signatures or coroutine-ness. Measured with
  `inspect.iscoroutinefunction`:

  | method | protocol | APSchedulerBackend | TemporalSchedulerBackend |
  |---|---|---|---|
  | `start` | async | async | async |
  | `stop` | async | async | async |
  | `schedule_cron` | sync | sync | **async** |
  | `schedule_oneshot` | sync | sync | **async** |
  | `cancel` | sync | sync | **async** |
  | `list_jobs` | sync | sync | **async** |

  Both classes report `issubclass(..., SchedulerBackend) is True`.

  **This is reachable in production.** `settings.scheduler.scheduler_backend`
  is `Literal["apscheduler", "temporal"]` with default `apscheduler`
  (`src/backend/core/config/features/__init__.py:258`). With `temporal`
  selected, `SchedulerFacade.remove_job` calls `backend.cancel(job_id)`
  synchronously and discards the result
  (`src/backend/services/scheduler/facade.py:283`). Verified at runtime: that
  call returns a coroutine that is never awaited, so the job is **never
  cancelled** and the caller receives no error. A silent no-op on a
  cancellation path, plus a coroutine that is dropped on the floor.

  Two decisions are needed and neither is made here: whether the Protocol
  should declare the mutating methods `async` (they are I/O and both real
  backends already are, for Temporal) or whether the Temporal backend should
  become sync; and whether `remove_job` should `await` defensively. Changing a
  public contract needs an ADR.

  Mitigating factor, stated plainly: `apscheduler` is the default and the
  documented production path, and the config description still calls
  `temporal` a stub. So the defect is latent on the default configuration, not
  firing in the current production path. It is recorded because the switch is
  a config value, not a code change, and the guard that should catch a bad
  backend is demonstrably blind.

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
  `test-collection-check`, which runs `pytest --co` only. It also does not run
  `check_layers.py`, so a green `make ci` says nothing about layer compliance;
  measured at `12ead1617` the two gates disagreed (layers exit 1, ci exit 0).
- **`check_object_authorization.py` is wired without `--strict`.**
  `make/quality.mk:293` (`check-object-auth`) and `make/quality.mk:319`
  (`audit-2026-09-22`) call the gate in its default mode, which prints the ❌
  issues and still returns 0. Under `--strict` the same input returns 1
  (coverage 17/159 = 10.7%, and 127 service `.get(id)` without tenant filter).
  Both are advisory today — the target is not in the `ci` composite.
- **`DeferredMixin` reaches past the backend Protocol into APScheduler.**
  `src/backend/services/execution/invoker/deferred_mixin.py:142` and `:161` call
  `scheduler_manager.scheduler.add_job(...)` directly. `SchedulerBackend`
  (`src/backend/core/interfaces/scheduler.py:118`) already declares
  `schedule_oneshot`, so the protocol is being bypassed. Three tests in
  `tests/unit/services/execution/test_invoker.py` pin the current shape through
  a `_StubScheduler.add_job`, so fixing this changes the test contract. Not
  fixed here: it is a production edit that needs an explicit decision.
- **Fixed at `88cf0f37d` — `test_builder_service_proxy.py` identity tests.**
  `12ead1617` had moved `route_registry` / `YAMLStore` behind a string-keyed
  lazy proxy to keep `services → dsl` off the layer gate. The gate went green
  and two tests went red, which is a trade rather than a fix. The proxy was
  unnecessary: `src.backend.core.api.extensions` re-exports both symbols and is
  listed in `check_layers.py:136` `CORE_LAZY_PROXY_EXCEPTIONS` as an intentional
  facade, so importing from there is `services → core`, which `ALLOWED` permits
  outright. Identity is preserved because the facade re-exports the same
  objects — verified at runtime, `route_registry is route_registry` and
  `YAMLStore is YAMLStore`. `tests/unit/services/dsl` now 8 passed / 0 failed
  (was 2 failed), `check_layers` exit 0, `make ci` exit 0. The 2 tests in
  `test_builder_service_imports.py` remain skipped on purpose: they assert the
  pre-Sprint-225 import shape.
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
- Test isolation, frontend cluster — **fixed at `3e1ff82ed`**.
  `test_components.py` installed `streamlit` and `pandas` mocks at module
  level, i.e. during collection, and never restored them. Two leaks followed:
  `sys.modules` stayed poisoned (so `api_clients/cached.py` died on
  `@st.cache_data(...)` with `AttributeError`), and `components` itself was
  cached against the mock. Both are now scoped by a fixture.
  Cluster `tests/unit/frontend`: **23 failed → 5**. The remaining 5 are
  layer-boundary ratchets, left failing deliberately — see below.
  This corrects an earlier note here: the cluster failed in isolation too,
  not only in combined runs.
- ~~`tests/unit/entrypoints/mcp` failures~~ — **resolved at `44d7ae4c2`**.
  The four remaining failures were `ImportError: fastmcp is not installed`;
  `fastmcp 4.0.3` (the version `uv.lock` pins) is now installed and the
  cluster is `106 passed, 1 xfailed, 0 failed`. `/mcp` is now genuinely
  mounted — verified in the live app as
  `McpAuthMiddleware -> StarletteWithLifespan` with inner route `/`, which is
  the D-AUDIT-20812 contract. A full authenticated JSON-RPC round-trip is
  still **NOT VERIFIED**: the outer `AuthRequiredMiddleware` returns 401
  before `McpAuthMiddleware` runs, and completing it needs an API key that
  this environment cannot mint.
- 10 tooling-test failures (audit-deprecation ×4, SBOM ×2, scaffold, routebuilder
  MRO, codemod idempotency, plugin scaffold) — all reproduce at clean `HEAD`.
- 123 optional `tenant_id` contracts remain tracked, not removed.
- 22 legacy layer exceptions in the backend allowlist.

---

## Measurement notes and staleness

- **OWASP ZAP: the "FAIL-NEW 0, PASS 60" summary is not reproducible from the
  report it cites. Status: PARTIAL, not VERIFIED.**
  `wave_evidence.json` at `c066786fb` records
  `zap_baseline.verdict = "PASS: FAIL-NEW 0, WARN-NEW 7 (hardening-заголовки:
  COEP и пр.), PASS 60"` and points at `zap/zap_report.json` +
  `zap_report.html`. Reading the raw report instead of the summary:
  - it has **no** `failNew` field, and no gate in `tools/` or `make/` computes
    one, so the "FAIL-NEW" framing has no producing code in the tree;
  - it contains **12 alerts**, not 60 — 4 with `riskcode "2"`
    (`Medium (High)`), 4 with `"1"` (Low), 4 with `"0"` (Informational);
  - the 4 Medium/High ones are CSP (`script-src unsafe-inline`,
    `style-src unsafe-inline`, `Failure to Define Directive with No Fallback`)
    and `Sub Resource Integrity Attribute Missing`;
  - every alert's `nodes` list is **empty**, so no alert can be attributed to a
    URL and none can be diffed against a baseline. A baseline comparison
    cannot be reconstructed from this artifact.

  The CSP findings are plausibly the documented `/docs` + `/redoc` relaxation
  (see the CSP row above) rather than new defects, but "plausibly" is not
  evidence and this audit does not claim otherwise. What the artifact
  supports is: a scan ran against the HEAD app on :8081, and 12 alerts were
  recorded. The counts in the summary are not reproducible.

- **Coverage: 75.22% over the runnable subset, NOT over the whole tree.**
  - The ~52% figures below were whole-`tests/unit` numbers. A segmented run at
    `b5d5ed9f3` (56 segments, `--cov-append`, then `coverage combine` and
    `xml`) reports `lines-covered="90988" lines-valid="120968"
    line-rate="0.7522"` — the canonical gate passes at exit 0.
  - **The caveat is material and is recorded in the artifact itself:** the
    env-tier directories that need Docker / live servers (top-level `smoke`,
    `rpa`, `chaos`, `e2e`) did not take part, because they cannot run here.
    So 75.22% answers "how much of what can run, is covered", not "how much of
    the repository is covered". A whole-tree number is still not available.
  - Historical whole-tree figures, for comparison:
    `52.25%` — full run on `tests/unit` at `cee4c33e5` (62374 / 119376 lines);
    `51.89%` — a later run, combined. The 0.36 p.p. spread means the ~52%
    figure is stable, not a one-off.

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
- **SBOM gate: verdict and exit code disagreed.** `_format_report()` took a
  `new_cves` argument and never used it, so a CVE-only failure printed
  `RESULT: PASS` while `main()` returned 1. Fixed at `15479d1c9`; the mask was
  hiding 6 CVE/advisory IDs absent from the 2026-09-14 baseline
  (CVE-2026-61632, CVE-2026-67422, GHSA-9xwg-3r6f-jcx2, GHSA-gm37-52c6-37mw,
  PYSEC-2026-3609, PYSEC-2026-3654). **Correction after triage:** those are
  **2 vulnerabilities, not 6** — `_extract_vuln_ids` adds each advisory's
  aliases, so every finding is counted as PYSEC + GHSA + CVE.

  Both are in `pymdown-extensions 10.21.3`, which is pinned in `uv.lock`:

  | advisory | aliases | fix | class |
  |---|---|---|---|
  | PYSEC-2026-3609 | CVE-2026-61632, GHSA-9xwg-3r6f-jcx2 | 11.0.0 | path traversal in `pymdownx/b64.py` — reads image-extension files outside `base_path` (targeted file read, not arbitrary read) |
  | PYSEC-2026-3654 | CVE-2026-67422, GHSA-gm37-52c6-37mw | 11.0.1 | ReDoS / CWE-1333 in four inline processors, reachable in the **default** configuration |

  **Not live in this environment:** `pymdown-extensions` is not installed
  (`PackageNotFoundError`), and `mkdocs-material` / `mkdocstrings` /
  `markdown` are absent too, so a fresh `pip-audit` correctly reports "No
  known vulnerabilities found". The 6 IDs came from the stale
  `dist/pip-audit.json` of 2026-09-22.

  **The blocker is ours.** `pyproject.toml:519` declares
  `pymdown-extensions>=10.7.0,<11.0.0` in the `docs` extra, and that cap
  excludes both fixes (11.0.0 and 11.0.1). `mkdocs-material` itself pins no
  upper bound, so the cap is removable. Anyone installing `[docs]` today gets
  the vulnerable version with no in-range upgrade.

  Re-measured at `3bc8a25f5`: `make sbom-diff-gate` exits **1** and prints
  `RESULT: FAIL (new CVEs vs baseline)` — the verdict and the exit code agree,
  so the `15479d1c9` fix holds. `dist/pip-audit.json` attributes both PYSEC IDs
  to `pymdown-extensions 10.21.3` and nothing else. `import pymdownx` fails in
  both the system interpreter and the `uv` venv (364 packages, none of them
  mkdocs/pymdown), confirming the `[docs]` extra is not installed and the
  exposure is docs-tooling only, not a runtime dependency.

- **The FAIL above was a stale-input artifact, not a real finding. The gate has
  no staleness check.** `make/security.mk:89` regenerates the audit report only
  when it is *missing*:

      @test -f dist/pip-audit.json || $(UV_RUN) pip-audit --format json …

  A file that exists but predates the current environment is never refreshed, so
  `sbom_diff_gate.py:330` compares a months-old report against the baseline and
  reports CVEs for packages that are not installed and not in the SBOM.

  Measured at `68c0dd68c`, same commit, no code change between the two runs:

  | Input | Content | Gate |
  |---|---|---|
  | `dist/pip-audit.json` dated 2026-09-22 | 374 deps, 4 vuln records, all `pymdown-extensions 10.21.3` | exit 1, `RESULT: FAIL` |
  | same file regenerated by `pip-audit` | 361 deps, **0** vulns, "No known vulnerabilities found" | exit 0, `RESULT: PASS` |

  Cross-checks that the stale report was the only thing wrong: the freshly
  generated `dist/sbom/sbom.cdx.json` (357 components) contains **no**
  pymdown component; `.baselines/sbom.baseline.json` (356 components) contains
  none either; `.baselines/pip-audit.baseline.json` has 0 vulns; and
  `dist/audit-requirements.txt` — regenerated from the live venv — does not list
  `pymdown` at all. A fresh scan therefore cannot produce those IDs.

  So the CVE finding recorded above is withdrawn as a *current* finding. It
  remains true that `pyproject.toml:519` caps `pymdown-extensions<11.0.0` in the
  `[docs]` extra, so the risk is real for anyone who installs that extra; it is
  simply not reachable from this environment's dependency set.

  The defect worth fixing is the gate, not the dependency: a supply-chain gate
  that reports phantom CVEs from a stale file is as misleading as one that
  reports `PASS` while exiting 1. `make sbom-diff-gate` should regenerate the
  audit report, or refuse to run when its input is older than the SBOM.
- **`sbom-diff-gate` is not invoked by `make ci`.** The composite runs
  format-check, lint-strict, type-check-strict, deps-check-strict,
  secrets-check, check-waf-coverage-strict, check-ai-safety and
  check-python3-syntax. CLAUDE.md V4 declares SBOM + pip-audit + cosign
  *mandatory* CI gates, so this one exists and works but never runs in CI.
- **`test_quality_results_aggregator.py` is slow, not hung.** An earlier note
  here called it a hang on the strength of a 90 s per-file cap. Re-measured
  with an adequate timeout: `6 passed in 91.83s`, matching its own docstring
  (~95 s, aggregator runs ~10 gates). The cap was the defect, not the test.
  Note it *writes* `.audit/quality-results.json`, so it must not be run while
  another agent has uncommitted edits to that file.

---

## How to refresh this document

1. Re-measure coverage: `uv run pytest tests/unit --cov=src/backend --cov-report=xml`.
2. `uv run python tools/check_coverage_gate.py main --coverage-xml coverage.xml --baseline .baselines/coverage.json --threshold 70 --strict`.
3. Re-run `make ci`, `make readiness-check`, `make pre-prod-check`.
4. Write per-SHA evidence to `artifacts/release/<sha>/EVIDENCE.md`.
5. Update this file and `.audit/last_run.json` **only** with results from that
   same SHA. Do not copy numbers between commits.
