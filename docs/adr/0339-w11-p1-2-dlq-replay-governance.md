# ADR-0339 — DLQ replay governance (7-step flow + capability + rate limit + audit)

## Статус

**Accepted** (2026-09-23). Закрывает architectural gap "DLQ replay
governance" из стратегического анализа 2026-09-22.

## Контекст

Стратегический анализ (timestamp 1790089356160) выявил gap:

> «DLQ без безопасного replay становится накопителем ошибок. Следует
> добавить управляемую модель:
>
>     inspect → classify → redact → dry-run → replay → verify → archive
>
> Replay должен требовать capability, поддерживать ограничение скорости
> и автоматически сохранять исходный event ID, replay ID и причину
> оператора.»

В репо уже есть:
- ``src/backend/infrastructure/messaging/dlq_base.py`` — ``DLQEnvelope``,
  ``DLQReason``, ``DLQWriter`` Protocol.
- ``src/backend/services/ops/message_replay.py`` — inbound message replay
  (webhook/MQTT/email/gRPC), но НЕ DLQ-specific.
- ``src/backend/infrastructure/scheduler/dlq.py`` — APScheduler DLQ (events
  scheduler only), не generic DLQ governance.

Не хватает: **управляемой 7-шаговой модели** с governance hooks
(capability, rate limit, audit, dry-run, PII redaction).

## Решение

Создать ``src/backend/services/ops/dlq_replay_governance.py`` —
``DLQReplayGovernor`` класс с 7-шаговым flow + 4 governance hooks.

### 7 шагов (per strategic analysis)

| # | Метод | Описание |
|---|---|---|
| 1 | ``inspect(envelope)`` | Read-only snapshot для UI/admin (returns dict). |
| 2 | ``classify(envelope)`` | Auto-categorization (PII / FINANCIAL / INTERNAL / CONFIDENTIAL). |
| 3 | ``redact(envelope)`` | Strip PII из payload (regex-based, recursive для dict/list). |
| 4 | ``replay(dry_run=True)`` | Simulate без side-effects (no executor, no capability check). |
| 5 | ``replay(dry_run=False)`` | Real replay с capability + rate limit + audit. |
| 6 | ``verify(replay_id)`` | Проверка audit log (был ли replay успешен). |
| 7 | ``archive(envelope)`` | Move в cold storage (default: audit log entry). |

### Governance hooks

| Hook | Callback | Default |
|---|---|---|
| Capability check | ``(capability, operator_id) -> bool`` | None (skip, NOT for prod) |
| Rate limit | sliding window, in-memory deque | 10/minute (configurable) |
| Audit writer | ``(ReplayAuditEntry) -> None`` | in-memory list |
| Redactor | ``(payload) -> redacted`` | regex-based (6 PII patterns) |
| Replay executor | ``(redacted) -> bool`` | None (no-op, для тестов) |

### Auto-classification (Step 2)

Использует 6 regex patterns для PII detection:

| Pattern | Regex | Sensitivity |
|---|---|---|
| email | `\b[\w.+-]+@[\w-]+\.[\w.-]+\b` | PII |
| phone_ru | `\+7[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}\b` | PII |
| card_number | `\b(?:\d[ -]?){13,16}\d\b` | FINANCIAL |
| passport | `\b\d{4}[\s\-]\d{6}\b` | FINANCIAL |
| inn | `\b\d{10,12}\b` | PII |
| snils | `\b\d{3}-\d{3}-\d{3}\s?\d{2}\b` | PII |

Plus dlq_class marker ("financial" → FINANCIAL).

### Audit trail compliance

Каждый replay создаёт ``ReplayAuditEntry``:
- ``replay_id`` (UUID)
- ``original_event_id`` (из envelope.metadata.event_id или fallback на dlq_id)
- ``operator_id`` (mandatory)
- ``reason`` (mandatory, для compliance)
- ``correlation_id`` (для distributed tracing)
- ``timestamp``
- ``dry_run`` + ``success`` flags
- ``metadata`` (rate_limit_remaining, redacted, executor_error)

Production audit writer должен использовать WORM storage
(append-only Kafka topic или ClickHouse с аггрегацией).

### Exceptions (fail-closed)

- ``CapabilityDeniedError(capability, operator_id)`` — нет прав на ``dlq.replay``.
- ``RateLimitExceededError(limit, window_seconds, operator_id)`` — sliding window exceeded.
- ``ValueError`` — пустой ``reason`` (operator обязан объяснить зачем).

### Backward compat

- Не трогает существующий ``DLQEnvelope`` / ``DLQReason`` / ``DLQWriter``.
- Не заменяет ``message_replay.py`` (inbound message replay — другая concern).
- Standalone модуль — DI не требуется; hooks инжектятся через constructor.

## Альтернативы (отклонённые)

- **Расширить ``message_replay.py``** — отклонено: ``message_replay.py`` —
  inbound message replay (webhook/MQTT/email/gRPC), DLQ governance — другая
  concern (outbox failures, poison messages).
- **Использовать Temporal workflow для replay governance** — отклонено:
  Temporal overhead избыточен для single-step replay operation. Workflow
  подходит для multi-step durable replay (отдельная задача).
