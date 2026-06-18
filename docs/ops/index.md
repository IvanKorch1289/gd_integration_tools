# Operations

Observability, monitoring, logging, audit, health.

## Архитектура

```
src/backend/ops/
├── data_quality/        # DQ rules + violations
├── lineage/             # Data lineage tracking
└── semantic_cache/      # L2/L3 semantic cache

src/backend/infrastructure/
├── observability/       # Prometheus, OpenTelemetry
├── monitoring/          # Health checks
├── logging/             # Structured logging (Graylog GELF)
└── audit/               # ClickHouse audit + OTel
```

## Health checks

Каждый клиент имеет `healthcheck()`:
- HTTP (httpx)
- SMTP
- Redis
- S3 (S165 W3 CB integration)
- gRPC (S165 W6 CB integration)
- Kafka (S165 W5 CB integration)

## Resilience (Rule 6)

| Клиент | Pool | CB | Retry | Healthcheck |
|---|---|---|---|---|
| HTTP | ✓ | ✓ | ✓ | ✓ |
| SMTP | ✓ | ✓ | ✓ | ✓ |
| Redis | ✓ | partial | ✓ | ✓ |
| S3 | ✓ | **✓ (S165 W3)** | ✓ | ✓ |
| gRPC | ✓ | **✓ (S165 W6)** | ✓ | ✓ |
| Kafka | ✓ | **✓ (S165 W5)** | ✓ | ✓ |
| PostgreSQL | ✓ | ✓ | partial | ✓ |
| MongoDB | ✓ | – | – | ✓ |

## Fallback chains

- **Cache**: Redis → Memory → Disk (S165 W1 FallbackCacheFacade)
- **Storage**: S3 → LocalFS (S164 W37 FallbackStorageDecorator)
- **Logging**: Graylog → Disk (auto-fallback)

## Audit

ClickHouse audit + OTel export. Per master_prompt §0: all actions audited.

## Metrics

Prometheus + Starlette Exporter. OpenTelemetry traces.

## Logging

- Stdlib structured logging
- Graylog GELF backend
- Per-module get_logger()
- Auto-fallback на disk при недоступности Graylog

## См. также

- [ARCHITECTURE](../ARCHITECTURE.md)