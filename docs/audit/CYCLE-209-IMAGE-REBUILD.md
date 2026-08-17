# Cycle 209 — image rebuild + NEW-3 partial fix (2026-08-14)

**Branch:** master @ HEAD
**Author:** kimi Code CLI (cycle 209)
**Scope:** cycle 207c (NEW-3) + cycle 208 deferred (image rebuild required).

---

## TL;DR

| Задача | Статус |
|---|---|
| Image rebuild с cycle 202 patches + fastmcp | ✅ DONE (3.5 мин build) |
| NEW-3 (MCP /mcp mount) | ⚠️ PARTIAL — mount работает (307), routing требует follow-up |
| Real gRPC RPC | ⚠️ DEFERRED — cycle 202 patches недостаточны для gRPC Cython |

**1 коммит** (`d081210f`): +11/-6 LOC (pyproject.toml + compose config).

---

## 1. Image rebuild (3.5 мин)

```text
$ sudo docker build -f ops/compose/Dockerfile -t gd-integration-tools:light .
#31 exporting layers 20.7s done
#31 writing image sha256:9c14b2cb951741b0439bdb5baefe77b18f6965ab74f1eb3e309317d668c90d7c done
```

Image теперь содержит:
- ✅ Все мои source-code patches (cycles 201-208) через `COPY .` на build
- ✅ fastmcp 3.4.5 (NEW-3 prerequisite)
- ✅ Cycle 202 patches активны (verified `request_streaming=False` on
  OrderServiceServicer.CreateOrder и OrderGRPCServicer.CreateOrder)

---

## 2. NEW-3 / MCP (PARTIAL FIX)

### 2.1 Configuration changes

```diff
# pyproject.toml
[project.optional-dependencies]
dev-light = [
    "aiosqlite>=0.20.0,<1.0.0",
+   # D-AUDIT-20803 (cycle 209): fastmcp в dev-light
+   "fastmcp>=3.2.4",
]
```

```diff
# ops/compose/docker-compose.light.yml
environment:
  APP_PROFILE: dev_light
  APP_SERVER: ${APP_SERVER:-granian}
  APP_WORKERS: ${APP_WORKERS:-2}
+ # D-AUDIT-20803 (cycle 209): MCP HTTP transport enable
+ MCP_HTTP_ENABLED: ${MCP_HTTP_ENABLED:-true}
```

### 2.2 Functional verification

| Endpoint | Before cycle 209 | After cycle 209 |
|---|---|---|
| `POST /mcp` (JSON-RPC) | `52 Empty reply` / curl error | `307 Temporary Redirect → /mcp/` |
| `GET /mcp/` (Accept: text/event-stream) | `404 Not Found` (fastmcp not installed) | `404 Not Found` (mount exists, route mismatch) |
| `GET /openapi.json` (paths: /mcp) | `False` (0 MCP paths) | `False` (out of OpenAPI — ASGI mount, not FastAPI route) |

**Improvement**: `/mcp` mount теперь достижим (307 → /mcp/). **Remaining
issue**: 307 redirect lands on `/mcp/` (trailing slash), но FastMCP 3.x
route ТОЛЬКО `/mcp` (точно). curl + `-L` повторяет POST на /mcp/ → 404.

### 2.3 Remaining routing issue (deferred cycle 210+)

```text
$ sudo docker exec gd-app-light python -c "
from src.backend.entrypoints.mcp.http_server import _resolve_http_app
from fastmcp import FastMCP
mcp = FastMCP('test')
asgi = _resolve_http_app(mcp)
print([route.path for route in asgi.routes])
"

['/mcp']   ← FastMCP expects EXACT /mcp
```

**Root cause**: Starlette's `Mount` adds trailing-slash redirect logic
(по умолчанию `redirect_slashes=True`). `/mcp` (without slash)
redirects to `/mcp/`. FastMCP's StreamableHTTPASGIApp handles only
`/mcp` (no slash).

**Fix candidates** (deferred):
- A. Wrap Mount с custom subapp, который sets `redirect_slashes=False`
- B. Override FastMCP route для также handle `/mcp/`
- C. Set `bind_path="/mcp/"` (теперь mount = expected path) — но
  upstream callers expect `/mcp`
- D. Add proxy middleware to strip trailing slash

Per Ponytail: minimal atomic fix в следующий cycle.

---

## 3. Real gRPC RPC (DEFERRED — deeper gRPC issue)

### 3.1 Functional test (cycle 209)

```python
$ sudo docker exec gd-grpc-light python -c "
import asyncio, grpc
import src.backend.entrypoints.grpc.grpc_server  # package init → patches
from src.backend.entrypoints.grpc.protobuf import orders_pb2, orders_pb2_grpc

async def main():
    async with grpc.aio.insecure_channel('unix:///tmp/order_service.sock') as ch:
        stub = orders_pb2_grpc.OrderServiceStub(ch)
        try:
            r = await stub.CreateOrder(orders_pb2.CreateOrderRequest(order_id=12345), timeout=5)
            print(f'OK: {r}')
        except grpc.aio.AioRpcError as e:
            print(f'⚠️ code={e.code()} details={e.details()[:100]}')

asyncio.run(main())
"

⚠️ code=StatusCode.UNKNOWN 
    details=Unexpected <class 'AttributeError'>:
        'function' object has no attribute 'request_streaming'
```

### 3.2 Root cause (deeper than cycle 202 surface fix)

Cycle 202 patches:
```python
_method.request_streaming = False  # type: ignore[attr-defined]
```

**Verified applied**: Python-level introspection shows `request_streaming=False`
на `OrderServiceServicer.CreateOrder` (parent) и `OrderGRPCServicer.CreateOrder` (subclass).

**However, gRPC Cython uses DIFFERENT code path**:
- Look at `grpc/_server.py:1042` (sync server) и analogous code в `grpc.aio`:
- `if method_handler.request_streaming:` — check на **method_handler**,
  а не на **function**

`method_handler` — internal object created by `add_*Servicer_to_server()`.
Cycle 202 patches не достают method_handler (он генерится внутри
gRPC internals из class methods).

Per Ponytail: deeper investigation beyond cycle 209 scope. Deferred.

### 3.3 Plan для cycle 210+

Требуется Cython-level patching OR grpcio downgrade до версии
до этой regression. Cycle 200 уже пытался 1.83 → 1.78 (без эффекта).

---

## 4. Container status (post-rebuild)

| Container | Status |
|---|---|
| gd-app-light | Up (healthy) ✅ |
| gd-grpc-light | Up (healthy) ✅ |
| compose-workflow-worker-{4,5,6,7} | Up (healthy, cycle 207 fix stable) ✅ |
| compose-postgres-1, compose-redis-1, compose-clamav-1 | Up (healthy) ✅ |

---

## 5. Артефакты cycle 209

- `pyproject.toml` (+3 lines): fastmcp added to `[dev-light]`
- `ops/compose/docker-compose.light.yml` (+8/-6 lines): MCP_HTTP_ENABLED
- `uv.lock` (regenerated)
- Image rebuild (`gd-integration-tools:light` 9c14b2cb...)

**HEAD**: `d081210f`

**Out of scope (cycle 210+)**:
- MCP routing 307→/mcp/→404 fix (disable redirect_slashes или FastMCP routing config)
- Real gRPC RPC end-to-end (requires gRPC Cython-patching или grpcio downgrade)
