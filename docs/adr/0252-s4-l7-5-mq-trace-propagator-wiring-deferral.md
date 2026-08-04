# ADR-0252: S-L7-5 W3C TraceContext MQ wiring — deferred (Sprint 4 L10)

**Date:** 2026-08-04
**Status:** Accepted (Sprint 4 / L10 Observability — formalize deferral)
**Sprint:** Sprint 4
**Deciders:** L10 Observability working group
**Supersedes:** — (clarifies ADR-0096 "DONE" claim, formalizes carryover)
**Related:** ADR-0096, `mq_trace_propagator.py`, KNOWN_ISSUES.md S-L7-5

## Context

Sprint 4 / L10 verification (item 4.5) проверила состояние
`infrastructure/observability/mq_trace_propagator.py:64-113`:

* Модуль объявлен ready (S18 W7, formalize в ADR-0096:137 как "PRODUCTION-READY")
* Docstring модуля честно говорит: "Wiring в Kafka/RabbitMQ producer/consumer —
  carryover S19+ (требует изменения 4+ файлов в infrastructure/messaging/)"
* `KNOWN_ISSUES.md:620 S-L7-5` явно фиксирует gap: "Кросс-сервисная
  trace_id propagation в Kafka/RabbitMQ headers отсутствует"

**Static-analysis (read-only, Sprint 4 verification):**

| Файл | Строка | Текущее поведение | W3C `traceparent`? |
|------|--------|-------------------|---------------------|
| `infrastructure/messaging/dlq/kafka_writer.py` | 76-80 | `send_and_wait(topic, value=..., key=...)` без `headers=` | **НЕТ** (kwarg отсутствует) |
| `infrastructure/messaging/dlq/rabbit_writer.py` | 61-72 | `Message(..., headers={"transport":..,"reason":..,"tenant_id":..,"trace_id": envelope.trace_id})` | **НЕТ** (только envelope-level `trace_id`) |
| `infrastructure/messaging/dlq/nats_writer.py` | 51-60 | `js.publish(subject, payload, headers={"Nats-Msg-Id":..,"X-Transport":..,"X-Tenant":..,"X-Trace":..})` | **НЕТ** (только envelope-level) |
| `infrastructure/clients/messaging/stream.py` | 305, 391 | `_inject_correlation_id_headers()` (только `correlation_id` из ContextVar) | **НЕТ** |
| `infrastructure/sources/mq.py` | 189-228 | `_on_message` НЕ вызывает `extract_from_headers()` | **НЕТ** (consumer side gap) |
| `infrastructure/messaging/outbox/repository.py` | 97-146 | `_merge_context_headers()` добавляет только `correlation_id` | **НЕТ** |

**Runtime verification (Sprint 4 новые regression-тесты):**

* `test_kafka_dlq_writer_does_not_pass_headers_kwarg` —
  KafkaDLQWriter.write НЕ передаёт `headers=` в `producer.send_and_wait`.
* `test_rabbit_dlq_writer_message_lacks_traceparent` —
  RabbitDLQWriter Message.headers НЕ содержит W3C `traceparent`.
* `test_nats_dlq_writer_message_lacks_traceparent` —
  NATSDLQWriter headers НЕ содержат W3C `traceparent`.

Все 6 статических + 3 runtime проверки **проходят**, документируя
текущее (отсутствующее) поведение.

**Propagator-модуль корректен (Sprint 4 новые positive-тесты):**

* `test_inject_populates_traceparent_with_active_span` —
  при active span `inject_into_headers` записывает валидный W3C
  `traceparent` формата `00-<32hex>-<16hex>-<flags>`.
* `test_extract_returns_context_with_matching_trace_id` —
  round-trip inject→extract сохраняет `trace_id`.
* `test_extract_lowercases_header_keys` —
  W3C case-insensitive headers корректно нормализуются.
* `test_extract_handles_bytes_values_for_kafka` —
  bytes-values (Kafka headers) конвертируются в str.

Модуль готов. Wiring gap — единственный blocker.

## Decision

**Признать S-L7-5 DEFERRED с Sprint 4.** Wiring модуля в Kafka/RabbitMQ
producer/consumer — **out of cycle Sprint 4 / L10**, оставить для
следующего sprint с явным scope ("M5: cross-service trace propagation").

**Причины:**

1. **Scope explosion.** Wiring требует правки 6 файлов (см. таблицу выше)
   в `infrastructure/messaging/` + `infrastructure/clients/messaging/`
   + `infrastructure/sources/`. Это выходит за границы Sprint 4 (L10
   Observability core: metrics, logging, audit, traces infrastructure
   внутри observability-домена).

