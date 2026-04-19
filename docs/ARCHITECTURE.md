# Architecture

## Overview

GD Integration Tools — enterprise integration bus для автоматизации бизнес-процессов. 9 архитектурных слоёв, 15+ протоколов, 85+ DSL-процессоров (Apache Camel EIP + RPA UiPath-style + AI/ML + n8n/Benthos/Zapier patterns).

## Layers

```
┌─────────────────────────────────────────────────┐
│                 Entrypoints                      │
│  REST API │ GraphQL │ gRPC │ SOAP │ WebSocket   │
│  SSE │ MQTT │ MCP │ Webhooks │ File Watcher     │
│  CDC │ Email │ Streamlit Dashboard               │
├─────────────────────────────────────────────────┤
│              DSL Engine                          │
│  RouteBuilder │ Pipeline │ Processors            │
│  Exchange │ ExecutionContext │ Tracer             │
│  Hot Reload │ Console │ Plugin Registry          │
│  Templates │ Versioning │ Transforms             │
├─────────────────────────────────────────────────┤
│              Services                            │
│  Orders │ Files │ Tech │ SKB │ Dadata            │
│  Admin │ Analytics │ Search │ RAG                │
│  AI Agent │ Agent Memory │ Webhook Scheduler     │
├─────────────────────────────────────────────────┤
│           Infrastructure                         │
│  DB (Postgres) │ Redis │ S3 │ Kafka │ RabbitMQ   │
│  ClickHouse │ Elasticsearch │ FTP/SFTP │ SMTP    │
│  Vector Store │ Event Bus │ MCP Local Client     │
├─────────────────────────────────────────────────┤
│              Core                                │
│  Config │ DI │ Security │ Decorators │ Errors    │
└─────────────────────────────────────────────────┘
```

## Data Flow

### HTTP Request → Response
```
Client → Middleware (API Key, Rate Limit, IP) → Endpoint
  → ActionHandlerRegistry.dispatch()
    → Service.method()
      → Repository (DB/Redis/S3)
    → Response
```

### DSL Pipeline
```
Source → Exchange(Message) → [Processor₁ → Processor₂ → ... → ProcessorN]
  → Action dispatch → Service → Result
```

## Dependency Injection

Singletons регистрируются в `app.state` через `register_app_state()` при старте:

```python
# src/core/di.py
def register_app_state(app: FastAPI) -> None:
    app.state.api_key_manager = APIKeyManager()
    app.state.tracer = ExecutionTracer()
    # ...

# In endpoints:
async def endpoint(manager: APIKeyManager = Depends(get_api_key_manager)):
    ...
```

## Key Design Decisions

- **DSL-first**: все интеграции описываются через RouteBuilder
- **Multi-protocol**: один pipeline, любой транспорт
- **Feature Flags**: маршруты отключаются без деплоя
- **Multi-layer caching**: Redis → Memory → Disk с stale-on-error
- **PII masking**: reversible masking перед внешними LLM
- **Event Bus**: FastStream Redis для async pub/sub
