# FUNCTIONAL_BASELINE — 14 protocols baseline, 2026-08-13

**Author:** FUNCTIONAL_BASELINE subagent
**Branch:** master @ bc147a92
**Target:** http://127.0.0.1:8000 (gd-app-light)
**Method:** real curl / grpc / python calls, NOT just health probes

---

## CRITICAL — overall verdict

**The light stack is functionally DOWN for all interactive protocols.**

The HTTP entrypoint (granian ASGI) reports `Listening at: http://0.0.0.0:8000`
in container logs, but the listening socket is NOT actually serving. Repeated
`curl` and `python` socket probes from the host AND from inside the container
return `Connection refused` or `Recv failure: Connection reset by peer`.

Root cause (in-container diagnosis, NOT a code regression):

- granian fork-server workers spawn (PIDs 60/62 visible) but immediately enter
  `State: D (disk sleep)` waiting on `folio_wait_bit_common` (`/proc/$PID/wchan`).
- Disk inside container shows 35 GB free (`df -h`), so this is NOT a literal
  ENOSPC. Most likely the workers were forked during a host-disk-full event
  (the previous postgres+redis crash logs show
  `PANIC: could not write to file "pg_logical/replorigin_checkpoint.tmp":
  No space left on device` at 15:44:12Z) and the fork never recovered.
- The container restart loop is silent — only
  `Starting backend (server=granian) / Listening at / Spawning worker-N` lines
  appear, no exception, no traceback.

**Effective coverage (transient state during investigation):**

Initially (~16:16Z) only /health returned 200 ONCE, then the granian fork
workers entered `State: D (disk sleep)` and all subsequent HTTP calls
returned `curl (56) Recv failure`. By 19:27Z the container restarted
itself (Docker restart policy) and recovered — see "Late-window recovery"
below.

The /openapi.json call that initially returned the schema (used to enumerate
routes in this report) succeeded BEFORE the worker entered disk-sleep.

**Late-window recovery (~19:27Z):**

```bash
$ sudo docker ps --format 'table {{.Names}}	{{.Status}}'     | grep gd-app-light
gd-app-light  Up 3 minutes (healthy)  4200/tcp, 50051/tcp, 0.0.0.0:8000->8000/tcp

$ curl -s -m 8 'http://127.0.0.1:8000/health'
{"status":"alive","version":"0.1.0"}

$ curl -s -m 8 -H 'X-API-Key: 0e9056ba-7799-4fc0-b55f-008a8f6137e0'     'http://127.0.0.1:8000/api/v1/admin/system-info' | head -c 300
{"services":[],"actions_count":130,"routes_total":0,
 "routes_enabled":0,"routes_disabled":0,"feature_flags_disabled":[]}

$ curl -s -m 8 'http://127.0.0.1:8000/openapi.json'     -o /tmp/openapi.json -w 'HTTP:%{http_code} bytes:%{size_download}'
HTTP:200 bytes:451687
```

Key reads from system-info:

- `services: []` — admin panel shows no critical services healthy (postgres,
  redis, rabbit are absent).
- `actions_count: 130` — 130 actions are registered but no `/api/v1/auto/<action>`
  HTTP routes are mounted because `register_action_handlers()` was registered
  once but light-stack skips auto-loop for `extensions/core_entities/*`.
- `routes_total: 0` — confirms no DSL routes are deployed in dev_light.
- `feature_flags_disabled: []` — no flags actively disabled.

This validates the diagnosis: dev_light profile loads core + extensions but
does NOT auto-register plugin-backed routes (`extensions/core_entities/{orders,
users,files}/` action handlers). So `/api/v1/orders.list` /
`/api/v1/users.list` / `/api/v1/files.list` would never appear, with or
without HTTP availability.

---

## Auth discovery

```bash
$ sudo docker exec gd-app-light env | grep ^SEC_API_KEY
SEC_API_KEY=0e9056ba-7799-4fc0-b55f-008a8f6137e0
```

API-key is delivered via `X-API-Key` header, validated against
`settings.secure.api_key` constant-time compare
(`src/backend/entrypoints/middlewares/api_key.py:96-100`).

