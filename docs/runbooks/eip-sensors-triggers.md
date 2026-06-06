# EIP Patterns, Sensors & Route Triggers — Sprint 55

**Sprint 55** добавил Apache Camel EIP gaps, Apache Airflow-style sensors,
и Camel-style ``from(...)`` route triggers. Все реализованы через DSL
на ``RouteBuilder`` + programmatic API в ``eip`` / ``orchestration`` модулях.

---

## 1. Apache Camel EIP — новые patterns (S55 W1 + W2)

### Routing Slip (S55 W1) — динамическая цепочка processors

```python
from src.backend.dsl.engine.processors.eip.routing_slip import (
    RoutingSlipProcessor, SimpleRegistry,
)

reg = SimpleRegistry()
reg.register("audit", AuditProcessor())
reg.register("transform", TransformProcessor())

# Per-message chain (header "flow" → list of step names)
.route_slip(steps=[], header="flow", strict=True, max_steps=20)
```

Apache Camel: https://camel.apache.org/components/latest/eips/routingSlip.html
Отличие от Pipeline: список steps определяется runtime'ом, не статически.

### Content-Based Router (S55 W2) — route по predicate

```python
.content_based_router([
    (lambda ex: ex.in_message.body.get("priority") == "high", "high_pri"),
    (lambda ex: ex.in_message.body.get("country") == "ru", "ru_route"),
], default_endpoint="default")
```

Apache Camel: https://camel.apache.org/components/latest/eips/contentBasedRouter.html
First matching predicate wins. Default fallback если задан, иначе message dropped.

### Sampling (S55 W2) — probabilistic subset

```python
# 10% от всех messages
.sampling(fraction=0.1)

# Каждый 100-й
.sampling(rate=100)

# 5 per second
.sampling(time_window_ms=1000, max_in_window=5)
```

Apache Camel: https://camel.apache.org/components/latest/eips/sampling.html
Dropped messages → ``exchange.sampled_out = True`` + ``exchange.stop()``.

### Message Filter — **НЕ дублирован** (S55 W6 dedup)

Используйте существующий ``FilterProcessor`` в ``src/backend/dsl/engine/processors/core.py``:

```python
.filter(lambda ex: ex.in_message.body.get("amount", 0) > 100)
```

Apache Camel: https://camel.apache.org/components/latest/eips/filter.html

---

## 2. Apache Airflow-style Sensors (S55 W3 + S6)

Long-running watcher, polling external condition, triggers route на match.

| Sensor | DSL | Library | Notes |
|--------|-----|---------|-------|
| File | `.from_file(path, pattern=...)` | watchfiles | inotify-based, no polling overhead |
| SQL | `.from_sql(dsn, query, predicate=...)` | asyncpg | JMESPath predicate support |
| HTTP | `.from_http(url, expected_status=...)` | httpx | Status + body_match |
| S3 | `.from_s3(bucket, key, ...)` | aioboto3 (lazy) | Install: `uv pip install aioboto3` |

```python
# File sensor
.from_file("/var/log/orders", pattern="*.csv", recursive=True, poll_interval_s=2.0)

# SQL sensor
.from_sql(
    "postgresql://user:pass@db:5432/orders",
    "SELECT * FROM new_orders WHERE created_at > NOW() - INTERVAL '1 hour'",
    predicate="length(@) > 0",
)

# HTTP sensor
.from_http("http://api.internal/health", expected_status=200, body_match="status == 'ok'")

# S3 sensor (lazy aioboto3)
.from_s3("my-bucket", "exports/orders-2026.json", region="eu-west-1")
```

Apache Airflow: https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/sensors.html

**Lifecycle**: каждая ``from_*()`` создаёт background task, регистрирует
в ``TriggerRegistry``. ``get_trigger_registry().start_all()`` — на startup
приложения; ``stop_all()`` — на shutdown.

---

## 3. Route Triggers — Camel `from(...)` (S55 W4 + W6)

Каждый route начинается с source'а (timer / cron / webhook / file / kafka).

| Trigger | DSL | Notes |
|---------|-----|-------|
| Cron | `.schedule(cron=...)` | Pre-existing, croniter-based |
| Interval | `.from_interval(interval_s)` | S55 W4, periodic |
| Webhook | `.from_webhook(path, method='POST')` | S55 W4, FastAPI route |
| File | `.from_file(path, pattern=...)` | S55 W6, sensor |
| SQL | `.from_sql(dsn, query)` | S55 W6, sensor |
| HTTP | `.from_http(url)` | S55 W6, sensor |
| S3 | `.from_s3(bucket, key)` | S55 W6, sensor (lazy aioboto3) |

```python
# Пример: webhooks + polling file
route = (RouteBuilder()
    .from_webhook("/webhooks/orders", method="POST")
    .from_file("/tmp/uploads", pattern="*.json")
    .process(...)
)
```

---

## 4. Performance — Sprint 55 W5

- **orjson** в hotpath (lineage_http_emitter): ~3x faster than stdlib json.dumps.
- **S3 sensor** с lazy import: работает на light installs (ImportError если aioboto3 нет).
- **Load test scaffold**: ``python -m tools.loadtest.routes --route-id <id> --rps 100 --duration 30``.

### Установка user-approved deps (опционально)

```bash
# rich: terminal UI для new manage.py commands
uv pip install rich

# aioboto3: для S3 sensor (иначе ImportError at construction)
uv pip install aioboto3
```

Оба добавлены в `pyproject.toml`, но не установлены в текущем venv
(uv install timeout).

---

## 5. Dedup notes (S55 W6)

**Removed**: ``MessageFilter`` class в ``filter_router_sampling.py``
(дублировал ``FilterProcessor`` в ``core.py``). Используйте
``FilterProcessor`` через существующий ``.filter()`` DSL method.

**Consolidated**: импорты + Module-level docstrings в ``eip.py``
для discoverability.

---

## 6. References

- Apache Camel EIP catalog: https://camel.apache.org/components/latest/eips/patterns.html
- Apache Airflow Sensors: https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/sensors.html
- DSL: `src/backend/dsl/builders/eip.py`
- Processors: `src/backend/dsl/engine/processors/eip/`
- Sensors: `src/backend/core/orchestration/airflow_sensors.py`
- Triggers: `src/backend/dsl/orchestration/triggers.py`
