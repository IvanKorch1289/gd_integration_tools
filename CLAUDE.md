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
│   │   └── processors/    # All processor implementations (138+)
│   │       ├── core.py        # SetHeader, Transform, Filter, Enrich, Validate, Log
│   │       ├── control_flow.py # Choice, Retry, TryCatch, Parallel, Saga, PipelineRef
│   │       ├── eip/           # Camel EIP: DeadLetter, Idempotent, Splitter, Aggregator,
│   │       │                  # Throttler, Delay, WireTap, DynamicRouter, ScatterGather,
│   │       │                  # RecipientList, Fallback, MessageTranslator, LoadBalancer,
│   │       │                  # CircuitBreaker, ClaimCheck, Normalizer, Resequencer,
│   │       │                  # Multicast, Loop, OnCompletion, Sort, Timeout
│   │       ├── components.py  # Source/Sink: HttpCall, DatabaseQuery, FileRead/Write,
│   │       │                  # S3Read/Write, Timer, PollingConsumer
│   │       ├── converters.py  # TypeConverter: JSON↔YAML/MsgPack/XML/CSV/Parquet/BSON, HTML→JSON
│   │       ├── patterns.py    # n8n/Benthos/Zapier: Switch, Merge, BatchWindow,
│   │       │                  # Deduplicate, Formatter, Debounce
│   │       ├── rpa.py         # UiPath-style: Pdf/Word/Excel read/write, OCR,
│   │       │                  # image resize, regex, Jinja2, hash, encrypt/decrypt,
│   │       │                  # archive, shell exec, email compose
│   │       ├── rpa_banking.py # Банковский RPA: Citrix, SAP GUI, 3270, Appium,
│   │       │                  # email-driven, keystroke replay, bank PDF parser
│   │       ├── banking.py     # Банковские протоколы: SWIFT MT/MX, ISO 20022, FIX,
│   │       │                  # EDIFACT, 1C
│   │       ├── ai_banking.py  # AI-пайплайны: KYC/AML, антифрод, кредитный скоринг,
│   │       │                  # чат-бот, обработка обращений, tx-категоризация, fin-OCR
│   │       ├── generic.py     # Универсальные: shadow mode, bulkhead, lineage,
│   │       │                  # SSE source, JSON Schema validate, A/B router, feature flags
│   │       ├── scraping.py    # Scrape, Paginate, ApiProxy
│   │       ├── ai.py          # LLMCall, PromptComposer, VectorSearch, PII, TokenBudget
│   │       ├── web.py         # Navigate, Click, FillForm, Extract, Screenshot
│   │       ├── external.py    # MCPTool, AgentGraph, CDC
│   │       ├── integration.py # EventPublish, MemoryLoad/Save
│   │       ├── export.py      # Export CSV/Excel/PDF
│   │       ├── enrichment.py  # Контент-обогащение
│   │       ├── ml_inference.py # ML-инференс в пайплайне
│   │       ├── storage_ext.py # Расширенные storage-процессоры
│   │       └── dq_check.py    # Data Quality checks
│   ├── adapters/       # Protocol adapters (REST, SOAP, gRPC, GraphQL, Kafka, etc.)
│   ├── commands/       # Action registry + setup.py (action handler registration)
│   ├── importers/      # OpenAPI importer
│   └── yaml_loader.py  # Declarative YAML → Pipeline loader
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

### New Pipeline via YAML
```yaml
route_id: my.pipeline
source: timer:60s
processors:
  - timer: {interval_seconds: 60}
  - http_call: {url: "https://api.example.com", method: GET}
  - dispatch_action: {action: analytics.save}
```
Load via `from app.dsl.yaml_loader import load_pipeline_from_file`.

## Documentation
- `docs/PROCESSORS.md` — каталог всех 138 процессоров (автоген из docstrings)
- `docs/RPA_GUIDE.md` — работа с PDF/Word/Excel/OCR/encryption
- `docs/AI_INTEGRATION.md` — LLM/RAG/PII/guardrails/caching
- `docs/CDC_GUIDE.md` — Change Data Capture (PG/Oracle/polling)
- `docs/DSL_COOKBOOK.md` — рецепты типовых pipelines
- `docs/ARCHITECTURE.md` — архитектура системы
- `docs/DEVELOPER_GUIDE.md` — гайд для разработчиков
- `docs/DEPLOYMENT.md` — docker + k8s deployment

**Регенерация docs/PROCESSORS.md:**
```bash
python tools/generate_processors_doc.py > docs/PROCESSORS.md
```

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
