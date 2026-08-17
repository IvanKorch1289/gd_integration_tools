# Cycle 207 — Out-of-scope tasks: workers + deferred gRPC/MCP (2026-08-14)

**Branch:** master @ HEAD
**Author:** kimi Code CLI (cycle 207)
**Scope:** Action items из CYCLE-206-FRONTEND-MIGRATION.md §6.2 ("Still pending")

---

## TL;DR

| Задача | Статус | Verification |
|---|---|---|
| Workers HEALTHCHECK | ✅ **FIXED** | 4/4 workers `healthy` (was `unhealthy` 7773+ fail streak) |
| gRPC socket в dev_light | ⚠️ DEFERRED (отдельный container нужен) | — |
| NEW-3 MCP JSON-RPC | ⚠️ DEFERRED (image rebuild нужен) | — |

**1 коммит** (`169d689f`): 45 LOC changed в compose файлах.

---

## 1. Cycle 207a — Workers HEALTHCHECK (FIXED ✅)

### 1.1 Root cause

**docker-compose.yml** (full stack) workers:
- Healthcheck: `python -c "import socket; socket.create_connection(('127.0.0.1', 8000), timeout=3)" || exit 1`
- Checks **port 8000** (app's HTTP port)
- Workers НЕ слушают 8000 — они слушают **:9100** (WorkerProbesServer)
- Все 4 workers marked `unhealthy` с FailingStreak **7773**

**docker-compose.light.yml** (light profile) workers:
- Healthcheck: `ps aux | grep -v grep | grep -q 'src.backend.infrastructure.workflow.worker' || exit 1`
- `ps` НЕ установлен в slim image → CMD exit 1 → unhealthy
- Даже если бы `ps` был: Tini wrapper изменяет process name

### 1.2 Fix (atomic, 2 файла)

Both compose файлы → TCP check на :9100 (WorkerProbesServer port):

```yaml
healthcheck:
  test: ["CMD-SHELL", "python -c \"import socket; socket.create_connection(('127.0.0.1', 9100), timeout=3)\" || exit 1"]
  interval: 30s
  timeout: 5s
  retries: 3
  start_period: 15s
```

**Universal**: `python` доступен в любом Python image, не зависит от
`ps`/Tini/process naming.

### 1.3 Production deploy

```bash
sudo docker compose -f ops/compose/docker-compose.yml up -d --no-deps workflow-worker
# sleep 35s → 4/4 workers "healthy"
```

### 1.4 Verification

| Container | Before | After |
|---|---|---|
| compose-workflow-worker-4 | `Up 1h (unhealthy)` FailingStreak 7776 | `Up 3 min (healthy)` ✅ |
| compose-workflow-worker-5 | `Up 1h (unhealthy)` FailingStreak 7776 | `Up 3 min (healthy)` ✅ |
| compose-workflow-worker-6 | `Up 1h (unhealthy)` FailingStreak 7776 | `Up 3 min (healthy)` ✅ |
| compose-workflow-worker-7 | `Up 1h (unhealthy)` FailingStreak 7776 | `Up 3 min (healthy)` ✅ |

---

## 2. Cycle 207b — gRPC socket в dev_light (DEFERRED ⚠️)

### 2.1 Root cause

`compose-app-1` (HTTP-приложение) **НЕ запускает** gRPC `serve()` в
своём lifespan. Только `proto_viewer_router` mounted в FastAPI.

```text
$ grep -rnE "grpc.serve|grpc_app" src/backend/plugins/composition/
(no results — gRPC serve() not in app lifecycle)
```

`base.yml` имеет `grpc.socket_path: /tmp/order_service.sock`, но нет
кода, который запускает `serve()` с этим socket.

### 2.2 Why deferred (не safe-incremental)

Fix requires:
- [ ] Add `grpc_serve` command в `manage.py` (~30 LOC)
- [ ] Add `grpc-server` service в `docker-compose.light.yml` (volume mount для unix socket)
- [ ] Healthcheck для нового service
- [ ] Wire grpc-serve в compose startup ordering (depends_on)
- [ ] Verify gRPC client (Python grpcio) can connect via unix socket

**Scope**: 1 service в compose + 1 CLI command + 1 healthcheck. Multi-file,
multi-cycle work. Out of scope cycle 207 atomic.

**Alternative минимальный fix**: add `feature-flag grpc.lifecycle.enabled=true`
в base.yml/dev_light.yml + lifespan hook to call serve(). Это зацепляет
существующий app startup — risky для atomic commit.

### 2.3 Doc

Оставлен как known issue. См. раздел "Still pending" в
CYCLE-206-FRONTEND-MIGRATION.md §6.2.

---

## 3. Cycle 207c — NEW-3 MCP JSON-RPC (DEFERRED ⚠️)

### 3.1 Root cause

```text
$ sudo docker exec compose-app-1 python -c "import fastmcp"
ModuleNotFoundError: No module named 'fastmcp'
```

**fastmcp НЕ установлен в compose-app-1 image** (только в optional
`[mcp]` extra, не в `[dev-light]` extra).

`ops/compose/Dockerfile` использует `--extra dev-light` (line 34), который
НЕ включает fastmcp.

### 3.2 Существующий комментарий подтверждает

`ops/compose/docker-compose.light.yml` уже имеет explanatory comment:

```yaml
# Причина: ``fastmcp>=3.2.4`` (ADR-0070 §3) входит в ``[mcp]`` extra,
# но НЕ в ``[dev-light]`` extra (``pyproject.toml``). Монтирование
# ``/mcp`` в ``light`` стеке даёт 404 ("fastmcp is not installed").
# Для тестирования MCP нужен ``[dev]`` или ``[mcp]`` extra +
```

Этот комментарий подтверждает что NEW-3 (MCP POST hang) — известный
infrastructure gap, не code bug.

### 3.3 Why deferred

Fix requires:
- [ ] Rebuild compose-app-1 image with `--extra mcp` (5-10 мин build time)
- [ ] OR add fastmcp к `[dev-light]` extra in pyproject.toml (affects all light stack users)

Оба варианта:
- Multi-file changes
- Image rebuild (5-10 min downtime OR careful restart)
- Out of scope cycle 207 atomic

### 3.4 Plan для будущих циклов (cycle 208+)

```bash
# Cycle 208 plan: enable fastmcp в light stack
1. Add "fastmcp>=3.2.4" to [dev-light] extra in pyproject.toml
2. Run: docker build -f ops/compose/Dockerfile -t gd-integration-tools:light .
3. Smoke test: curl POST /mcp with Accept: application/json
4. Expected: 200 OK with JSON-RPC response
```

---

## 4. Summary

### 4.1 Achieved (cycle 207)

- ✅ Workers HEALTHCHECK fix — production deployed, **4/4 workers healthy**
- ✅ Atomic commit `169d689f` (45 LOC changed)

### 4.2 Still pending (deferred to cycle 208+)

| Task | Reason | Cycle |
|---|---|---|
| gRPC socket в dev_light | Requires new compose service + grpc-serve command | 208+ |
| NEW-3 MCP JSON-RPC | Requires image rebuild with `[mcp]` extra | 208+ |
| gRPC OrderService* test in dev_light | Need grpc-server container first | 209+ |
| Tarantool crash-loop | 8 months old, separate compose | background |

---

## 5. Артефакты cycle 207

- `ops/compose/docker-compose.yml` (workers healthcheck fix)
- `ops/compose/docker-compose.light.yml` (workers healthcheck fix)
- `docs/audit/CYCLE-207-OUT-OF-SCOPE.md` (this file)

**HEAD**: `169d689f`