2. **Public-API стабильность.** Текущие public-функции
   `inject_into_headers(headers: dict[str, str])` /
   `extract_from_headers(headers)` уже корректны (positive tests pass).
   Wiring требует ИЗМЕНЕНИЯ сигнатур / kwargs существующих методов
   (`KafkaDLQWriter.write`, `RabbitDLQWriter.write`, `StreamClient
   ._publish_*_immediately`, `MQSource._on_message`). Это нарушает
   "только новые defaulted kwargs" rule из Sprint 4 constraints.

3. **Cross-layer coupling.** Включение `mq_trace_propagator` в
   messaging-слой = hard dependency messaging → observability. Сейчас
   observability полностью изолирован (lazy import в
   `_inject_correlation_id_headers`). Wiring инвертирует эту
   dependency — недёшево, требует отдельного design review.

4. **Test coverage.** Sprint 4 уже ввёл **regression-локи** на
   текущий gap (см. test_mq_trace_propagator_wiring.py) — эти
   тесты будут **fail** при будущем wiring, форсируя обновление
   + добавление positive round-trip тестов с реальным брокером.

**Action items:**

| # | Item | Owner | Sprint |
|---|------|-------|--------|
| 1 | Regression-локи на gap (negative tests) — DONE Sprint 4 | L10 WG | Sprint 4 |
| 2 | Positive tests propagator round-trip — DONE Sprint 4 | L10 WG | Sprint 4 |
| 3 | ADR-0096 строка 47-50 (claim "DONE MQ publish") — REVISIT | L10 WG | Sprint 4 |
| 4 | Future wiring sprint — OPEN | next sprint | TBD |

## Consequences

### Positive

* Sprint 4 закрыт без cross-layer risk: добавлены только
  observability-domain тесты (не трогаем messaging/infrastructure).
* Regression-локи (`test_mq_trace_propagator_wiring.py:9`) документируют
  gap как известное поведение — никто случайно не «починит» его без
  awareness.
* ADR-0096 "DONE" claim теперь корректно прочитан: модуль готов,
  wiring — deferred (Sprint 4 explicit acknowledgment).

### Negative

* End-to-end distributed tracing через message broker **по-прежнему
  разорван** в production. Downstream consumer получает свежий
  trace_id (без parent), не связанный с producer-span.
* ADR-0096 строка 47-50 содержит неточный claim "W3C traceparent в
  Kafka/RabbitMQ/NATS headers DONE" — должен быть REVISED.

### Neutral

* 1 новый тест-файл (test_mq_trace_propagator_wiring.py: 9 тестов).
* 1 тест-файл усилен (test_observability_cardinality_tenant.py:
  +4 теста на propagator round-trip).
* Никаких изменений в `infrastructure/messaging/*` или
  `infrastructure/observability/mq_trace_propagator.py`.

## Implementation Status

| Component | Status | Notes |
|-----------|--------|-------|
| `mq_trace_propagator.py` (inject/extract) | DONE | S18 W7, ADR-0096:137 |
| Propagator round-trip tests | DONE | Sprint 4 |
| Wiring in Kafka producer/consumer | **TODO** | next sprint (this ADR) |
| Wiring in Rabbit producer/consumer | **TODO** | next sprint (this ADR) |
| Wiring in NATS producer/consumer | **TODO** | next sprint (this sprint) |
| Wiring in MQSource._on_message (extract) | **TODO** | next sprint |
| Wiring in StreamClient.publish_to_{kafka,rabbit} | **TODO** | next sprint |
| Wiring in OutboxRepository.enqueue | **TODO** | next sprint |
| Regression locks on current gap | DONE | Sprint 4 (this ADR) |

## References

* `src/backend/infrastructure/observability/mq_trace_propagator.py:64-113`
  — propagator-модуль (carryover S19+ docstring:42-43)
* `src/backend/infrastructure/messaging/dlq/kafka_writer.py:76-80`
* `src/backend/infrastructure/messaging/dlq/rabbit_writer.py:61-72`
* `src/backend/infrastructure/messaging/dlq/nats_writer.py:51-60`
* `src/backend/infrastructure/clients/messaging/stream.py:305,391`
* `src/backend/infrastructure/sources/mq.py:189-228`
* `src/backend/infrastructure/messaging/outbox/repository.py:97-146`
* `tests/unit/infrastructure/observability/test_mq_trace_propagator_wiring.py`
  — regression-локи на текущий gap
* `tests/unit/infrastructure/observability/test_observability_cardinality_tenant.py`
  — positive round-trip тесты propagator'а
* `docs/adr/0096-correlation-otel-traceid-binding.md:47-50` — REVISIT claim
* `.claude/KNOWN_ISSUES.md:620` — S-L7-5 explicit gap entry
* Sprint 4 / L10 Observability verification
