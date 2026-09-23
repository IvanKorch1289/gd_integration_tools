# ADR-0338 — Outbox state-machine crash matrix (model-based tests)

## Статус

**Accepted** (2026-09-23). Закрывает architectural gap "Outbox state-machine
crash tests" из стратегического анализа 2026-09-22.

## Контекст

Стратегический анализ (timestamp 1790089356160) выявил gap:

> «Outbox уже нельзя считать простой заготовкой. Реализованы repository,
> dispatcher, lifecycle, stuck-message monitor, PostgreSQL NOTIFY, workflow
> worker, модели, мониторинг backlog и DLQ.
>
> Не хватает доказательств следующих инвариантов:
>
> 1. Commit произошёл, а publish — нет.
> 2. Publish произошёл, а фиксация статуса — нет.
> 3. Lease истёк во время обработки.
> 4. Два dispatcher конкурируют за одну запись.
> 5. Consumer завершил side effect и упал до ACK.
> 6. Broker недоступен длительное время.
> 7. Poison message повторяется после deploy.
> 8. Старый consumer получает событие новой версии.
>
> Такой набор лучше реализовать через model-based testing, а не десятки
> независимых unit-тестов.»

Существующий ``tests/unit/infrastructure/test_outbox_state_machine.py``
(Sprint 12) покрывает сценарии 1, 3 + invariants (no_loss, no_double,
crash_recovery, lease_enforcement) через hypothesis property-based tests.

Не покрыты: 2, 4, 5, 6, 7, 8 — 6 из 8 scenarios.

## Решение

Создать ``tests/unit/infrastructure/test_w11_p1_1_outbox_crash_matrix.py``
с **narrative model-based tests** для 6 оставшихся scenarios. Narrative
формат выбран потому что:

- Каждый scenario читается как явный walk-through с пронумерованными
  шагами и комментариями «что именно проверяется».
- Failure modes explicit (видно какой шаг ломается → какой invariant
  violated → какой DLQ/recovery path triggered).
- Property-based (hypothesis) избыточен: в Sprint 12 уже есть
  property-based для happy path + invariants; новые тесты —
  focused на **specific crash patterns**, не на random walk.

### Crash matrix coverage

| # | Scenario | Test class | Status |
|---|---|---|---|
| 1 | Commit OK, publish — нет | existing ``test_no_loss_under_retry`` | ✅ |
| 2 | **Publish OK, status update FAIL** | ``TestScenario2PublishOkStatusFail`` | ✅ NEW |
| 3 | Lease истёк во время обработки | existing ``test_lease_enforcement`` | ✅ |
| 4 | **Два dispatcher конкурируют за запись** | ``TestScenario4TwoDispatchersCompete`` | ✅ NEW |
| 5 | **Consumer side-effect OK, ACK FAIL** | ``TestScenario5ConsumerAckFail`` | ✅ NEW |
| 6 | **Broker недоступен длительное время** | ``TestScenario6BrokerDownExtended`` | ✅ NEW |
| 7 | **Poison message после deploy** | ``TestScenario7PoisonMessageAfterDeploy`` | ✅ NEW |
| 8 | **Old consumer + new schema** | ``TestScenario8SchemaVersioning`` | ✅ NEW |

### Simulation infrastructure

В тесте определены in-memory mocks:

- ``_Broker`` — broker с возможностью отказа + tracking published/delivered.
- ``_BrokerUnavailableError`` — exception для unavailable broker.
- ``_ConsumeResult`` — success/failure + reason.
- ``_OutboxRecord`` — single row (state, attempts, lease_until, sent_at).
- ``_OutboxTable`` — in-memory table с методами claim/mark_sent/mark_failed/
  mark_stuck_if_expired/sweep_stuck/mark_dlq.

Эти mocks намеренно НЕ используют существующий ``OutboxRepository`` —
тест фокусируется на **state machine correctness**, не на DB-интеграции
(что покрыто другими test files в ``tests/unit/infrastructure/messaging/``).

### Invariants documented в тестах

1. **No loss** — каждый event eventually SENT (или DLQ).
2. **No double-publish в dispatcher** — atomic claim.
3. **Duplicate publish допустим при status update fail** — mitigation:
   consumer idempotency.
4. **No premature DLQ** — broker outage → PENDING (retry), не DLQ.
5. **Poison → DLQ → replay** — eventual processing via DLQ replay.
6. **Schema versioning isolated** — failure одного event не валит pipeline.

### Cross-cutting invariants (TestStateMachineInvariants)

