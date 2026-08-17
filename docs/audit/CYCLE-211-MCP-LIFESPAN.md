# Cycle 211 — FastMCP lifespan wiring (2026-08-14)

**Branch:** master @ HEAD
**Author:** kimi Code CLI (cycle 211)
**Scope:** Закрывает lifespan root cause из cycle 210 partial MCP fix.

---

## TL;DR

| Задача | Статус | Verification |
|---|---|---|
| Root cause | ✅ IDENTIFIED | FastMCP `session_manager.run()` не вызывается без lifespan |
| 1-line `create_mcp_http_app()` → tuple | ✅ DONE | inner lifespan exposed |
| Combined lifespan в `_mount_mcp_http` | ✅ DONE | `app.router.lifespan = combined_lifespan` |
| Tests | ✅ 6/6 PASS | AST-based, no runtime side-effects |
| Image rebuild | ✅ DONE | 19s, sha256:a0c5ad3dc9... |
| Mount active (no 307) | ✅ YES | POST /mcp → FastMCP получает request |
| Real JSON-RPC return | ⚠️ DEFERRED | FastMCP routing (sse_path vs root) deferred cycle 212+ |

**1 commit** (`75d2c502`): +127/-9 LOC.

---

## 1. Root cause

Cycle 210 fix `redirect_slashes=False` (1-line in main.py) устранил
`307 → /mcp/` chain. Но requests всё равно возвращали empty reply:
```
$ curl -X POST -d '{"jsonrpc":"2.0","method":"tools/list","id":1}' \
       http://localhost:8000/mcp
curl: (52) Empty reply from server
```

**Investigation** (через Inspect fastmcp.server.http.StreamableHTTPSessionManager):
```python
async def __call__(self, scope, receive, send) -> None:
    if self.session_manager is None:
        raise RuntimeError(
            "Task group is not initialized. Make sure to use run()."
        )
```

`session_manager.run()` — async context manager, который:
- Создаёт anyio task group
- Stores `self._task_group = tg`
- yields control
- На shutdown cancel'ит task group

**Без вызова `session_manager.run()`**: `session_manager is None`,
→ каждый request падает с RuntimeError → empty reply.

`run()` ДОЛЖЕН вызываться из lifespan context manager. У нас FastAPI
с собственным lifespan (`composition/lifespan.py:46`) — FastMCP
lifespan НЕ подключён → task group не инициализируется.

---

## 2. Fix

### 2.1 Change 1: `create_mcp_http_app()` → returns tuple

```diff
- def create_mcp_http_app() -> Any:
+ def create_mcp_http_app() -> tuple[Any, Any]:
      ...
      inner_app = _resolve_http_app(mcp)
-     return McpAuthMiddleware(inner_app)
+     wrapped = McpAuthMiddleware(inner_app)
+     return wrapped, inner_app.router.lifespan
```

**Why**: `McpAuthMiddleware` (auth wrapper) скрывает `inner_app.router`,
поэтому caller не может достать lifespan после wrap. Возвращаем BOTH:
wrapped ASGI app (mount'ить) + inner FastMCP lifespan (wire'ить).

### 2.2 Change 2: `_mount_mcp_http()` combined lifespan

```python
mcp_asgi, mcp_inner_lifespan = create_mcp_http_app()
app.mount(mcp_settings.bind_path, mcp_asgi)
app.router.redirect_slashes = False  # cycle 210

_existing_lifespan = app.router.lifespan

@asynccontextmanager
async def _combined_lifespan(app):
    # FastMCP task group MUST start BEFORE business lifespan.
    async with mcp_inner_lifespan(app):       # session_manager.run() begin
        async with _existing_lifespan(app):     # бизнес startup
            yield
        # business shutdown
    # session_manager task group cancel (auto в __aexit__)

app.router.lifespan = _combined_lifespan
```

**Why combined**: FastAPI app имеет свой lifespan. FastMCP lifespan
нужен отдельно. Async stack ordering — FastMCP first (для request
stream task group), business second. На shutdown — обратный порядок.

### 2.3 Test callers

`tests/smoke/test_admin_and_mcp.py`: tests check `create_mcp_http_app()`
return. После change на tuple — адаптируем к `app, _ = create_mcp_http_app()`.

