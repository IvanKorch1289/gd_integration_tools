# DSL Reference

Справочник DSL-процессоров и builder-API. Подробное описание каждого
процессора генерируется автоматически из docstrings в
`src/dsl/engine/processors/`.

## Builder API

```python
from src.dsl.builder import RouteBuilder

pipeline = (
    RouteBuilder.from_("rabbitmq:queues.orders")
    .decode("json")
    .filter("$.status == 'NEW'")
    .transform_polars("df.group_by('region').sum()")
    .to_("s3:warehouse/orders/{date}.parquet")
    .build(route_id="orders.to_warehouse")
)
```

## Категории процессоров

| Категория | Примеры | Файл |
|-----------|---------|------|
| Routing | Filter, Choice, MulticastSplit, RecipientList | `dsl/engine/processors/routing/` |
| Transformation | Transform, PolarsTransform, JmespathTransform | `dsl/engine/processors/transform/` |
| EIP | Aggregator, Splitter, ContentEnricher, ComposedMessage | `dsl/engine/processors/eip/` |
| IO | DecodeBody, EncodeBody, S3Sink, FileSink | `dsl/engine/processors/io/` |
| Compute | DaskCompute, DuckDBQuery, PolarsExtended | `dsl/engine/processors/` |
| Connector | RestCall, GrpcCall, GraphqlCall, SoapCall | `dsl/engine/processors/connector/` |
| Resilience | Retry, CircuitBreaker, Timeout | `dsl/engine/processors/resilience/` |
| Workflow | Subworkflow, Loop, Branch | `dsl/engine/processors/workflow/` |

## Полный список процессоров

См. секцию `api/src/dsl/engine/processors/` в боковой панели —
автоматически собирается через **autoapi** из docstrings проекта.

## Macros

```python
from src.dsl.macros import etl_postgres_to_clickhouse

pipeline = etl_postgres_to_clickhouse(
    source_query="SELECT * FROM orders WHERE updated_at > $1",
    target_table="analytics.orders",
)
```

См. `src/dsl/macros.py` — ~30 готовых интеграций.

## Templates Library

```python
from src.dsl.templates_library import templates

tmpl = templates.get("etl.postgres_to_clickhouse")
pipeline = tmpl.builder(source_query="...", target_table="...")
```
