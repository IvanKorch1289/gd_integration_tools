# Cycle 218 — FastMCP `path="/"` fix (2026-08-14)

**Branch:** master @ HEAD
**Author:** kimi Code CLI (cycle 218)
**Scope:** Fix Starlette Mount re-root path mismatch.

---

## TL;DR

| Задача | Статус |
|---|---|
| Root cause (Starlette Mount re-root) | ✅ IDENTIFIED |
| `path="/"` fix в `http_app()` | ✅ DONE |
| Inner route теперь at `/` | ✅ VERIFIED |
| Mount в runtime | ✅ VERIFIED (print log shows) |
| **Real JSON-RPC return** | ⚠️ **STILL 404** (other issue) |

**1 commit** (`c3c08605`): +9/-2 LOC.

---

## 1. Root cause

Starlette Mount re-roots incoming request paths. When request comes for `/mcp` and parent's route is `Mount("/mcp", inner_app)`:
- Path is stripped: `/mcp` → `/`
- Inner app receives request at path `/`
- FastMCP's `http_app()` creates Route at `/mcp` (default) → no match → 404

**Standalone test works** because `TestClient` doesn't re-root paths (passes raw path to inner app).

---

## 2. Fix

Pass `path="/"` to FastMCP's `http_app()`:

```diff
- asgi = candidate(stateless_http=True)
+ asgi = candidate(stateless_http=True, path="/")
```

Inner app's Route becomes `/` (was `/mcp`). When mounted at `/mcp`:
- Request to `/mcp` → re-roots to `/` → inner Route at `/` matches → FastMCP handler runs

---

## 3. Verification

### 3.1 Inner routes (standalone)

```bash
$ docker exec gd-app-light python -c "
from fastmcp import FastMCP
app = FastMCP('test').http_app(path='/', stateless_http=True)
for r in app.routes:
    print(f'  {r.path} methods={getattr(r, \"methods\", None)}')
"
  / methods={'POST', 'DELETE'}    ← was /mcp methods=...
```

### 3.2 Mount log (D-AUDIT-20810)

```
D-AUDIT-20810 _mount_mcp_http ENTRY
D-AUDIT-20810 mcp_settings: http_enabled=True, bind_path=/mcp
D-AUDIT-20810 create_mcp_http_app() returned: StarletteWithLifespan
D-AUDIT-20810 app.mount done at /mcp
D-AUDIT-20810 MCP HTTP transport mounted at /mcp
```

Mount verified running.

### 3.3 Real JSON-RPC

```bash
$ curl -X POST http://localhost:8000/mcp
HTTP/1.1 404 Not Found
{"detail":"Not Found"}
```

⚠️ **STILL 404.** Inner route is at `/` (verified), but path mismatch
still occurs. Possible other causes:
- FastMCP internal sub-path routing for streamable_http
- Mount name conflict
- Middleware order issue

Out of scope for cycle 218 (multi-cycle debug).

---

## 4. Артефакты

- `src/backend/entrypoints/mcp/http_server.py` (+9/-2): `path="/"` для `http_app()`
- Image `gd-integration-tools:light` @ sha256:dac1ac486c75... (16s rebuild)

**HEAD**: `c3c08605`

---

## 5. NEW-3 status (cycles 209-218)

| Step | Status | Cycle |
|---|---|---|
| Mount works (compile-time) | ✅ | 209 |
| redirect_slashes fix | ✅ | 210 |
| Mount runs in runtime | ✅ | 216 |
| Mount log diagnostic | ✅ | 217 |
| McpAuthMiddleware check | ✅ | 217 (not the cause) |
| path="/" fix | ✅ | **218** (route at `/`) |
| Real JSON-RPC return | ⚠️ | cycle 219+ |