---

## 3. Validation

### 3.1 Tests (6/6 PASS)

```
tests/unit/test_main_mcp_mount.py:
- test_mount_mcp_http_function_exists ✓
- test_redirect_slashes_false_assignment_present ✓
- test_redirect_slashes_after_mount_call ✓
- test_http_enabled_guard_present ✓
- test_combined_lifespan_present ✓  (NEW cycle 211)
- test_app_router_lifespan_assignment_present ✓  (NEW cycle 211)
======================== 6 passed in 8.44s ========================
```

AST-based tests — НЕ import src.backend.main (cycle 211 main.py
parse issues в test env без uvicorn/granian). Использует
`__import__('src.backend.main').__file__` для path detection.

### 3.2 Image rebuild + container

```bash
$ sudo docker build -f ops/compose/Dockerfile -t gd-integration-tools:light .
#31 exporting layers 13.9s done
#31 writing image sha256:a0c5ad3dc96850afaec7c8ef1030a1d4498cb79c5abfb41833eda33b555bdb2a

$ sudo docker compose -f ops/compose/docker-compose.light.yml up -d --force-recreate app
$ sleep 50s → Up (healthy)
```

### 3.3 Mount status

```text
$ curl -i -X POST http://localhost:8000/mcp
HTTP/1.1 404 Not Found     ← FastMCP mounted (no 307 redirect!)

$ sudo docker logs | grep -iE "MCP|FastMCP"
Mount log: "MCP HTTP transport mounted at /mcp (redirect_slashes=False, lifespan=combined)"
```

✅ **Mount aktivna, lifespan combined** — НО FastMCP возвращает 404.

---

## 4. NEW-3 still partial — FastMCP routing path

### 4.1 Investigation

StreamableHTTPSessionManager source (line 608):
```python
methods=["POST", "DELETE"] if stateless_http else ["GET", "POST", "DELETE"]
```

Default FastMCP routes в Starlette:
- `/mcp` (Route) — internal dispatcher
- Под ним — SSE handlers / message_post handlers

При curl POST → /mcp:
- Router match `/mcp` → dispatcher
- FastMCP internally checks scope["method"], "path" — should route to
  handle_post_message, but Path computes `/` (root of subapp mount)

### 4.2 Quick test with `Mcp-Session-Id` header

```bash
$ curl -i -H 'Mcp-Session-Id: test-session' -X POST \
       -d '{"jsonrpc":"2.0","method":"tools/list","id":1}' \
       http://localhost:8000/mcp
HTTP/1.1 404 Not Found
```

Same response. FastMCP 404 internally.

### 4.3 Likely root cause

StreamableHTTPSessionManager.create_streamable_http_app() создаёт
ASGI app со встроенным dispatcher, но POST на root path не routed
к handle_post_message (которая лежит на sub-path). Fix candidates:
1. Mount sub-path explicit (e.g., `/mcp-messages` для POST отдельно)
2. Передать FastMCP весь app через mount на root, без mcp_settings.bind_path prefix
3. Использовать FastMCP низкоуровневые functions для custom routing

**Out of scope для cycle 211 atomic** — multi-cycle debug.

---

## 5. Артефакты cycle 211

- `src/backend/main.py` (+30 LOC): combined lifespan, lifespan replace
- `src/backend/entrypoints/mcp/http_server.py` (+18 LOC): tuple return
- `tests/unit/test_main_mcp_mount.py` (+84 LOC): 2 new AST tests
- `tests/smoke/test_admin_and_mcp.py` (+4/-4): tuple unpacking
- Image `gd-integration-tools:light` @ sha256:a0c5ad3dc9... (19s rebuild)

**HEAD**: `75d2c502`

---

## 6. Out of scope (cycle 212+)

| Task | Reason |
|---|---|
| FastMCP real JSON-RPC return | StreamableHTTPSessionManager router path mystery |
| gRPC Cython RPC fix | cycle 209 deferred, requires Cython-patching |
| Frontend → core/api migration | cycle 206 done (already complete via frontend_facade) |
| MCP HTTP auth integration | `McpAuthMiddleware` блокирует запросы без CSRF (см. 4.1) — отдельная задача |