- **State machine representation (XState)** — отклонено: 7 шагов +
  governance — overkill для state machine; procedural API проще для
  понимания и тестирования.
- **Integration с ``DLQWriter`` Protocol** — отклонено: replay governor —
  read+classify+redact+replay, а ``DLQWriter`` — write-only API для
  добавления в DLQ. Complementary, не competing concerns.

## Последствия

### Плюсы

- **DLQ → безопасный replay** — 7 шагов с governance hooks.
- **Fail-closed**: capability denied → no executor call. Rate limit exceeded → no executor call.
- **Compliance-ready audit trail**: replay_id + operator_id + reason + correlation_id.
- **PII auto-redaction**: 6 patterns, recursive для dict/list.
- **Dry-run mode**: preview без side-effects для ops sanity check.
- **Existing ``DLQEnvelope`` consumers** могут использовать ``DLQReplayGovernor``
  для replay без изменений в producer-side code.

### Ограничения

- **In-memory rate limit** — single-process. Для multi-instance нужно
  Redis-based rate limiter (W11 backlog: extend ``RedisRateLimiter``).
- **In-memory audit log** — default. Production: WORM storage.
- **PII patterns — базовый набор** — 6 patterns. Custom deployment может
  добавить через ``redactor`` callback (dependency injection).
- **DLQEnvelope.version mismatch** — не покрыто (out of scope, решается
  в schema versioning layer).

### Production deployment path

1. Hook ``capability_check`` в ``core.security.capabilities.gate.check()``.
2. Hook ``audit_writer`` в ``infrastructure.audit.event_log.write()``
   (ClickHouse или Kafka append-only).
3. Hook ``replay_executor`` в ``infrastructure.messaging.broker.publish()``.
4. Rate limit → Redis-based через ``RedisRateLimiter`` (token bucket).
5. UI → Streamlit admin panel с inline editor для reason field.

## Verification

| Gate | Команда | Результат |
|---|---|---|
| compileall | `python -m compileall -q src/ extensions/ scripts/ tools/ tests/ testkit/` | EXIT 0 |
| check_python3_syntax | `python tools/checks/check_python3_syntax.py --root .` | EXIT 0 |
| ruff | `python -m ruff check src/backend/services/ops/dlq_replay_governance.py tests/...` | All checks passed |
| pytest (W11 P1-2) | `python -m pytest tests/unit/services/ops/test_w11_p1_2_dlq_replay_governance.py` | 35/35 passed |
| pytest (full) | 6 test files | 224/224 passed |
| smoke test | end-to-end PII redact + replay | OK (8 шагов за 1.5s) |

## Файлы

- `src/backend/services/ops/dlq_replay_governance.py` — новый модуль (~580 LOC)
- `tests/unit/services/ops/test_w11_p1_2_dlq_replay_governance.py` — 35 tests в 9 test classes
- `docs/adr/INDEX.md` — обновлён (131 → 132 ADRs)

## Tests coverage

| Test class | Tests | Что проверяет |
|---|---|---|
| TestInspect | 3 | Read-only snapshot, payload_size, None handling |
| TestClassify | 7 | card_number → FINANCIAL, email/phone/inn → PII, no-PII → INTERNAL, dlq_class override, capability_denied special case |
| TestRedact | 6 | email/card replacement, dict recursive, JSON string recursive, no-redaction, custom redactor |
| TestReplayDryRun | 3 | dry_run flag, capability skipped, rate limit skipped |
| TestReplayReal | 8 | executor call, empty reason ValueError, capability denied/allowed, rate limit, executor exception, audit trail, PII before executor |
| TestVerify | 2 | successful replay verification, nonexistent replay |
| TestArchive | 2 | archive_id UUID, audit entry created |
| TestAuditTrailCompliance | 3 | mandatory fields, event_id from metadata, fallback to dlq_id |
| TestEndToEndFlow | 1 | Full 7-step flow with PII payload |

## Crash matrix integration

| DLQ entry state | Governance path |
|---|---|
| PII payload (email/card) | redact → executor получает [REDACTED:*] |
| High retry count | classify → audit (no auto-replay) |
| Capability denied reason | CONFIDENTIAL → no redaction (auth errors are safe) |
| Empty reason | ValueError → no replay, no audit |

## Cross-cutting

- **W11 P0-4 (DomainProblem.to_dlq_envelope)** — DLQ envelopes для
  outbox/crash matrix могут быть consumed через DLQReplayGovernor.
- **W11 P1-1 (outbox crash matrix)** — poison message scenario (#7)
  приводит к DLQ, дальше — DLQReplayGovernor.archive + manual replay.
- **V15 R-V15-5 (WAF strict)** — outbound replay calls должны идти
  через WAF-фасад (отдельная governance concern, не covered здесь).

## Ссылки

- ADR-0338 — outbox crash matrix
- ADR-0337 — DomainProblem (canonical error contract)
- ADR-0335 / 0336 — configuration matrix gates
- Strategic analysis 2026-09-22: DLQ replay governance gap
- `src/backend/infrastructure/messaging/dlq_base.py` — DLQEnvelope source
- PROGRESS_LEDGER: `docs/roadmap/PROGRESS_LEDGER.md`
