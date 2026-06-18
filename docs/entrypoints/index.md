# EntryPoints

FastAPI, gRPC, GraphQL, SOAP, REST, WebSocket, SSE, MQTT, MCP, CDC, Scheduler, Webhook.

## Архитектура

```
src/backend/entrypoints/
├── api/v1/endpoints/    # 28+ endpoint files (FastAPI)
├── graphql/             # GraphQL schema
├── grpc/                # gRPC services (.proto)
├── soap/                # SOAP (zeep)
├── mqtt/                # MQTT (aiokafka-style MqttSettings)
├── sse/                 # Server-Sent Events
├── websocket/           # WebSocket
├── http3/               # HTTP/3
├── stream/              # Streaming
├── express/             # Express-style middleware
├── middlewares/         # 16+ ASGI middlewares
├── mcp/                 # MCP gateway
├── filewatcher/         # File watcher (watchfiles)
├── cdc/                 # CDC ingress
├── scheduler/           # Cron scheduler
├── webhook/             # Webhook ingress
├── email/               # SMTP egress
└── asyncapi/            # AsyncAPI schema
```

## Facades (Rule 1)

- `AuthFacade` (S164 W35) — все auth через facade
- `StorageFacade` (S164 W37) — file/blob storage
- `UnifiedCacheFacade` (S165 W1) — cache with TTL
- `NotificationFacade` — email/telegram/push (in audit/facade)

## Middleware (16+ ASGI)

| Middleware | Описание | Sprint |
|---|---|---|
| `IPRestrictionMiddleware` | IP allowlist | S162 |
| `GlobalRateLimitMiddleware` | FastAPI-Limiter | S151 |
| `WSRateLimitMiddleware` | Per-WS token bucket | S164 W36 |
| `CircuitBreakerMiddleware` | Per-endpoint CB | S151 |
| `CORSMiddleware` | CORS | S56 |
| ... | ... | ... |

## См. также

- [ARCHITECTURE](../ARCHITECTURE.md)
- [AI](../ai/index.md)