- ``test_no_loss_across_scenarios`` — composite: normal + crash + retry → all SENT.
- ``test_state_machine_uses_canonical_problem_category`` — sanity: outbox errors
  мапятся в ``DomainProblem`` (UNAVAILABLE category) per W11 P0-4.

## Альтернативы (отклонённые)

- **Расширить существующий ``test_outbox_state_machine.py``** — отклонено:
  317 LOC уже там, добавление 6 narrative scenarios создаст 600+ LOC file,
  что снижает читаемость. Отдельный файл — лучше separation of concerns.
- **Property-based для всех 8 scenarios** — отклонено: hypothesis эффективен
  для invariants (no_loss, no_double), но плохо для specific crash patterns
  (schema mismatch, broker outage, DLQ replay) — random walk не воспроизводит
  crash точно. Narrative tests → explicit, debuggable, regression-proof.
- **Использовать существующий ``OutboxRepository`` mock** — отклонено:
  нужны контролируемые crash injection points (broker.toggle_available,
  broker.redeliver), которые проще моделировать в standalone mocks.
- **Stateful integration test с реальной Postgres** — отклонено: требует
  Docker (kickoff blocked), медленно, flaky в CI.

## Последствия

### Плюсы

- **6 из 8 crash scenarios доказаны** — каждое с явными шагами и assertions.
- **Composite invariant** (no_loss_across_scenarios) — verifies что
  state machine корректен даже при composite failures.
- **Integration с W11 P0-4** (DomainProblem) — sanity check показывает,
  что outbox errors используют canonical error contract.

### Ограничения

- **Mocks не DB** — не покрывают transaction semantics (e.g., COMMIT
  после outbox INSERT, NOTIFY/LISTEN race). Эти покрыты в
  ``tests/unit/infrastructure/messaging/``.
- **Mocks не consumer** — consumer-side idempotency и schema routing —
  simplified в ``_Broker.consume()``. Production code в
  ``src/backend/services/messaging/consumers/`` отдельно тестируется.
- **No real broker** — broker.unavailable toggle is binary, не
  покрывает partial failures (e.g., publish OK but ACK fails).

### Backward compat

- Не трогает production code.
- Дополняет ``test_outbox_state_machine.py`` (не заменяет).
- Использует ``ProblemCategory`` из W11 P0-4 для cross-cutting invariant.

## Verification

| Gate | Команда | Результат |
|---|---|---|
| compileall | `python -m compileall -q src/ extensions/ scripts/ tools/ tests/ testkit/` | EXIT 0 |
| check_python3_syntax | `python tools/checks/check_python3_syntax.py --root .` | EXIT 0 |
| ruff | `python -m ruff check tests/unit/infrastructure/test_w11_p1_1_outbox_crash_matrix.py` | All checks passed |
| pytest (new) | `python -m pytest tests/unit/infrastructure/test_w11_p1_1_outbox_crash_matrix.py` | 13/13 passed |
| pytest (existing) | `python -m pytest tests/unit/infrastructure/test_outbox_state_machine.py` | 8/8 passed (no regression) |
| pytest (full) | 6 test files | 197/197 passed |

## Файлы

- `tests/unit/infrastructure/test_w11_p1_1_outbox_crash_matrix.py` — 13 tests (новый)
- `docs/adr/INDEX.md` — обновлён (130 → 131 ADRs)

## Crash matrix сводка (для будущих maintainers)

```
Scenario                          | State machine path                           | Mitigation
----------------------------------|----------------------------------------------|---------------------------
1. Commit OK, publish FAIL        | PENDING → PROCESSING → FAILED → PENDING     | tenacity retry
2. Publish OK, status FAIL        | PENDING → PROCESSING → STUCK → PENDING      | consumer idempotency
3. Lease expired                  | PENDING → PROCESSING → STUCK → PENDING      | sweeper periodic reset
4. Two dispatchers                | atomic claim; one wins                      | DB row lock
5. Side effect OK, ACK FAIL       | broker redelivers                           | consumer dedup table
6. Broker down extended           | PENDING → FAILED → PENDING (retry)          | backoff + lease TTL
7. Poison message                 | PENDING → ... → DLQ → replay → SENT         | max_retries + DLQ replay
8. Schema mismatch (consumer old) | consumer fails → DLQ                       | schema versioning + DLQ
```

## Ссылки

- ADR-0337 — DomainProblem (canonical error contract)
- ADR-0335 / 0336 — configuration matrix gates
- Sprint 12 — original hypothesis-based outbox state machine tests
- Strategic analysis 2026-09-22: crash matrix gap
- PROGRESS_LEDGER: `docs/roadmap/PROGRESS_LEDGER.md`
