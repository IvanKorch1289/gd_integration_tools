# RouteBuilder — Python (Camel-style) fluent API

RouteBuilder предоставляет Python-интерфейс для построения DSL-маршрутов
в Camel-стиле (Enterprise Integration Patterns). Эквивалентен YAML DSL,
но позволяет использовать IDE autocomplete и проверку типов.

## Базовый пример

```python
# source: src/backend/dsl/builders/integration.py:44-62
from src.backend.dsl.builder import RouteBuilder

route = (
    RouteBuilder("credit_check_v2")
    .from_("http:POST /api/v1/credit/check")
    .policy.idempotency(key="header.X-Idempotency-Key")
    .get_setting("skb.api_url", to="body.api_url")
    .proxy(src="/legacy", dst="http://legacy:8080")
    .call_function("extensions.credit.normalizer:apply_rules")
    .crud_create("orders", body="${body.order}")
    .validate_response(schema="CreditDecision", on_error="dlq")
    .dispatch_action("credit.score.calculate", mode="sync")
    .invoke_workflow("credit_assessment_ai", mode="async-api")
    .to("response", code=202, body="${body.invocation_id}")
    .build()
)
```

## Эквивалентный YAML

```yaml
# routes/credit_check/credit_check_v2.dsl.yaml
from:
  http:
    method: POST
    path: /api/v1/credit/check

steps:
  - get_setting: { path: "skb.api_url", to: body.api_url }
  - proxy: { src: /legacy, dst: http://legacy:8080 }
  - call_function: { ref: extensions.credit.normalizer:apply_rules }
  - crud_create: { entity: orders, body: ${body.order} }
  - validate_response: { schema: CreditDecision, on_error: dlq }
  - dispatch_action: { name: credit.score.calculate, mode: sync }
  - invoke_workflow: { name: credit_assessment_ai, mode: async-api }

to:
  response:
    code: 202
    body: { invocation_id: ${body.invocation_id} }
```

## Полный набор fluent-методов

### Источник (from)

```python
.from_("http:GET /api/resource")           # HTTP source
.from_("kafka:topic=orders")                # Kafka source
.from_("timer:interval=60s")                # Scheduled
.from_("file:path=/data/in/*.csv")          # File watcher
```

### CRUD-операции

```python
# source: src/backend/dsl/builders/integration.py
route.crud_create("orders", body="${body.order}")     # INSERT
route.crud_read("orders", id="${header.order_id}")    # SELECT
route.crud_update("orders", id="${body.id}", body="${body}")  # UPDATE
route.crud_delete("orders", id="${header.order_id}")  # DELETE
route.crud_list("orders", filter="${body.filter}")     # SELECT list
```

### Proxy / Forward

```python
route.proxy(src="/legacy", dst="http://legacy:8080")       # HTTP proxy
route.forward_to("http://internal:9000/api")               # Forward без改
route.expose_proxy(port=8080, path="/api/proxy")          # Expose proxy endpoint
```

### Вызовы

```python
route.call_function("extensions.credit.normalizer:apply_rules")
route.dispatch_action("orders.send_notification", mode="sync")
route.invoke_workflow("order_fulfillment", mode="async-api", args={"order_id": "${body.id}"})
```

### Settings и валидация

```python
route.get_setting("skb.api_url", to="body.api_url", default="https://default.example.com")
route.validate_response(schema="CreditDecision", on_error="dlq")
route.validate_response(schema="OrderConfirmation", on_error="warn")
```

### Policy

```python
route.policy.idempotency(key="header.X-Idempotency-Key", ttl_seconds=3600)
route.policy.rate_limit(requests=100, window_seconds=60)
route.policy.circuit_breaker(failure_threshold=5, recovery_timeout=30)
```

### Базы данных

```python
route.db_call_procedure("compute_order_totals", args="${body}", result_property="totals")
route.db_query("SELECT * FROM orders WHERE id = :id", params="${header}", result_property="orders")
route.db_query_external("remote_db", query="${body.sql}", result_property="external_result")
```

### Файлы и S3

```python
route.read_file(path="${header.file_path}")
route.write_file(path="/tmp/${body.filename}", content="${body.content}")
route.read_s3(bucket="data", key="${header.s3_key}")
route.write_s3(bucket="output", key="${body.key}", content="${body.data}")
```

### Email / Shell / Webhook

```python
route.email(to="${body.recipients}", subject="Order confirmed", body="${body}")
route.shell("python /scripts/process.py", args="${body}", result_property="script_output")
route.webhook_sign(secret="${settings.webhook_secret}")
route.webhook_verify(signature="header.X-Signature", secret="${settings.webhook_secret}")
```

### Таймер / Polling

```python
route.timer(interval="30s", property="tick")
route.poll(
    uri="http://status-check:8080/${header.task_id}",
    condition="body.status == 'completed'",
    interval=5,
    timeout=300,
)
```

### Output

```python
route.to("response", code=200, body="${body.result}")
route.to("dlq", reason="${body.error_reason}")
route.publish_event(topic="orders.created", body="${body}")
route.notify_cascade("order_shipped", body="${body}")
```

## Сравнение с Java Apache Camel

```java
// Java Camel
from("direct:input")
    .idempotentConsumer(header("id"), myMemoryStore)
    .process(new CreditNormalizer())
    .to("sql:INSERT INTO orders VALUES (#)?dataSource=ds")
    .to("log:out");
```

```python
# Python RouteBuilder (gd_integration_tools)
RouteBuilder("credit_flow")
    .from_("direct:input")
    .policy.idempotency(key="header.id")
    .call_function("extensions.credit.normalizer:apply_rules")
    .crud_create("orders", body="${body}")
    .to("log", body="${body}")
```

Ключевые отличия:
- Python-стиль вместо Java builder chain
- `call_function` вместо processor- classes
- `invoke_workflow` для Temporal вместо `to("temporal:...")`
- `get_setting` для typed settings вместо property-placeholder

## DI-интеграция

RouteBuilder использует DI-контейнер для resolver'ов:

```python
# Резолв сервиса из контейнера
route.crud_create("orders", body="${body}",
                  service_resolver=get_container().resolve(OrderService))
```

## Регистрация

```python
from src.backend.dsl.registry import route_registry

route = RouteBuilder("my_route").from_("http:GET /api/ping").to("response", code=200).build()
route_registry.register(route)
```

## Feature flags

```python
route.feature_flag("new_credit_flow_enabled")  # Роут активен только при флаге
route.schedule("0 9 * * 1-5")                   # Cron schedule (Slo по R-V15-2)
```

## Stateful vs Stateless

Все миксины RouteBuilder stateless — не хранят состояние между вызовами.
Хранилище — в процессорах (processors) и внешних системах (Redis, Temporal).

## См. также

- `src/backend/dsl/builders/integration.py` — IntegrationMixin (основной миксин)
- `src/backend/dsl/builders/ai_rpa.py` — AI/RPA процессоры
- `src/backend/dsl/builders/agent_dsl.py` — Agent DSL
- `docs/tutorials/01_first_route.md` — YAML DSL route tutorial