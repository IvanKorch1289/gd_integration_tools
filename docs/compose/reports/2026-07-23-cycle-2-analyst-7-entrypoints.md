# Cycle 2 — Analyst 7 (Entrypoints/middlewares/DSL routes) — Consolidated

**Status**: success

## P0 — Critical
1. **DSL Console public without auth** (`entrypoints/api/v1/endpoints/dsl_console.py:131-262`): `POST /dsl/execute-inline`, `/dsl/execute-registered`, `/dsl/dry-run` — **no auth guard, no rate limit**. `execute_inline` (L216-263) accepts arbitrary YAML and executes DSL processes.
2. **DSL Console exception leak** (`dsl_console.py:148,184,200`): `except Exception as exc: return InlineDSLResponse(status="error", error=str(exc))` — public endpoint returns raw `str(exc)`, leaks stack traces / internal paths.
3. **MCP namespace authz gap**: only `ai` namespace has per-tool authz (`mcp/namespaces/ai_mcp.py:78-100`). `analytics_mcp.py`, `credit_mcp.py`, `system_mcp.py` — no whitelist filter, expose all actions.
4. **WebSocket no Origin check** (`websocket/ws_handler.py:165-323`, `ws_invocations.py:50-51`): no `Origin` header validation — CSRF risk.
5. **gRPC servicer auth gap** (`entrypoints/grpc/auto_servicer.py:118`): wraps `dispatch_action` without any auth check; `AuthInterceptor` exists but not visibly applied.
6. **Path traversal in admin scaffold** (`admin_plugins.py:511-523`): `scaffold_plugin(body.name)` — `body.name` could be `../../etc/passwd`. Admin-only but RCE if exploited.
7. **Input size limit bypass** (`imports.py:34-75`, `files.py:75-102`): `await file.read()` directly — bypasses `request_body_cache.py:38-58` 10MB limit.
8. **request_body_cache warning then proceeds** (`request_body_cache.py:96-100`): logs warning but still caches body exceeding limit, allowing large-body memory pressure.

## P0 — Streaming/timeout
- `entrypoints/timeout.py:73` — `wait_for(call_next(request))` cancels streaming responses mid-flight
- `ai_stream.py:114-118` — no per-token timeout; 64-token response can exceed 30s timeout
- `admin_workflow_audit.py:107-202` and `admin_workflow_cost.py:167-181` — ClickHouse queries not wrapped in timeout

## P1 — OpenAPI drift
- `dsl_routes.py:284-289` `get_dsl_route_python` — orphan endpoint, response_model mismatch
- 8+ admin endpoints have `response_model=None` or wrong (imports, dadata, files, tech, health, admin_ip_restriction, admin_tenants)

## P1 — Error response leaks
- `dsl_console.py:148,184,200` — public endpoint returns `str(exc)` (HIGH risk)
- 5+ admin endpoints leak exception messages in `detail=`
- `auth_login.py:185` — **mock-jwt fallback** on JWT encoding failure (known anti-pattern)

## P1 — Rate limit missing
- `dsl_console.py:131-262` — public, no rate limit, can be hammered
- `admin_workflow_audit.py`, `admin_workflow_cost.py`, `admin_connector.py:132-175`, `admin_capabilities.py` — no per-route rate limit

## Verified clean
- No SQL injection (all parameterized)
- Exception handler does not leak to client
- WS auth on accept-then-check pattern
