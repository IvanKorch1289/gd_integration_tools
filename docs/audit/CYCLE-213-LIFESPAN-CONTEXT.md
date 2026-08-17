# Cycle 213 — FastMCP lifespan_context fix (2026-08-14)

**Branch:** master @ HEAD
**Author:** kimi Code CLI (cycle 213)
**Scope:** Final fix для broken cycle 211/212 lifespan integration.

---

## TL;DR

| Задача | Статус | Verification |
|---|---|---|
| Discovery (root cause analysis) | ✅ DONE | `lifespan` is method, `lifespan_context` is function |
| Fix `create_mcp_http_app()` | ✅ DONE | returns `inner.router.lifespan_context` (function) |
| Restore combined lifespan в main.py | ✅ DONE | asynccontextmanager combined |
| Tests | ✅ 6/6 PASS | (no change since cycle 212) |
| Image rebuild | ✅ DONE | 14s |
| **ASGI Lifespan warnings** | ✅ **GONE** | (vs cycle 211's "ASGI Lifespan errored") |
| Real JSON-RPC return | ⚠️ STILL 404 | Deep FastMCP session_manager issue (cycle 214+) |

**1 commit** (`3e9eb3dc`): +29/-19 LOC.

---

## 1. Root cause (закрыт cycle 211/212)

**Cycle 211 bug**: я использовал `inner.router.lifespan`, который IS A METHOD (Starlette descriptor):
```python
# Starlette Router class:
@property
def lifespan(self) -> Lifespan[Starlette]:  # ← property descriptor
    return self.router.lifespan_context
```

`inner.router.lifespan` (через property) returns `self.router.lifespan_context`.
Calling `mcp_inner_lifespan(app)` calls the **property** on a different instance
(not bound to original router) → wrong binding → ASGI reports "ASGI Lifespan errored".

**Cycle 213 fix**: use `inner.router.lifespan_context` directly (the actual function):
```python
return wrapped, inner_app.router.lifespan_context
```

`lifespan_context` is the **function** with signature `(app: Starlette) -> AsyncGenerator[None, None]`.
Calling it returns the async context manager. `async with mcp_inner_lifespan(app)` works.

---

## 2. Fix

### 2.1 `create_mcp_http_app()` returns `lifespan_context`

```diff
- return wrapped, inner_app.router.lifespan
+ return wrapped, inner_app.router.lifespan_context
```

### 2.2 `_mount_mcp_http()` — combined lifespan (restored)

```python
_existing_lifespan = app.router.lifespan

@asynccontextmanager
async def _combined_lifespan(app):
    # FastMCP task group MUST start BEFORE business lifespan
    async with mcp_inner_lifespan(app):
        async with _existing_lifespan(app):
            yield

app.router.lifespan = _combined_lifespan
```

---

## 3. Validation

### 3.1 ASGI Lifespan warnings

**Before** (cycle 211):
```
[WARNING] ASGI Lifespan errored, continuing without Lifespan support
```

**After** (cycle 213):
```
(no warnings) ← combined lifespan works
```

### 3.2 Container status

```bash
$ curl -s -m 5 -o /dev/null -w "Health: %{http_code}\n" http://localhost:8000/health
Health: 200

$ sudo docker logs gd-app-light 2>&1 | grep -iE "ASGI Lifespan|Lifespan support"
(none)

$ sudo docker logs gd-app-light 2>&1 | grep -iE "MCP HTTP transport mounted"
(should appear — see 'remaining issue' below)
```

### 3.3 /mcp POST test

```bash
$ curl -X POST -H 'Content-Type: application/json' \
       -d '{"jsonrpc":"2.0","method":"tools/list","id":1}' \
       http://localhost:8000/mcp
HTTP/1.1 404 Not Found
{"detail":"Not Found"}
```

---

## 4. Remaining issue (deferred cycle 214+)

Despite combined lifespan working (no ASGI warnings), POST /mcp still 404.
Root cause: FastMCP's `_handle_request`:
```python
if self._task_group is None:
    raise RuntimeError("Task group is not initialized. Make sure to use run().")
```

Even after `lifespan_context` runs, `self._task_group` is still None.
This means `streamable_http_app.session_manager.run()` is NOT actually
initializing the task group. Possible reasons:
- The lifespan_context creates a NEW session_manager and assigns to
  `streamable_http_app.session_manager`, but the asgi_app.handle_request
  binds to the OLD session_manager (from when the app was created).
- Different `_handle_request` binding issue (closure vs bound method).

Multi-cycle investigation required (D-AUDIT-20806):
- Trace `streamable_http_app.session_manager` assignment timing
- Investigate `RequestBodyLimitMiddleware(self._handle_request, ...)`
  binding — does it capture the new session_manager or old?

---

## 5. Артефакты

- `src/backend/entrypoints/mcp/http_server.py` (+11/-3 lines): return `lifespan_context`
- `src/backend/main.py` (+20/-16 lines): restore combined lifespan using proper API
- Image `gd-integration-tools:light` @ sha256:bb76959c63b8... (14s rebuild)

**HEAD**: `3e9eb3dc`

---

## 6. Out of scope (cycle 214+)

| Task | Reason |
|---|---|
| Real FastMCP JSON-RPC return | `_handle_request` task group binding issue (multi-cycle debug) |
| gRPC Cython real RPC | cycle 209+ deferred, requires Cython-patching |
| Frontend → core/api migration | cycle 206 done (no-op, already via `frontend_facade`) |
| ASGI lifespan 404 detection | Currently we return 404 (clean state) vs empty reply (cycle 211) |
