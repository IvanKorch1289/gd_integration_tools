# Фаза IL1 — Infrastructure Layer P0 (фундамент)

- **Статус:** in-progress
- **Приоритет:** P0
- **ADR:** ADR-022 (Connector SPI)
- **Зависимости:** A3 (svcs DI), A4 (resilience consolidation), H4 (initial closure).
- **План:** `/root/.claude/plans/tidy-jingling-map.md` (раздел «Волна 1 — P0»).

## Цель

Привести инфраструктурный слой к единому SPI-контракту коннекторов (MuleSoft-
/Camel-style), внедрить RED client-metrics, замкнуть OTEL-инструментацию на
Kafka/RabbitMQ/Mongo/gRPC, добавить deep health probes, per-client circuit
breaker, Kafka idempotent producer, admin API для manual reload, унифицированный
PoolingProfile.

## Под-задачи

| № | Название | Блокер-для | Файлы |
|---|---|---|---|
| 1.1 | `InfrastructureClient` ABC + `ConnectorRegistry` | 1.3, 1.6, 1.7, вся Волна 2/3 | `src/infrastructure/clients/base_connector.py`, `src/infrastructure/registry.py` |
| 1.2 | Client Metrics (RED) | 2.7, 3.3-3.5, 3.6-3.8 | `src/infrastructure/observability/client_metrics.py` |
| 1.3 | OTEL auto-instrument full | — | `src/infrastructure/observability/otel_auto.py` (расш.) |
| 1.4 | Circuit Breaker на Redis/Mongo/Kafka | — | `src/infrastructure/clients/storage/*.py`, `messaging/kafka.py` |
| 1.5 | Kafka idempotent + transactional producer | 2.1 | `src/infrastructure/clients/messaging/kafka.py` |
| 1.6 | Deep health probes | — | `src/infrastructure/application/health_aggregator.py` |
| 1.7 | Admin API `/admin/connectors/*` | 2.4, 2.7 | `src/entrypoints/api/v1/endpoints/admin_connectors.py` |
| 1.8 | `PoolingProfile` dataclass | 1.1, 1.4, 2.3, 2.5, 2.6 | `src/core/config/pooling.py` |

## Definition of Done

- [ ] ADR-022 зафиксирован в `docs/adr/`.
- [ ] `src/core/config/pooling.py` с `PoolingProfile` pydantic-моделью.
- [ ] `src/infrastructure/clients/base_connector.py` с `InfrastructureClient` ABC + `HealthResult`.
- [ ] `src/infrastructure/registry.py` с `ConnectorRegistry` singleton.
- [ ] `src/infrastructure/observability/client_metrics.py` с 4 Prometheus метриками (RED + pool + circuit).
- [ ] `ClientMetricsMixin` встроен в ABC.
- [ ] OTEL auto-instrument расширен на aiokafka / aio-pika / motor / grpc-client; deps добавлены в `pyproject.toml`.
- [ ] Circuit breaker внедрён в Redis/Mongo/Kafka клиенты (threshold/recovery из PoolingProfile).
- [ ] Kafka producer: `enable_idempotence=True`, `acks=all`, `max_in_flight=5`.
- [ ] Outbox publisher использует `transactional_id=f"outbox-{instance_id}"`.
- [ ] `HealthAggregator.check_all(mode="fast"|"deep")` с deep-probes для Postgres/Redis/Kafka/Mongo/Rabbit/S3.
- [ ] Endpoint `GET /api/v1/health/components?mode=fast|deep` работает.
- [ ] Endpoint `POST /api/v1/admin/connectors/{name}/reload` (admin-only) работает.
- [ ] Endpoint `GET /api/v1/admin/connectors` возвращает список зарегистрированных.
- [ ] Хотя бы один клиент (Redis / Postgres) мигрирован на ABC как reference.
- [ ] `ruff check` зелёный.
- [ ] `make lint` зелёный.
- [ ] Deprecation shim для старых import-path (на 1 релиз).
- [ ] `docs/PROGRESS.md::IL1` → `done`.
- [ ] `docs/adr/PHASE_STATUS.yml::IL1` → `done`.
- [ ] Коммиты с префиксом `[phase:IL1]` (1 на под-задачу или сгруппированные).

## Как проверить локально

```bash
# 1. Guard'ы зелёные.
python3 tools/check_phase_order.py
python3 tools/check_deps_matrix.py
bash scripts/audit.sh IL1

# 2. Lint + type-check.
make lint
make type-check

# 3. Smoke.
docker compose up -d postgres redis
make run
curl -s http://localhost:8000/api/v1/health/components?mode=deep | jq
curl -s http://localhost:8000/metrics | grep -E '^infra_client_'
curl -s http://localhost:8000/api/v1/admin/connectors | jq
```

## Риски

- R1 (high): Migration shim для старых import-path — не сломать production (grep-gate).
- R9 (medium): Vault-rotation должен знать `vault_path` каждого клиента — явный
  параметр в `register()`.

Полный risk-регистр — в плане.

## Коммерческий референс

- MuleSoft 4.x `ConnectionProvider<T>` SPI.
- Apache Camel `Component`/`Endpoint` interface.
- WSO2 Carbon `AbstractConnector`.
- TIBCO BW 6 `AdapterLifecycle`.

## Следующая фаза

**IL2** — консолидация (Kafka через FastStream полностью, NotificationGateway
enterprise, ReconnectionStrategy, Vault hot-reload wiring, IMAP pool, HTTP
per-upstream профили, Streamlit dashboard).
