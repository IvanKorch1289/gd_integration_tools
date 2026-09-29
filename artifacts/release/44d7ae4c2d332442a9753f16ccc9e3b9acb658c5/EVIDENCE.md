# Evidence — `44d7ae4c2` (fastmcp installed; MCP surface verified)

Measured after the change landed. `ENV_FAILURE` from the previous entry is
resolved; the MCP surface moves from *not served* to *mounted and verified*,
with one honest gap recorded.

## What changed in the environment

`fastmcp==4.0.3` installed with `uv pip install "fastmcp==4.0.3"` — the exact
version `uv.lock` pins (uv.lock:2357). Deliberately **not** `uv sync
--all-extras`: that would prune and rewrite the whole venv, and the decision
was to avoid mutating the environment beyond the one missing library.

Installing it also confirmed the diagnosis rather than assuming it — the four
`test_http_server_auth_wrap.py` tests went from `ImportError: fastmcp is not
installed` to passing with no code change of their own.

## Claim ledger

| Claim | Evidence command | Exit | Code path | Runtime/test | Counterevidence | Status |
|---|---|---:|---|---|---|---|
| MCP cluster fully green | `pytest tests/unit/entrypoints/mcp -q` | 0 | `entrypoints/mcp/*` | `106 passed, 1 xfailed, 0 failed` | — | **VERIFIED** |
| `/mcp` is mounted in the live app | in-process `app.routes` inspection | 0 | `app_factory._mount_mcp_http` | `MCP mounts in live app.routes: ['/mcp']` | — | **VERIFIED** |
| ASGI chain is correct | in-process chain walk | 0 | `mcp/auth_middleware.py` | `McpAuthMiddleware -> StarletteWithLifespan` | — | **VERIFIED** |
| Inner path matches D-AUDIT-20812 | in-process route listing | 0 | `mcp/http_server.py:51` | `inner FastMCP routes: ['/']` | — | **VERIFIED** |
| No regression from the install | 9 entrypoints clusters | 0 | — | grpc 66, api 338, mcp 106, middlewares 575, websocket 65, scheduler 15, sse 36, stream 16, webhook 12 — all green | — | **VERIFIED** |
| `make ci` passes | `make ci` | 0 | — | 20758 collected, "CI gate passed" | 10 markers, all benign as before | **VERIFIED** |
| A green test was green for the wrong reason | `patch(..., side_effect=ImportError)` analysis | 0 | `tests/unit/test_main.py` | `from ... import` binds a name, never calls the mock | — | **VERIFIED** |
| Authenticated MCP round-trip | needs a credential | — | — | — | Redis auth not configured; creating credentials unprompted | **NOT VERIFIED** |

## Two more stale tests, revealed by the install

Installing the library made two previously-unrunnable tests execute, and both
failed. Neither pointed at a code defect.

### `test_mount_mcp_http_skipped_on_import_error` was passing for the wrong reason

The test intended to simulate `mcp_settings` failing to import:

```python
patch("src.backend.core.config.ai_stack.mcp_settings", side_effect=ImportError)
```

`side_effect` fires only when the mock is **called**. The production code does
`from src.backend.core.config.ai_stack import mcp_settings`, which merely binds
a name — so **no ImportError was ever raised**. The test went green purely
because `create_mcp_http_app()` happened to fail for an unrelated reason
(fastmcp missing) and a broad `except` skipped the mount.

It now uses `patch.dict("sys.modules", {..., None})`, which makes the import
genuinely raise, so the intended path is actually exercised.

This is the most important finding in this entry: a test that asserted the
right thing was verifying nothing, and it would have kept passing in CI where
fastmcp *is* installed, for the same wrong reason.

### `test_mcp_http_app_routes_exist` read the wrong object

Previously skipped by `importorskip("fastmcp")`. It read `app.routes` off the
return of `create_mcp_http_app()`, but S49 W1 made that return
`McpAuthMiddleware` wrapping the FastMCP ASGI app — the routes are on the
inner app. It then expected `/tools` or `/mcp`, which predates the
D-AUDIT-20812 fix that deliberately sets the inner path to `/` so that
Starlette `Mount` re-rooting matches. It now asserts what the code intends,
and the live app confirms it: `inner FastMCP routes: ['/']`.

## The MCP surface, before and after

Before, at `3fa6cd206`: `mcp_settings.http_enabled` was `False`, and
`create_mcp_http_app()` would have raised anyway. `GET /mcp` returned 401 —
but so did `/definitely-not-a-real-path-xyz`, byte for byte, so that 401 was a
catch-all auth middleware and carried no information.

After, at `44d7ae4c2`, with `MCP_HTTP_ENABLED=true`:

```
D-AUDIT-20810 mcp_settings: http_enabled=True, bind_path=/mcp
D-AUDIT-20810 create_mcp_http_app() returned: McpAuthMiddleware
D-AUDIT-20810 app.mount done at /mcp

MCP mounts in live app.routes: ['/mcp']
ASGI chain under /mcp: McpAuthMiddleware -> StarletteWithLifespan
inner FastMCP routes: ['/']
```

`/mcp` is genuinely mounted, wrapped in the MCP auth middleware, and its inner
route matches the D-AUDIT-20812 contract.

**The honest gap:** `GET /mcp` still returns 401, because the *outer*
`AuthRequiredMiddleware` intercepts before `McpAuthMiddleware` ever runs. An
unauthenticated request therefore still cannot distinguish a working MCP route
from an absent one — that is a property of the auth stack, not a defect. A full
protocol round-trip (`initialize` / `tools/list` over JSON-RPC) would need a
valid API key. Redis is reachable but not configured for auth here, and
minting credentials is not something to do unprompted, so that round-trip is
recorded as **NOT VERIFIED** rather than assumed.

## No regression

All 9 entrypoints clusters re-measured after the install, each run separately
to stay under the RAM ceiling: grpc 66, api 338, mcp 106, middlewares 575,
websocket 65, scheduler 15, sse 36, stream 16, webhook 12 — every one green.
Collection rose 20754 → 20758 because the two `importorskip`-gated tests now
execute.