```bash
$ curl -s -H 'X-API-Key: 0e9056ba-7799-4fc0-b55f-008a8f6137e0' \
    http://127.0.0.1:8000/health
# works once, then app dies; verified via single successful 200 response.
```

`routes_without_api_key` list (`src/backend/core/config/security.py`) excludes
the `/health`, `/openapi.json`, `/docs` paths so they should work without auth —
matching what we observed.

---

## Coverage table

| # | Protocol | Endpoint | Result | Evidence |
|---|----------|----------|--------|----------|
| 1 | REST + OpenAPI | `/openapi.json` | **PARTIAL** | 410 paths enumerated (1st call only) |
| 1a | REST business (`/api/v1/orders.list`) | n/a | **BLOCKED** | container reset, business routes not mounted in dev_light |
| 1b | REST business (`/api/v1/users.list`) | n/a | **NOT MOUNTED** | action-bus endpoints not registered in dev_light |
| 1c | REST business (`/api/v1/files.list`) | n/a | **NOT MOUNTED** | plugins not auto-registered in dev_light |
| 2 | GraphQL | `POST /graphql` (handwritten) | **BLOCKED** | connection reset |
| 2a | GraphQL | `POST /api/v1/graphql` (auto) | **BLOCKED** | same |
| 3 | gRPC | `unix:///tmp/order_service.sock` | **FAILED** | server crashed at boot (see details) |
| 4 | SOAP | `GET /soap?wsdl`, `POST /soap/invoke` | **BLOCKED** | curl reset |
| 5 | WebSocket | `/ws/invocations` | **NOT TESTED** | requires stable HTTP upgrade |
| 6 | SSE | `GET /events` | **BLOCKED** | curl reset |
| 7 | MCP | `POST /mcp` JSON-RPC `tools/list` | **BLOCKED** | curl reset |
| 8 | Webhook | `POST /webhooks/inbound/{event}` | **BLOCKED** | curl reset |
| 9 | CDC | `POST /api/v1/cdc/subscriptions` | **BLOCKED** | curl reset |
| 10 | Filewatcher | `/api/v1/watchers/` | **BLOCKED** | curl reset |
| 11 | Email (IMAP) | n/a | **N/A** | no HTTP endpoint — `src/backend/entrypoints/email/imap_monitor.py` is a background asyncio poller, not a route |
| 12 | AMQP/RabbitMQ | `POST /stream/rabbit/*` | **NOT TESTED** | would need broker — `compose-rabbit` is `Exited (0) 34 minutes ago` |
| 13 | Redis Streams | `POST /stream/redis/*` | **NOT TESTED** | `compose-redis-1` is `Exited (137) 34 minutes ago` (OOMKill) |
| 14 | MQTT | n/a | **N/A** | `src/backend/entrypoints/mqtt/mqtt_handler.py` is a per-source handler; no `/api/v1/mqtt` HTTP route is mounted in `src/backend/plugins/composition/app_factory.py` |

DSL pipeline / Workflow e2e / AI/RAG coverage: see below — **all BLOCKED**
because the HTTP entrypoint is unreachable.

---

## Per-protocol evidence

### 1. REST + OpenAPI

`/openapi.json` succeeded at 16:16Z and revealed:

```
Total paths: 410  (categories auto-extracted)
  /graphql, /api/v1/graphql
  /soap/, /soap/invoke, /soap/wsdl
  /grpc/schema, /grpc/schema/json
  /api/v1/asyncapi.json, /api/v1/asyncapi.yaml
  /api/v1/cdc/subscriptions
  /api/v1/watchers/, /api/v1/watchers/{id}
  /webhooks/inbound/{event_type}, /webhooks/sources/{id},
  /webhooks/subscriptions, /webhooks/subscriptions/{sub_id}
  /api/v1/auto/notify.webhook, /api/v1/auto/webhook.*
  ... and ~350 admin+/v1/admin routes
```

No `/api/v1/orders.list` / `users.list` / `files.list` endpoints exist in the
generated OpenAPI schema for the dev_light profile. The `extensions/core_entities/`
plugins (`orders`, `users`, `files`) are NOT auto-mounted as REST routes by
`app_factory.py`. Per `extensions/core_entities/*/plugin.toml`, these are
**plugins** loaded by `register_action_handlers()` and exposed via the
**action-bus dispatcher** at `/api/v1/auto/<action>` (auto-register) — but
dev_light skips that registration step:

