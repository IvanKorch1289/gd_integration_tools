# DSL (Domain-Specific Language)

Маршруты, шаги, шаблоны, валидация для всей интеграционной шины.

## Архитектура

```
src/backend/dsl/
├── builders/          # Fluent API (RouteBuilder, WorkflowBuilder)
│   ├── base.py        # + 13 mixin files
│   └── *.py           # agent_dsl, data_store, template_engine, etc.
├── engine/            # Runtime
│   ├── exchange.py    # Message envelope
│   ├── context.py     # Execution context
│   ├── processors/    # 18 processor dirs (cdc, ai, eip, etc.)
│   ├── versioning.py
│   └── trace_storage.py
├── yaml_loader/       # YAML DSL parser
│   ├── loaders.py
│   ├── resolve.py
│   ├── build.py
│   └── validate.py
├── commands/          # Setup CLI
└── processors/        # Specific processors
```

## Builders (fluent API)

| Builder | Описание | Mixin count |
|---|---|---|
| `RouteBuilder` | Single integration route | 13 mixins |
| `WorkflowBuilder` | Multi-step Temporal workflow | workflow_mixin |
| `AgentDSLMixin` | LangGraph agent route | orchestration + infra |

## Processors (18 categories)

| Категория | Описание | DSL-метод |
|---|---|---|
| `cdc_capture` | PostgreSQL/Oracle CDC source | `route.from_cdc_capture()` |
| `cdc_transform` | CDC event normalization | `route.cdc_transform()` |
| `eip` | Enterprise Integration Patterns | `route.aggregate()` etc. |
| `ai` | LLM, RAG, RLM | `route.invoke_llm()`, `route.rag_query()` |
| `data_query` | SQL queries | `route.from_db()` |
| `data_store` | CRUD operations | `route.crud_*()` |
| `converters` | Format conversion | `route.convert()` |
| `messaging` | MQ/MQTT/WebSocket | `route.to_eventbus()` |
| `notify` | Email/Telegram/Push | `route.notify()` |
| `control_flow` | Choice/Saga/LRA | `route.choice()` etc. |
| `saga_lra` | Saga compensations | saga_mixin |
| `agent_dsl` | LangGraph agents | agent_dsl_mixin |
| `batch` | Batch processing | batch.py |
| `dask_compute` | Dask distributed | dask_mixin |
| `streaming_llm` | LLM streaming | streaming_mixin |
| `calendar_ics` | Calendar integration | calendar_ics |

## Пример

```python
route = (
    RouteBuilder
    .from_cdc_capture("orders.changes", profile="prod", tables=["orders"])
    .cdc_transform(operations=["INSERT", "UPDATE"], project=["id", "table", "operation"])
    .to_eventbus("domain.orders")
    .to_cache(ttl=60)
    .dispatch_action("analytics.process_changes")
    .build()
)
```

## Validation

Pydantic-based через `BaseProcessor.to_spec()`. All processors implement `to_spec()` per S164 W22 contract.

## См. также

- [ADRs](../adr/) — Architecture decisions
- [Index](../index.md) — Project overview
- [ARCHITECTURE](../ARCHITECTURE.md) — Layer map