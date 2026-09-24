# Contract-tests inventory — idempotency/inbox/outbox/schema-evolution (v5 P3)

> Инвентаризация per v5 §4 P3-15 «Contract-тесты idempotency/inbox/outbox/
> schema-evolution contract tests» — проверка гипотезы «пробелы».
> **Вывод: все четыре домена уже покрыты контракт-тестами; пробелов не
> обнаружено.** Evidence: файлы + свежий прогон (2026-09-24, 118 passed).

## Инвентарь

| Домен | Тесты (evidence) | Что покрывают |
|---|---|---|
| Idempotency | `tests/unit/core/idempotency/` (mutation-target, pyproject) | state machine PENDING→COMPLETED, key derivation, TTL |
| Outbox | `tests/unit/infrastructure/test_outbox_state_machine.py`, `test_w11_p1_1_outbox_crash_matrix.py` (ADR-0338), `services/messaging/test_outbox_monitor_proxy.py` | state machine, crash/retry матрица, монитор |
| Inbox | `tests/unit/infrastructure/eventing/test_inbox.py`, `messaging/test_outbox_dlq_wiring.py`, `test_dlq_lazy_init.py` | eventing inbox + DLQ wiring |
| Schema-evolution | `tests/unit/dsl/versioning/` (loader_integration, migration_registry), `dsl/engine/test_versioning.py` | apply_migrations до целевой apiVersion, реестр миграций, загрузчик |

Прогон объединённого набора: **118 passed** (4.78s).

## Гипотезы-пробелы, которые НЕ подтвердились

- «Inbox не покрыт» — покрыт (eventing test_inbox).
- «Schema-evolution нет контракт-тестов» — покрыт versioning-сьютом.
- «Outbox только wiring» — есть state machine + crash matrix (W11).

## Реальные остатки (за пределами инвентаризации)

1. Idempotency-тесты — Redis-зависимые части покрываются в интеграционном
   контуре (unit-часть зелёная после pollution-фикстуры).
2. Backfill/catchup — отдельный пункт V5 P3-13, ждёт ADR run-history store
   (не контракт-тест, а новый функционал).

## Рекомендация

Пункт V5 §4 P3-15 считать ЗАКРЫТЫМ инвентаризацией: контракт-тесты
присутствуют во всех четырёх доменах; при изменениях этих доменов —
не забывать прогонять перечисленные сьюты (входят в tests/unit
регрессию).