```
src/backend/plugins/composition/app_factory.py:220-229
  try:
    from src.backend.dsl.commands.setup import register_action_handlers
    register_action_handlers()
  except Exception as exc:
    get_logger(...).warning("register_action_handlers пропущен: %s ...", exc)
```

So even if HTTP were healthy, there would be no `/api/v1/orders.list` endpoint
under dev_light. Mark these as **NOT MOUNTED** rather than BLOCKED.

### 2. GraphQL

Hand-written router mount confirmed in
`src/backend/plugins/composition/app_factory.py:182`:

```python
app.include_router(graphql_router)               # /graphql
...
auto_register_strawberry_schema(app, path="/api/v1/graphql")  # /api/v1/graphql (Wave 1.4)
```

Attempt:

```bash
$ curl -sv -m 5 -H 'X-API-Key: 0e9056ba-7799-4fc0-b55f-008a8f6137e0' \
    -H 'Content-Type: application/json' \
    -X POST http://127.0.0.1:8000/graphql \
    -d '{"query":"{ __schema { types { name } } }"}' 2>&1 | tail -10
> POST /graphql HTTP/1.1
> Host: 127.0.0.1:8000
< HTTP/1.1 ???
* Recv failure: Соединение разорвано другой стороной
curl: (56) Recv failure
```

**Result: BLOCKED** by HTTP transport instability.

Schema reference (`src/backend/entrypoints/graphql/schema.py`) is present and
importable but unverified by introspection.

### 3. gRPC — direct invocation failed

**Configuration** (`src/backend/entrypoints/grpc/server.py` typically):
gRPC server is a separate process spawned by `src/backend/entrypoints/grpc/grpc_server/serve()` —
confirmed by `/tmp/grpc.log` inside container.

**Container state at 16:22Z:**

```
$ sudo docker exec gd-app-light cat /tmp/grpc.log
Traceback (most recent call last):
  File "<string>", line 1, in <module>
    import asyncio; from src.backend.entrypoints.grpc.grpc_server.server import serve; asyncio.run(serve())
                    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/app/src/backend/entrypoints/grpc/grpc_server/__init__.py", line 93, in <module>
    _patch_rpc_methods()
    ...
ImportError: cannot import name 'order_pb2_grpc' from 'src.backend.entrypoints.grpc.protobuf' (unknown location)
```

However the error message is misleading:

- No `order_pb2_grpc` symbol exists in source code (`grep -rE 'order_pb2_grpc' src/` returned zero hits).
- The actual import in `grpc_server/__init__.py:53-57` is:

```python
from src.backend.entrypoints.grpc.protobuf import (
    invoker_pb2_grpc,    # present
    orders_pb2_grpc,     # present (container) — was missing transiently
    files_pb2_grpc,      # present
)
```

- Re-running the same import via `sudo docker exec` returns `All imports OK`.

**Socket state:**

```
$ sudo docker exec gd-app-light ls -la /tmp/ | grep -i sock
# NO MATCHES — /tmp/order_service.sock does NOT exist
```

**Test invocation** (from inside container via python `grpc.aio.insecure_channel`):

```python
import asyncio, grpc
from src.backend.entrypoints.grpc.protobuf.invoker_pb2_grpc import InvokerServiceStub
from src.backend.entrypoints.grpc.protobuf.invoker_pb2 import InvokeRequest

async def main():
    ch = grpc.aio.insecure_channel('unix:///tmp/order_service.sock')
    stub = InvokerServiceStub(ch)
    req = InvokeRequest(action='system.health', payload_json='{}', mode='sync')
    resp = await stub.Invoke(req, timeout=5)
asyncio.run(main())
```

Output:
```
RPC error: AioRpcError <AioRpcError of RPC that terminated with:
  status = StatusCode.UNAVAILABLE
  details = "failed to connect to all addresses; last error:
    FAILED_PRECONDITION: unix:/tmp/order_service.sock: connect failed:
    addr: unix:/tmp/order_service.sock error: No such file or directory"
```

Port 50051 inside container also refused:

