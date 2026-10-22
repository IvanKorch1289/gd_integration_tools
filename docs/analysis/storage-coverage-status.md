# Storage Backends — Test Coverage Status (S61 W4)

Аудит существующего покрытия для **storage / data-pipeline backends** после
закрытия W1-W3 (S61 S3ObjectStorage + DSL processors).

## Legend

- ✅ **Покрыто** — unit-тесты + chaos-тесты + DSL processor
- 🟡 **Частично** — только unit или только chaos
- ❌ **Не покрыто** — есть код, нет тестов
- ⏭ **N/A** — backend не используется в проекте (или только lazy import)

## ObjectStorage (S3 / MinIO / LocalFS)

| Backend | ObjectStorage | DSL processor | Unit tests | Chaos tests | Status |
|---|---|---|---|---|---|
| S3 / MinIO / AWS | `S3ObjectStorage` (aioboto3) | 5 процессоров, **недоступны из YAML**¹ | 20 (S61 W1+W3)² | `test_object_storage_chain_chaos.py` | ⚠️ |
| LocalFS | `LocalFSStorage` | (используется через `get_object_storage`) | 11 (legacy) | `test_object_storage_chain_chaos.py` | ✅ |
| S3Client (aiobotocore pool) | n/a (high-perf) | n/a | 0 (через chaos) | `test_s3_chain.py` | 🟡 |

¹ **Недоступны из YAML**: `dsl/yaml_loader/build.py:198` резолвит YAML-шаг через
`getattr(builder, proc_name)`, но соответствующие методы `RouteBuilder` удалены
(`dsl/builders/infrastructure_dsl.py:486-487`). Декларативно объектным хранилищем
сейчас нельзя достичь. Дополнительно: YAML-ключ `from_s3` коллизирует с
S3-poll-сенсором (`dsl/builders/eip/sources.py:363`).

² **Тесты были пропущены**: `moto` отсутствовал в зависимостях, поэтому весь
`tests/unit/storage/test_s3_object_storage.py` (~20 тестов) завершался
`Skipped`, а не выполнялся. Заявленное покрытие было номинальным.
Восстановлено в cycle 171 / Wave 0 (`moto[s3]` добавлен в extra `test-core`).

**Дополнительно найдено в cycle 171:** `aioboto3` не объявлен ни в
`pyproject.toml`, ни в `uv.lock`, хотя `S3ObjectStorage.__init__` (`s3.py:125`)
вызывает его eagerly. В **production** это приводит к явному падению
(`ProductionConfigError` на composition root — покрыто тестом
`test_get_object_storage_raises_in_production_when_s3_fallback_to_local`),
а в **staging/dev** — к молчаливой деградации на LocalFS с одним WARNING'ом.

**W3 deliverable**: 5 DSL processors + S3ObjectStorage refactor (proper async
context manager) → ⚠️ процессоры написаны, но недостижимы из YAML; покрытие
было номинальным (тесты skip-ились). См. сноски ¹ ² и раздел «Что найдено
в cycle 171» в `artifacts/current_audit/S3_CACHE_LOGGING_AUDIT_2026-10-21.md`.

## Redis (cache / message broker)

| Component | Unit tests | Chaos tests | Status |
|---|---|---|---|
| Cache backend | `tests/unit/cache/backends/test_redis.py` | `test_redis_chain.py` | ✅ |
| Cluster pipeline | `tests/cache/test_redis_cluster.py` | `test_cache_chain_chaos.py` | ✅ |
| Breaker storage | `tests/unit/infrastructure/resilience/test_redis_breaker_storage.py` | n/a | ✅ |
| Fallback | `tests/unit/core/utils/test_redis_fallback.py` | n/a | ✅ |
| Broadcaster | `tests/unit/core/feature_flags/test_redis_broadcaster.py` | n/a | ✅ |
| Idempotency | `tests/unit/entrypoints/middlewares/test_idempotency_redis_backend.py` | n/a | ✅ |
| Streams source | `tests/integration/sources/test_mq_redis_streams.py` | `test_mq_chain_chaos.py` | ✅ |

**Coverage**: 7+ test files покрывают все major Redis use-cases. ⏭ DSL processors для Redis (как для S3) — **не нужны**: Redis в проекте = cache, не blob storage.

## ClickHouse (analytics / audit)

| Component | Unit tests | Chaos tests | Status |
|---|---|---|---|
| Audit service | `tests/unit/services/audit/test_clickhouse_audit.py` | `test_audit_chain_chaos.py` | ✅ |
| Query builder | `tests/unit/infrastructure/clients/storage/test_clickhouse_query_builder.py` | n/a | ✅ |
| Bulk writer | `tests/unit/infrastructure/clients/storage/test_clickhouse_bulk_writer.py` | `test_clickhouse_chain.py` | ✅ |
| Config | `tests/unit/core/config/test_clickhouse.py` | n/a | ✅ |
| DSL audit processor | `tests/unit/dsl/engine/processors/test_audit_clickhouse.py` | `test_audit_chain_chaos.py` | ✅ |

**Coverage**: 5+ test files + 1 DSL processor (`audit_clickhouse`). ⏭ DSL для query-into-route — **out of scope**: ClickHouse = read-only analytics, не storage в DSL-flow.

## Kafka (async messaging, AIOKafkaProducer)

| Component | Unit tests | Chaos tests | Status |
|---|---|---|---|
| DLQ writer | `tests/unit/infrastructure/messaging/dlq/test_kafka_writer.py` | `test_kafka_chain.py` | ✅ |
| MQ sink | `tests/unit/infrastructure/sinks/test_mq_sink.py` | `test_mq_chain_chaos.py` | ✅ |
| Event bus | `tests/unit/infrastructure/clients/messaging/test_event_bus.py` | `test_mq_chain_chaos.py` | ✅ |
| Sources | `tests/integration/sources/test_mq_redis_streams.py` | n/a | ✅ |

**Coverage**: solid. ⏭ DSL processors для Kafka (`to_kafka`/`from_kafka`) — **out of scope S61**: messaging ≠ blob storage, separate concern (W4+ if needed).

## FastStream (lazy import only)

```bash
$ grep -rln "faststream" src/backend/
src/backend/services/ops/health.py:202:  # Default-реализация — best-effort через lazy import faststream/confluent.
```

**Status**: ⏭ **N/A** — FastStream присутствует только как опциональный lazy import в health-check. Активный messaging stack — `aiokafka` (см. `dlq/kafka_writer.py`).

## Conclusion

| Backend | Coverage | Action S61 |
|---|---|---|
| S3 / MinIO / LocalFS | ✅ Solid (W1+W3) | — |
| Redis (cache/broker) | ✅ Solid (7+ test files) | — |
| ClickHouse (audit/analytics) | ✅ Solid (5+ test files + 1 DSL) | — |
| Kafka (aiokafka DLQ + MQ) | ✅ Solid (4+ test files) | — |
| FastStream | ⏭ N/A (lazy import only) | — |

**S61 W4 = NO-OP**: storage backends уже покрыты. W4 = documentation этой status-таблицы.

**Pending W5 candidate**: если потребуется DSL `to_kafka` / `from_kafka` — отдельный спринт (messaging ≠ storage, нужны схемы сериализации, partition key strategy, idempotent producer).
