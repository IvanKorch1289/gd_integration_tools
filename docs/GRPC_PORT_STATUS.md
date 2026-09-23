# gRPC Port Status — Investigation (2026-09-21)

> **Context**: Live smoke test показал, что `gd-app-light` container exposes
> port 50051, но gRPC server не отвечает. Документируем root cause.

## Investigation

### Container config

```
$ sg docker -c "docker inspect gd-app-light" | grep -A 10 Entrypoint
"Entrypoint": [
    "/bin/sh",
    "-c",
    "alembic upgrade head 2>&1 | head -3; exec python manage.py run"
]
```

Контейнер запускает **`manage.py run`** — это **только FastAPI/ASGI сервер**.

### gRPC server — отдельный процесс

`manage.py` имеет **два** подкоманды для серверов:

| Команда | Что запускает | Порт |
|---|---|---|
| `manage.py run` | FastAPI + uvicorn/granian | 8000 |
| `manage.py grpc-serve` | gRPC server (Unix socket или TCP) | 50051 |

Текущий Entrypoint **запускает только REST** — gRPC остаётся выключенным.

### Code references

```python
# manage.py:36-37
@app.command()
def run(...):
    """Запуск FastAPI backend через выбранный ASGI-сервер."""

# manage.py:138-139
@app.command("grpc-serve")
def grpc_serve(...):
    """Отдельный процесс для gRPC server (Unix socket или TCP)."""
```

`manage.py grpc-serve` использует `settings.grpc.socket_path` (Unix socket)
по умолчанию, или TCP через CLI flag `--socket`.

### Почему 50051 exposed но не listening

docker-compose.yml / Dockerfile **пробрасывает** 50051 в host, но
container Entrypoint **не запускает** gRPC server. Порт проброс без
listening процесса → connection refused / timeout.

## Historical context

`src/backend/entrypoints/grpc/grpc_server/interceptor.py:30-32`:

```python
# D-AUDIT-18001 fix (cycle 180): inherit from grpc.aio.ServerInterceptor
# (was bare class — gRPC server rejected with 'Interceptor must be
# ServerInterceptor'). gRPC port 50051 was CLOSED due to this bug.
```

**Цикл 180 зафиксировал bug** — gRPC port был CLOSED из-за неправильного
наследования interceptor (был bare class вместо `grpc.aio.ServerInterceptor`).
Текущий код исправлен, но **сервер по-прежнему не стартует** в gd-app-light.

## State (2026-09-21)

| Проверка | Status | Notes |
|---|---|---|
| gRPC code исправлен | ✅ | interceptor наследует `grpc.aio.ServerInterceptor` |
| gRPC server в gd-app-light | ❌ | Entrypoint не запускает `manage.py grpc-serve` |
| Port 50051 exposed в docker-compose | ⚠️ | Mismatch: port exposed но процесс не запускается |
| Production gRPC serving | ❓ | требует separate deployment для grpc-serve |

## Recommendations

### Sprint 37 (in priority order)

1. **Decision: gRPC single-process vs separate**:
   - Option A: запускать gRPC inline в `manage.py run` (single FastAPI+gRPC process)
   - Option B: gRPC как separate service (current — но нужен Entrypoint fix)
   - Audit рекомендовал multi-protocol auto-registration — это **указывает на A**

2. **Fix Entrypoint** (если Option A):
   ```yaml
   # docker-compose.yml
   entrypoint: ["sh", "-c", "alembic upgrade head; exec python manage.py run --with-grpc"]
   ```
   + modify `manage.py run` чтобы запускал gRPC inline как background task

3. **Fix port forwarding** (если Option B):
   ```yaml
   # docker-compose.yml — добавить отдельный grpc-serve service
   grpc-server:
     image: gd-integration-tools:light
     command: python manage.py grpc-serve --socket 0.0.0.0:50051
     ports: ["50051:50051"]
   ```

## Live evidence

```
$ .venv/bin/python -c "
import grpc
ch = grpc.insecure_channel('localhost:50051')
grpc.channel_ready_future(ch).result(timeout=3)
"
gRPC test: TIMEOUT (server not responding)
```

Container logs не содержат gRPC startup events:
```
$ sg docker -c "docker logs gd-app-light" | grep -i grpc
(no matches — gRPC server не стартует)
```

## Status

**Out of scope локальной сессии** — требует решение по архитектуре deployment
(A vs B) и изменение docker-compose.yml + manage.py. Задокументировано для
следующего sprint.