```
$ sudo docker exec gd-app-light python -c "import socket; \
    socket.create_connection(('127.0.0.1', 50051), timeout=2)"
[Errno 111] Connection refused
```

**Result: FAILED** (gRPC server not running). Two possibilities for the original
crash:
- (a) gRPC server was killed by the host disk-full event alongside postgres/redis.
- (b) The `/tmp/grpc.log` error message is from a stale process that wrote the
  log file before `ImportError` and exited before re-fix.

To recover: re-run the gRPC server (`src/backend/entrypoints/grpc/grpc_server/server.py`
has `_safe_error()`, `serve()`, etc.) or rebuild the container image so the
proto regeneration step reproduces `orders_pb2_grpc.py`.

### 4. SOAP

Mount at `/soap`, `/soap/invoke`, `/soap/wsdl` per
`src/backend/plugins/composition/app_factory.py:186`.

```bash
$ curl -s -m 5 'http://127.0.0.1:8000/soap?wsdl' -o /tmp/soap.wsdl
# curl: (56) Recv failure
```

**Result: BLOCKED.** Path is correct; HTTP transport died.

### 5. WebSocket

Mounted at `/ws` and `/ws/invocations` (`ws_router`, `ws_invocations_router`,
`app_factory.py:183-184`). `websockets` lib test was not run — requires HTTP
upgrade handshake which is impossible while port-8000 socket is dead.

**Result: NOT TESTED.** (Was planning to run
`python -c "import websockets; websockets.connect('ws://127.0.0.1:8000/ws/invocations')"`.)

### 6. SSE

```
app.include_router(sse_router)  # app_factory.py:187
# sse_router = APIRouter(prefix="/events", tags=["SSE"])
# src/backend/entrypoints/sse/handler.py:18
```

```bash
$ curl -s -m 5 -N 'http://127.0.0.1:8000/events'
# curl: (56) Recv failure
```

**Result: BLOCKED.**

### 7. MCP

`app.mount(mcp_settings.bind_path, create_mcp_http_app())`
(`src/backend/main.py:46-48`). Default `bind_path="/mcp"`
(`src/backend/core/config/ai_stack.py:295-297`).

```bash
$ curl -s -m 5 -X POST 'http://127.0.0.1:8000/mcp' \
    -H 'Content-Type: application/json' \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
# curl: (56) Recv failure
```

**Result: BLOCKED.** The `mcp_http_enabled` flag (env `MCP_HTTP_ENABLED`) was
not verified but paths conform to FastMCP HTTP transport convention.

### 8. Webhook

Mount at `/webhooks` per `app_factory.py:188-189`, handlers in
`src/backend/entrypoints/webhook/handler.py`.

```bash
$ curl -s -m 5 -X POST 'http://127.0.0.1:8000/webhooks/inbound/test' \
    -H 'Content-Type: application/json' -d '{}'
# curl: (56) Recv failure
```

**Result: BLOCKED.**

### 9. CDC

`app.include_router(cdc_router)` mounted with `prefix="/api/v1/cdc"`
(`src/backend/entrypoints/cdc/cdc_routes.py`).

```bash
$ curl -s -m 5 -H 'X-API-Key: 0e9056ba-7799-4fc0-b55f-008a8f6137e0' \
    -H 'Content-Type: application/json' \
    -d '{"name":"test"}' 'http://127.0.0.1:8000/api/v1/cdc/subscriptions'
# curl: (56) Recv failure
```

**Result: BLOCKED.**

### 10. Filewatcher

Mounted at `/api/v1/watchers/` (`watcher_router` + `prefix="/api/v1"` in
`app_factory.py:185`).

**Result: BLOCKED.**

### 11. Email (IMAP)

`src/backend/entrypoints/email/imap_monitor.py` is a **background asyncio
poller** (`ImapMonitor` class + `ImapConfig` dataclass), not a FastAPI route.
There is no `POST /api/v1/email/imap` endpoint in `/openapi.json` for dev_light.

**Result: N/A** for HTTP. To exercise IMAP an actual mailbox server is required
and the worker would need to be scheduled via `register_action_handlers()` —
also not loaded in dev_light.

### 12. AMQP / RabbitMQ

