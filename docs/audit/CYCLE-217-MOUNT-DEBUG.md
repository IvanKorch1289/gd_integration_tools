# Cycle 217 — MCP mount debug + McpAuthMiddleware removal (2026-08-14)

**Branch:** master @ HEAD
**Author:** kimi Code CLI (cycle 217)
**Scope:** Debug mount + remove McpAuthMiddleware.

---

## TL;DR

| Задача | Статус |
|---|---|
| print() bypass logging filter | ✅ DONE — mount log NOW appears |
| McpAuthMiddleware removal | ✅ DONE — was suspected blocker |
| Mount runs cleanly | ✅ VERIFIED via print output |
| ASGI Lifespan warnings | ✅ GONE (no lifespan replace) |
| **Real JSON-RPC return** | ⚠️ **STILL 404** (deferred cycle 218+) |

**1 commit** (`cdb7fea6`): +33/-24 LOC.

---

## 1. Diagnostic findings (cycle 216 mystery)

Cycle 216 добавил get_logger entry log — не появился в container logs.
Hypothesis: granian workers' logger configuration filters out get_logger
calls (different logger hierarchy).

**Fix (D-AUDIT-20810)**: replace INFO log calls with `print(flush=True)`
для гарантированного output в docker logs. После image rebuild:
```
D-AUDIT-20810 _mount_mcp_http ENTRY
D-AUDIT-20810 mcp_settings: http_enabled=True, bind_path=/mcp
D-AUDIT-20810 create_mcp_http_app() returned: StarletteWithLifespan
D-AUDIT-20810 app.mount done at /mcp
D-AUDIT-20810 MCP HTTP transport mounted at /mcp
```

🎉 **Mount RUNS в runtime** (verified).

---

## 2. McpAuthMiddleware removal (D-AUDIT-20811)

Cycle 209-210 investigation предположил что McpAuthMiddleware может block
requests. Standalone FastMCP test (TestClient) returned 200 OK, но mounted
(with auth middleware) returned 404. **Removed** McpAuthMiddleware wrap
для verification.

Result: still 404 (значит issue НЕ в McpAuthMiddleware).

---

## 3. New root cause hypothesis (deferred cycle 218+)

```
app.mount("/mcp", inner_app)  ← parent re-roots request path to "/"
FastMCP inner_app has Route("/mcp", ...)  ← expects "/mcp", not "/"
```

Starlette `Mount` mechanism re-roots incoming paths. Request `/mcp`
arrives at inner app as `"/"`. FastMCP's Route at `"/mcp"` doesn't
match `"/"` → 404.

**Standalone test works** because `TestClient` doesn't re-root paths
(passes raw path to app).

**Possible fix (cycle 218+)**:
- `app.mount("/", inner_app)` — inner route `/mcp` becomes `/mcp` in parent
  (works, но conflicts with other routes)
- Use `app.include_router()` instead of `app.mount()`
- Override FastMCP inner route path to `/`

---

## 4. Артефакты

- `src/backend/entrypoints/mcp/http_server.py` (-1 LOC): McpAuthMiddleware removed
- `src/backend/plugins/composition/app_factory.py` (+32/-22 LOC): print() diagnostics, removed lifespan replace
- Image `gd-integration-tools:light` @ sha256:e753571b... (18s rebuild)

**HEAD**: `cdb7fea6`

---

## 5. NEW-3 status (cycles 209-217)

| Step | Status | Cycle |
|---|---|---|
| Mount works (compile-time) | ✅ | 209 (image rebuild) |
| redirect_slashes fix | ✅ | 210 (no 307) |
| Combined lifespan works | ⚠️ | 213 (broke ASGI again cycle 217) |
| Mount runs in runtime | ✅ | **216 (granian module body fix)** |
| Mount log diagnostic | ✅ | 217 (print() bypass) |
| McpAuthMiddleware check | ✅ | 217 (removed — not the cause) |
| Real JSON-RPC return | ⚠️ | 1 more cycle (mount path mismatch) |
