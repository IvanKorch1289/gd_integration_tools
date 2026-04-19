# gd_integration_tools

Apache Camel-inspired integration platform in Python with DSL route builder.

## Architecture

```
src/
├── core/               # Config, interfaces, resilience, security, DI
│   ├── config/         # Pydantic settings (base, database, http, etc.)
│   ├── service_dsl.py  # @service_dsl / @register_action decorators
│   └── interfaces.py   # CircuitBreaker, AsyncBatcher, auth contracts
├── dsl/                # ★ DSL engine — the heart of the system
│   ├── builder.py      # RouteBuilder — fluent API for route construction
│   ├── engine/
│   │   ├── exchange.py     # Exchange (Camel-compatible: in/out message, properties)
│   │   ├── pipeline.py     # Pipeline (list of processors + metadata)
│   │   ├── execution_engine.py  # Executes pipeline with middleware chain
│   │   ├── middleware.py   # Timeout, error normalization, metrics
│   │   └── processors/    # All processor implementations
│   │       ├── core.py        # SetHeader, Transform, Filter, Enrich, Validate, Log
│   │       ├── control_flow.py # Choice, Retry, TryCatch, Parallel, Saga, PipelineRef
│   │       ├── eip.py         # Camel EIP: DeadLetter, Idempotent, Splitter, Aggregator,
│   │       │                  # Throttler, Delay, WireTap, DynamicRouter, ScatterGather,
│   │       │                  # RecipientList, Fallback, MessageTranslator,
│   │       │                  # LoadBalancer, CircuitBreaker, ClaimCheck, Normalizer,
│   │       │                  # Resequencer, Multicast
│   │       ├── components.py  # Source/Sink: HttpCall, DatabaseQuery, FileRead/Write,
│   │       │                  # S3Read/Write, Timer, PollingConsumer
│   │       ├── converters.py  # TypeConverter: JSON↔YAML/MsgPack/XML/CSV/Parquet/BSON, HTML→JSON
│   │       ├── scraping.py    # Scrape, Paginate, ApiProxy
│   │       ├── ai.py          # LLMCall, PromptComposer, VectorSearch, PII, TokenBudget
│   │       ├── web.py         # Navigate, Click, FillForm, Extract, Screenshot
│   │       ├── external.py    # MCPTool, AgentGraph, CDC
│   │       ├── integration.py # EventPublish, MemoryLoad/Save
│   │       ├── export.py      # Export CSV/Excel/PDF
│   │       └── dq_check.py    # Data Quality checks
│   ├── adapters/       # Protocol adapters (REST, SOAP, gRPC, GraphQL, Kafka, etc.)
│   ├── commands/       # Action registry + setup.py (action handler registration)
│   └── importers/      # OpenAPI importer
├── infrastructure/     # Clients (HTTP, Redis, S3, SMTP, FTP, ES, MongoDB, ClickHouse)
├── services/           # Business services (orders, users, files, AI, export, etc.)
├── entrypoints/        # FastAPI routes, WebSocket, Streamlit UI, webhooks, MQTT, email
└── schemas/            # Pydantic models
```

## Key Concepts

- **Exchange**: Message container (Camel-compatible) with in/out messages, properties, headers, status
- **Processor**: Unit of work — `async process(exchange, context)`
- **Pipeline**: Ordered list of processors with metadata (route_id, source, protocol)
- **RouteBuilder**: Fluent API — `RouteBuilder.from_("id", source="...").transform(...).build()`
- **Action**: Named operation mapped to service method via `ActionHandlerRegistry`

## Adding New Functionality

### New Processor
1. Create class extending `BaseProcessor` in appropriate file under `processors/`
2. Add builder method to `RouteBuilder` in `builder.py`
3. Export in `processors/__init__.py`

### New Action
Option A (decorator): Add `@register_action("prefix.method")` to service method
Option B (manual): Add `ActionHandlerSpec` in `setup.py`

### New Protocol Adapter
1. Add enum value to `ProtocolType` in `adapters/types.py`
2. Create adapter in `adapters/`

## Commands

```bash
# Run app
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Run tests
pytest tests/ -v

# Lint
ruff check src/ --fix
ruff format src/

# Type check
mypy src/ --ignore-missing-imports
```