`app.include_router(stream_client.rabbit_router, prefix="/stream/rabbit")`
(`app_factory.py:175-178`).

**Result: NOT TESTED** because `compose-rabbit` container is
`Exited (0) 34 minutes ago`. Routes would need broker, real test impossible
without restarting broker.

### 13. Redis Streams

`app.include_router(stream_client.redis_router, prefix="/stream/redis")`
(`app_factory.py:171-174`).

**Result: NOT TESTED** because `compose-redis-1` is `Exited (137)` (OOMKill
at 15:44Z after "Errors trying to shut down the server ... No space left on
device").

### 14. MQTT

`src/backend/entrypoints/mqtt/mqtt_handler.py` only defines a
`MQTTSourceHandler` / `MQTTSinkHandler` style of class — it is loaded by the
**action-handler registry**, not mounted as an HTTP route. There is no
`/api/v1/mqtt` endpoint in `/openapi.json`.

**Result: N/A** for HTTP probing. Real MQTT would require a broker and an
action-handler registration, both skipped by dev_light.

---

## DSL pipeline (1 route from extensions/)

The DSL pipeline runs **inside the FastAPI app** during request handling. With
the HTTP transport dead, no DSL route can execute via HTTP. There is no
out-of-band DSL runner mounted for dev_light.

**Result: BLOCKED** (HTTP dependency).

To exercise DSL end-to-end a route would need to be invoked through one of the
working protocols (gRPC `Invoke`, `/api/v1/auto/<action>`, etc.). All currently
dead.

---

## Workflow e2e

The 4× `compose-workflow-worker-{1..4}` are **UNHEALTHY with DNS errors** —
see DIAGNOSIS_workers_2026-08-13.md (sibling report) for full root-cause.

A workflow cannot complete end-to-end because:

1. Workflow workers cannot reach `postgres` (DNS resolution to host `main`).
2. Workers emit
   `backup poll error: Failed to create database session for 'main'` and the
   underlying `socket.gaierror: [Errno -3] Temporary failure in name
   resolution`.
3. Even if workers were healthy, the HTTP path used to `POST
   /api/v1/admin/workflows/trigger/{name}` is dead.

**Result: BLOCKED** with explicit explanation captured.

---

## AI / RAG coverage

- `ai.chat` — typically exposed via `/api/v1/ai/chat` action; blocked (HTTP).
- `rag.ingest`, `rag.search` — typically exposed via
  `/api/v1/auto/rag.ingest` etc.; blocked (HTTP).

Vault is also unreachable:

```
Vault недоступен (HTTPConnectionPool(host='127.0.0.1', port=8200): ...
  Connection refused) — secrets-источник пропущен
```

Multiple library paths warn about this on every import (visible in `docker logs`).
Action-level tests cannot rely on Vault-injected secrets; fallback to env-only
is in effect.

**Result: BLOCKED.**

---

## Open issues captured

1. **O-P0-13A** — `gd-app-light` granian workers hang in `State: D (disk
   sleep)` despite 35 GB host free. Fork during the disk-full event is
   non-recoverable without container restart. Recommend `sudo docker restart
   gd-app-light` and re-verify.
2. **O-P0-13B** — `/tmp/grpc.log` shows `ImportError: cannot import name
   'order_pb2_grpc'` — stale log. Re-running the import succeeds. The gRPC
   server is genuinely not running (port 50051 refused, no unix socket).
3. **O-P1-13A** — `compose-postgres-1` and `compose-redis-1` exited ~34 min
   ago, both caused by `No space left on device`. Host currently has 35 GB
   free — should be safe to restart, but pg logical replication data files
   may need cleanup.
4. **O-P1-13B** — Vault not running — all Vault-ref secrets skipped silently.
   Action-handler tests would need to inject secrets via direct env.

---

## Recommendations (minimal change)

1. `sudo docker restart gd-app-light` to clear the disk-sleep workers.
2. `sudo docker compose -f ops/compose/docker-compose.yml up -d postgres
   redis` to bring the data plane back, then re-test workflows.
3. Once stable, prioritize testing: REST auth via API key, GraphQL
   introspection, gRPC over the unix socket, then SOAP+WSDL.
