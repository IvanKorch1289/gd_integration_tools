# Evidence — `3fa6cd206` (MCP / admin test-contract drift)

Measured after both commits landed, on this tree. Nothing is carried across
SHAs.

## Claim ledger

| Claim | Evidence command | Exit | Code path | Runtime/test | Counterevidence | Status |
|---|---|---:|---|---|---|---|
| MCP cluster improved 8 → 4 | `pytest tests/unit/entrypoints/mcp -q` | 1 | `entrypoints/mcp/*` | `8 failed, 98 passed, 305.74 s` → `4 failed, 102 passed, 1.75 s` | — | **VERIFIED** |
| Adjacent suites 7 → 0 | `pytest tests/unit/test_main.py tests/smoke/test_admin_and_mcp.py` | 0 | `main`, `admin_schemas`, `admin_capabilities` | 7 failed → 0 failed, 2 new negative tests | — | **VERIFIED** |
| Remaining 4 are environmental, not code | `uv run python -c "import importlib.util…find_spec('fastmcp')"` | 0 | `mcp/gateway.py:146` | `fastmcp spec: None` | fastmcp **is** declared and locked | **ENV_FAILURE** |
| `/mcp` is not actually served | control: `/mcp` vs `/definitely-not-a-real-path-xyz` | 0 | `app_factory._mount_mcp_http` | both `401`, 36 B, `{"detail":"Authentication required"}` | — | **VERIFIED (not mounted)** |
| S202 admin guard fails closed | new negative tests | 0 | `require_admin` via `request.state.auth` | 403 without admin context, 200 with | — | **VERIFIED** |
| FastMCP call signature in prod is valid | FastMCP docs (`http_app(path=…)`, `http_app(stateless_http=True)`) | — | `mcp/http_server.py:51` | matches real library API | — | **VERIFIED (external)** |
| `make ci` passes | `make ci` | 0 | — | 20754 collected, "CI gate passed" | markers checked individually | **VERIFIED** |
| MCP runtime behaviour with fastmcp present | cannot run | — | — | — | venv has 337 dists, lock has 4.0.3 | **NOT VERIFIED** |

## What was wrong

Eleven failing tests across three files, one root cause each. In every case the
**production code was the current, intended version** and the test was still
asserting a contract that had been deliberately replaced.

### 1. `test_http_transport.py` — 2 failures

- `_FakeMcp.http_app()` took no kwargs, but `http_server.py:51` calls
  `candidate(stateless_http=True, path="/")` (D-AUDIT-20812, cycle 218, which
  fixed a real Starlette `Mount` 404). The resulting `TypeError` was swallowed
  by `except Exception: continue`, surfacing as a `RuntimeError` that looked
  like a FastMCP problem. The real FastMCP signature was confirmed against
  vendor documentation rather than assumed. The test now also asserts the
  kwargs it forwards, not just "not None".
- The test patched private `_verify_api_key` / `_verify_jwt`, but S93 W3 moved
  the middleware onto the public `verify_request()`. The real verifiers ran,
  rejected the fake key, and the request got 401.

### 2. `test_workflow_tools.py` — 2 failures

- `mock_row.status` was a `MagicMock` unrelated to the members of the
  `terminal` set, so `row.status in terminal` was always `False`. Because
  `asyncio.sleep` is mocked, the poll loop **hot-spun on wall-clock for the
  full 300 s timeout** and then returned a dict with no `"result"` key →
  `KeyError`. This is the 301.92 s in the "before" column.
- `assert_not_called()` became false once `register_workflow_tools` also
  registered the catalog tools. The real intent — that `wf1` without a
  `route_id` is skipped — is now asserted directly.

### 3. `test_main.py` — 4 failures

`_mount_mcp_http` moved from `src.backend.main` to
`src.backend.plugins.composition.app_factory` (D-AUDIT-20807, cycle 216) and
now takes the app as an argument. All four tests still called
`main._mount_mcp_http()`. Two also passed a bare `MagicMock` where the
function unpacks a 2-tuple `(asgi_app, lifespan)`.

### 4. `test_admin_and_mcp.py` — 3 failures

Both admin routers gained `dependencies=[Depends(require_admin(...))]` in the
S202 audit fix. The tests built a bare `FastAPI()` with no auth and expected
200; the guard correctly returned 403.

**The guard was not weakened.** The tests now inject an admin `AuthContext`
through `request.state.auth` — the same channel `AuthRequiredMiddleware` uses
in production. Two negative tests were added that did not exist before: both
endpoints must return 403 without an admin context. The S202 guard had no
negative coverage.

## Before / after

| Scope | Before | After |
|---|---|---|
| `tests/unit/entrypoints/mcp` | 8 failed, 98 passed, 305.74 s | 4 failed, 102 passed, 1.75 s |
| `tests/unit/test_main.py` | 2 passed, 4 failed | 6 passed |
| `tests/smoke/test_admin_and_mcp.py` | 3 failed, 2 skipped | 5 passed, 2 skipped |
| Combined affected set | 15 failed | 4 failed, 113 passed |
| `make ci` | exit 0 | exit 0, collection 20752 → 20754 |

The 87× runtime drop is itself evidence: it is the removed 300 s hot-spin.

## The remaining 4 failures are environmental

`test_http_server_auth_wrap.py` fails with `ImportError: fastmcp is not
installed` from `mcp/gateway.py:146`.

- `fastmcp>=3.2.4` is declared in **two** extras: `mcp` (pyproject:241) and
  `dev-light` (pyproject:474). This workspace runs the `dev_light` profile.
- `uv.lock` pins **fastmcp 4.0.3** (uv.lock:2357).
- The venv holds 337 distributions and does not contain fastmcp.
- `make/setup.mk` prescribes `uv sync --all-extras`; this venv is stale.

So this is a venv/lockfile mismatch, not a code defect. Recorded as
`ENV_FAILURE` rather than papered over with a skip: the tests it guards verify
that the MCP HTTP app is wrapped in **auth middleware**, and a skip would hide
exactly that.

## `/mcp` is not served here — proved, not assumed

`GET /mcp` returns 401, which looks like a working auth-gated endpoint. A
control experiment shows it is not:

| path | status | bytes |
|---|---:|---:|
| `/mcp` | 401 | 36 |
| `/mcp/` | 401 | 36 |
| `/definitely-not-a-real-path-xyz` | 401 | 36 |
| `/nonexistent` | 401 | 36 |

All four are byte-identical `{"detail":"Authentication required"}`. The 401 is
a catch-all auth middleware and carries **no** information about the MCP route.

Two independent causes, either of which alone disables it:

1. `mcp_settings.http_enabled = False` in this profile — `app_factory.py:157`
   returns before ever attempting the mount.
2. `fastmcp` is not importable, so `create_mcp_http_app()` would raise anyway.

`mcp` does not appear in `openapi.json`, which is expected — MCP is JSON-RPC
over HTTP, not an OpenAPI operation.
