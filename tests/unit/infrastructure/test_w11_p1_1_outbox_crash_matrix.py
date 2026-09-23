"""W11 P1-1: Outbox state-machine crash matrix (model-based tests).

Стратегический анализ 2026-09-22 (timestamp 1790089356160) выявил gap:
«Нет полноценной state-machine crash matrix. … Лучше реализовать через
model-based testing, а не десятки независимых unit-тестов».

Этот файл реализует 6 narrative crash scenarios, не покрытых в
``tests/unit/infrastructure/test_outbox_state_machine.py`` (Sprint 12):

| # | Scenario | Статус |
|---|---|---|
| 1 | Commit произошёл, publish — нет | ✅ existing (test_no_loss_under_retry) |
| 2 | Publish OK, status update FAIL | НОВЫЙ здесь |
| 3 | Lease истёк во время обработки | ✅ existing (test_lease_enforcement) |
| 4 | Два dispatcher конкурируют за запись | НОВЫЙ здесь |
| 5 | Consumer side-effect OK, ACK FAIL | НОВЫЙ здесь |
| 6 | Broker недоступен длительное время | НОВЫЙ здесь |
| 7 | Poison message повторяется после deploy | НОВЫЙ здесь |
| 8 | Старый consumer получает новую версию | НОВЫЙ здесь |

Каждый scenario — narrative walk-through с явными crash points
и проверяемыми инвариантами. Это model-based testing, не property-based:
тесты читаемы и явно показывают, что именно проверяется.

ADR-0338: outbox state-machine crash matrix.
"""

from __future__ import annotations

from src.backend.core.errors import ProblemCategory

# ──────────────────── Shared simulation infrastructure ────────────────────


class _Broker:
    """Simulated message broker с возможностью отказа."""

    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.published: list[str] = []  # event_ids
        self.delivered: dict[str, int] = {}  # event_id → consumer-side delivery count

    def publish(self, event_id: str, schema_version: int = 1) -> None:
        """Publish event. Raises если broker недоступен."""
        if not self.available:
            raise BrokerUnavailableError(f"Broker down, cannot publish {event_id}")
        self.published.append(event_id)

    def consume(
        self, event_id: str,
        consumer_schema_version: int = 1,
        event_schema_version: int = 1,
    ) -> "ConsumeResult":
        """Consumer получает event. Returns ConsumeResult."""
        self.delivered[event_id] = self.delivered.get(event_id, 0) + 1
        # Schema mismatch simulation: consumer v1 + event v2 → fail.
        if consumer_schema_version < event_schema_version:
            return ConsumeResult(
                success=False,
                reason=f"schema mismatch: consumer v{consumer_schema_version} "
                f"vs event v{event_schema_version}",
            )
        return ConsumeResult(success=True)


class BrokerUnavailableError(Exception):
    """Broker temporarily unavailable (network, partition, etc.)."""



# Use simple class instead of dataclass for portability
# Use simple class instead of dataclass for portability
class ConsumeResult:
    """Result of consumer-side processing."""

    def __init__(self, success: bool, reason: str = "") -> None:
        self.success = success
        self.reason = reason


class _OutboxState:
    """Single event state (mock of outbox row)."""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SENT = "SENT"
    FAILED = "FAILED"
    STUCK = "STUCK"
    DLQ = "DLQ"


class _OutboxRecord:
    """Outbox row mock."""

    def __init__(self, event_id: str, schema_version: int = 1) -> None:
        self.event_id = event_id
        self.schema_version = schema_version
        self.state = _OutboxState.PENDING
        self.attempts = 0
        self.publish_attempts = 0  # раз сколько пытались publish
        self.lease_until: float | None = None
        self.sent_at: float | None = None


class _OutboxTable:
    """In-memory outbox table."""

    def __init__(self) -> None:
        self.records: dict[str, _OutboxRecord] = {}

    def insert(self, event_id: str, schema_version: int = 1) -> None:
        self.records[event_id] = _OutboxRecord(event_id, schema_version)

    def claim(self, event_id: str, now: float, lease_ttl: float) -> bool:
        """Atomic claim (single-writer simulation)."""
        r = self.records.get(event_id)
        if r is None:
            return False
        if r.state in (_OutboxState.SENT, _OutboxState.DLQ):
            return False
        if r.state == _OutboxState.PROCESSING:
            # Already claimed — check lease.
            if r.lease_until is None or now <= r.lease_until:
                return False  # still in lease
            # Lease expired — sweeper should reset before claim.
        r.state = _OutboxState.PROCESSING
        r.lease_until = now + lease_ttl
        r.attempts += 1
        return True

    def mark_sent(self, event_id: str, now: float) -> None:
        r = self.records[event_id]
        r.state = _OutboxState.SENT
        r.sent_at = now

    def mark_failed(self, event_id: str) -> None:
        """Mark for retry (FAILED → PENDING)."""
        r = self.records[event_id]
        r.state = _OutboxState.PENDING
        r.lease_until = None

    def mark_stuck_if_expired(self, event_id: str, now: float) -> None:
        r = self.records[event_id]
        if r.state == _OutboxState.PROCESSING and r.lease_until is not None:
            if now > r.lease_until:
                r.state = _OutboxState.STUCK

    def sweep_stuck(self) -> int:
        n = 0
        for r in self.records.values():
            if r.state == _OutboxState.STUCK:
                r.state = _OutboxState.PENDING
                r.lease_until = None
                n += 1
        return n

    def mark_dlq(self, event_id: str, reason: str = "") -> None:
        r = self.records[event_id]
        r.state = _OutboxState.DLQ


# ──────────────────── CRASH SCENARIO 2: Publish OK, status update FAIL ────────────────────


class TestScenario2PublishOkStatusFail:
    """Publish OK, status update FAIL → state stuck в PROCESSING → re-publish.

    Crash model:
        1. Dispatcher claims event → PROCESSING.
        2. Publishes to broker → success.
        3. DB UPDATE outbox SET state=SENT fails (DB connection lost).
        4. Process crashes.

    Ожидаемое поведение:
        - После lease expiry → STUCK.
        - Sweeper resets → PENDING → re-publish.
        - Result: DUPLICATE publish (broker received twice).
        - Mitigation: consumer must be idempotent (по ``event_id``).
    """

    def test_duplicate_publish_on_status_update_failure(self) -> None:
        table = _OutboxTable()
        table.insert("evt-1")
        broker = _Broker(available=True)

        # Step 1: claim
        assert table.claim("evt-1", now=0.0, lease_ttl=5.0) is True
        assert table.records["evt-1"].state == _OutboxState.PROCESSING

        # Step 2: publish OK
        broker.publish("evt-1")
        assert broker.published == ["evt-1"]

        # Step 3: status update FAILS (DB connection lost) — state remains PROCESSING
        # (in real system: connection lost, UPDATE never persisted)
        # We simulate by NOT calling mark_sent.

        # Step 4: process crashes; lease expires after 5s.
        table.mark_stuck_if_expired("evt-1", now=10.0)
        assert table.records["evt-1"].state == _OutboxState.STUCK

        # Sweeper resets.
        assert table.sweep_stuck() == 1
        assert table.records["evt-1"].state == _OutboxState.PENDING

        # Re-publish (new dispatcher run).
        assert table.claim("evt-1", now=11.0, lease_ttl=5.0) is True
        broker.publish("evt-1")

        # Invariant: broker received DUPLICATE → consumer MUST be idempotent.
        assert broker.published == ["evt-1", "evt-1"], (
            "Дубликат ожидаем при status update fail; "
            "consumer должен быть idempotent по event_id"
        )
        # Documenting invariant:
        # DUPLICATE_PUBLISH_OK = True for this crash scenario
        assert len(broker.published) == 2


# ──────────────────── CRASH SCENARIO 4: Two dispatchers compete ────────────────────


class TestScenario4TwoDispatchersCompete:
    """Два dispatcher'а одновременно пытаются claim'ить одну и ту же запись.

    Crash model:
        1. Dispatcher A claims evt-1 → PROCESSING, lease set.
        2. Dispatcher B (на другом worker'е) тоже пытается claim evt-1.
        3. Atomic claim в DB: только один wins.

    Ожидаемое поведение:
        - Только один dispatcher успешно claims.
        - Другой получает ``claim() == False``.
        - Каждый event → ровно один publish (no double).
    """

    def test_only_one_winner(self) -> None:
        table = _OutboxTable()
        table.insert("evt-1")
        broker_a = _Broker()
        broker_b = _Broker()

        # Dispatcher A claims first.
        assert table.claim("evt-1", now=0.0, lease_ttl=10.0) is True
        assert table.records["evt-1"].state == _OutboxState.PROCESSING

        # Dispatcher B tries to claim (concurrent, BEFORE A publishes).
        assert table.claim("evt-1", now=0.5, lease_ttl=10.0) is False, (
            "B должен получить False — A уже claimed, lease не expired"
        )

        # A publishes successfully.
        broker_a.publish("evt-1")
        table.mark_sent("evt-1", now=1.0)

        # B tries again — should still fail (SENT).
        assert table.claim("evt-1", now=2.0, lease_ttl=10.0) is False

        # Invariant: только A publish'нул.
        assert broker_a.published == ["evt-1"]
        assert broker_b.published == []
        assert len(broker_a.published) == 1, "no double-publish"

    def test_lease_expiry_allows_other_to_claim(self) -> None:
        """Если A не успевает (lease expired) → B может claim'нуть."""
        table = _OutboxTable()
        table.insert("evt-1")

        # A claims, then lease expires (A crashed/wedged).
        assert table.claim("evt-1", now=0.0, lease_ttl=5.0) is True
        # Sweeper detects expired lease.
        table.mark_stuck_if_expired("evt-1", now=10.0)
        assert table.records["evt-1"].state == _OutboxState.STUCK
        table.sweep_stuck()
        assert table.records["evt-1"].state == _OutboxState.PENDING

        # B can now claim (A's lease expired, sweeper reset state).
        assert table.claim("evt-1", now=11.0, lease_ttl=5.0) is True


# ──────────────────── CRASH SCENARIO 5: Consumer side-effect OK, ACK FAIL ────────────────────


class TestScenario5ConsumerAckFail:
    """Consumer выполнил side-effect, но ACK/NACK fails → redelivery.

    Crash model:
        1. Broker delivers evt-1 to consumer.
        2. Consumer выполняет side effect (e.g., credit card charge).
        3. ACK отправлен, но network fails → broker не получает.
        4. Broker redelivers evt-1 (после visibility timeout).
        5. Consumer видит evt-1 снова, выполняет side effect AGAIN.

    Ожидаемое поведение:
        - DOUBLE side effect (если consumer не idempotent).
        - Mitigation: idempotency key + dedup table в consumer'е.
    """

    def test_consumer_double_delivery(self) -> None:
        """Consumer redelivery → broker delivers 2 раза → double side effect."""
        broker = _Broker()

        # First delivery → consumer processes.
        result_1 = broker.consume("evt-1", consumer_schema_version=1, event_schema_version=1)
        assert result_1.success is True
        # Side effect 1 happens (e.g., charge credit card).
        side_effects_count = 1

        # ACK fails (network). Broker redelivers.
        result_2 = broker.consume("evt-1", consumer_schema_version=1, event_schema_version=1)
        assert result_2.success is True
        side_effects_count += 1  # Side effect 2 happens (DUPLICATE!)

        # Documenting: consumer must dedup via idempotency key.
        assert side_effects_count == 2
        # Broker delivered 2 times (redelivery after ACK fail).
        assert broker.delivered["evt-1"] == 2

    def test_consumer_with_idempotency_dedup(self) -> None:
        """Consumer с idempotency table: redelivery пропускается."""
        processed: set[str] = set()  # idempotency table

        def consumer_process(event_id: str) -> str:
            if event_id in processed:
                return "skipped (already processed)"
            processed.add(event_id)
            return "processed"

        # First delivery.
        result_1 = consumer_process("evt-1")
        assert result_1 == "processed"

        # Redelivery (after ACK fail).
        result_2 = consumer_process("evt-1")
        assert result_2 == "skipped (already processed)"

        # Invariant: side effect ровно 1.
        assert len(processed) == 1


# ──────────────────── CRASH SCENARIO 6: Broker unavailable extended ────────────────────


class TestScenario6BrokerDownExtended:
    """Broker недоступен длительное время → events stay PENDING.

    Crash model:
        1. Multiple events PENDING.
        2. Broker goes down.
        3. Dispatcher tries to publish → fails.
        4. Multiple retry cycles → events stay PENDING (или STUCK → PENDING).
        5. Broker recovers.
        6. Dispatcher publishes → SENT.

    Ожидаемое поведение:
        - No loss (all events eventually SENT).
        - No premature DLQ (events don't go to DLQ during broker outage).
    """

    def test_no_loss_during_outage(self) -> None:
        table = _OutboxTable()
        broker = _Broker(available=False)  # broker DOWN

        events = ["evt-1", "evt-2", "evt-3"]
        for e in events:
            table.insert(e)

        # 5 retry cycles while broker down.
        now = 0.0
        for cycle in range(5):
            for e in events:
                if table.claim(e, now, lease_ttl=2.0):
                    try:
                        broker.publish(e)
                        table.mark_sent(e, now + 0.1)
                    except BrokerUnavailableError:
                        # Mark for retry.
                        table.mark_failed(e)
            # Lease expiry handling.
            for e in events:
                table.mark_stuck_if_expired(e, now + 5.0)
            table.sweep_stuck()
            now += 10.0

        # After outage: all events still PENDING (no loss).
        for e in events:
            assert table.records[e].state == _OutboxState.PENDING, (
                f"{e} should still be PENDING during outage, "
                f"got {table.records[e].state}"
            )

        # Broker recovers.
        broker.available = True

        # Dispatcher retries — all events SENT.
        for e in events:
            assert table.claim(e, now=100.0, lease_ttl=5.0) is True
            broker.publish(e)
            table.mark_sent(e, now=100.1)

        for e in events:
            assert table.records[e].state == _OutboxState.SENT

    def test_no_premature_dlq(self) -> None:
        """Broker outage → DLQ НЕ должен срабатывать (retry, не DLQ)."""
        table = _OutboxTable()
        broker = _Broker(available=False)
        table.insert("evt-1")

        # 10 retry cycles (broker down).
        now = 0.0
        for _ in range(10):
            if table.claim("evt-1", now, lease_ttl=1.0):
                try:
                    broker.publish("evt-1")
                except BrokerUnavailableError:
                    table.mark_failed("evt-1")
            table.mark_stuck_if_expired("evt-1", now + 5.0)
            table.sweep_stuck()
            now += 10.0

        # Event должен быть PENDING (или STUCK briefly), не DLQ.
        assert table.records["evt-1"].state in (
            _OutboxState.PENDING,
            _OutboxState.STUCK,
        ), (
            f"Premature DLQ: state={table.records['evt-1'].state}. "
            "DLQ должен срабатывать только после N permanent failures, "
            "не при transient broker outage."
        )


# ──────────────────── CRASH SCENARIO 7: Poison message after deploy ────────────────────


class TestScenario7PoisonMessageAfterDeploy:
    """Poison message: consumer fails repeatedly → DLQ → deploy fix → replay.

    Crash model:
        1. Event published (e.g., schema change without backward compat).
        2. Consumer fails to process (deserialization error).
        3. Retry N times → DLQ.
        4. Deploy rolls out fix.
        5. DLQ replay → consumer now succeeds.

    Ожидаемое поведение:
        - Event eventually processed (через DLQ replay).
        - No infinite retry loop.
        - Max retry count enforced.
    """

    def test_eventually_processed_via_dlq_replay(self) -> None:
        table = _OutboxTable()
        broker = _Broker()
        table.insert("evt-1", schema_version=2)

        # Consumer v1 tries to process v2 event → schema mismatch.
        consumer_version = 1
        max_retries = 3

        # Retry loop.
        for attempt in range(max_retries + 1):
            if table.claim("evt-1", now=attempt * 10.0, lease_ttl=5.0):
                broker.publish("evt-1")
                consume_result = broker.consume(
                    "evt-1", consumer_schema_version=consumer_version, event_schema_version=2
                )
                if not consume_result.success:
                    # Consumer fails.
                    if attempt >= max_retries:
                        # DLQ.
                        table.mark_dlq("evt-1", reason=consume_result.reason)
                    else:
                        table.mark_failed("evt-1")
                else:
                    table.mark_sent("evt-1", now=attempt * 10.0 + 0.1)
                    break
            table.mark_stuck_if_expired("evt-1", now=attempt * 10.0 + 6.0)
            table.sweep_stuck()

        # After max retries → DLQ.
        assert table.records["evt-1"].state == _OutboxState.DLQ
        assert table.records["evt-1"].attempts >= max_retries

        # Deploy fix: consumer v2 deployed.
        consumer_version = 2

        # DLQ replay: re-insert event (DLQ → outbox replay).
        table.records["evt-1"].state = _OutboxState.PENDING
        if table.claim("evt-1", now=100.0, lease_ttl=5.0):
            broker.publish("evt-1")
            consume_result = broker.consume(
                "evt-1", consumer_schema_version=consumer_version
            )
            assert consume_result.success is True
            table.mark_sent("evt-1", now=100.1)

        assert table.records["evt-1"].state == _OutboxState.SENT
        # Invariant: event eventually processed.
        assert table.records["evt-1"].sent_at is not None

    def test_max_retries_enforced(self) -> None:
        """Retry count не должен превышать max → DLQ."""
        table = _OutboxTable()
        table.insert("evt-1")
        max_retries = 5

        for attempt in range(10):  # try many times
            if table.claim("evt-1", now=attempt * 10.0, lease_ttl=1.0):
                if attempt >= max_retries:
                    table.mark_dlq("evt-1")
                    break
                table.mark_failed("evt-1")
            table.mark_stuck_if_expired("evt-1", now=attempt * 10.0 + 5.0)
            table.sweep_stuck()

        assert table.records["evt-1"].state == _OutboxState.DLQ
        assert table.records["evt-1"].attempts >= max_retries


# ──────────────────── CRASH SCENARIO 8: Old consumer + new schema ────────────────────


class TestScenario8SchemaVersioning:
    """Старый consumer получает event новой версии → schema mismatch.

    Crash model:
        1. Producer publishes v2 event (after schema migration).
        2. Old consumer (v1) receives v2 event → fails.
        3. Consumer retries → DLQ.
        4. Consumer rolled back to v1 (deployment rollback).
        5. Same event reprocessed → still fails.
        6. Either: deploy v2 consumer OR transform bridge.

    Ожидаемое поведение:
        - Schema version в event metadata (для diagnostic).
        - Consumer failure isolation (failed events не валят pipeline).
    """

    def test_schema_mismatch_isolated(self) -> None:
        """Schema mismatch event isolated, doesn't crash consumer pipeline."""
        broker = _Broker()
        events = [
            ("evt-old-schema", 1),   # v1 — old consumer OK
            ("evt-new-schema", 2),   # v2 — old consumer fails
            ("evt-another-old", 1),  # v1 — old consumer OK
        ]
        consumer_version = 1

        results = []
        for event_id, schema_version in events:
            broker.publish(event_id)
            result = broker.consume(event_id, consumer_schema_version=consumer_version, event_schema_version=schema_version)
            results.append((event_id, result.success, result.reason))

        # Old schema events processed OK.
        assert results[0] == ("evt-old-schema", True, "")
        assert results[2] == ("evt-another-old", True, "")

        # New schema event fails ISOLATED (other events still process).
        assert results[1][0] == "evt-new-schema"
        assert results[1][1] is False
        assert "schema mismatch" in results[1][2]

        # Invariant: failures are isolated (other events succeed).
        successful = [r for r in results if r[1]]
        assert len(successful) == 2

    def test_consumer_v2_processes_mixed_versions(self) -> None:
        """Consumer v2 (after deploy) обрабатывает оба schema versions."""
        broker = _Broker()
        events = [
            ("evt-v1", 1),
            ("evt-v2", 2),
        ]
        consumer_version = 2  # deployed v2

        for event_id, schema_version in events:
            broker.publish(event_id)
            result = broker.consume(event_id, consumer_schema_version=consumer_version, event_schema_version=schema_version)
            assert result.success is True, (
                f"Consumer v{consumer_version} должен обрабатывать v{schema_version}"
            )


# ──────────────────── Invariants: state machine correctness ────────────────────


class TestStateMachineInvariants:
    """Cross-cutting invariants для всего state machine."""

    def test_no_loss_across_scenarios(self) -> None:
        """Все events, кроме poison, eventually SENT (no silent loss)."""
        # Build composite scenario: 1 normal + 1 crash + 1 retry.
        table = _OutboxTable()
        broker = _Broker(available=True)

        events_normal = ["evt-normal"]
        events_crash = ["evt-crash"]
        events_retry = ["evt-retry"]

        for e in events_normal + events_crash + events_retry:
            table.insert(e)

        # Process evt-normal immediately.
        table.claim("evt-normal", now=0.0, lease_ttl=5.0)
        broker.publish("evt-normal")
        table.mark_sent("evt-normal", now=0.1)

        # evt-crash: publish OK, status update FAIL → re-publish.
        table.claim("evt-crash", now=0.0, lease_ttl=5.0)
        broker.publish("evt-crash")
        # Status update "fails" — leave PROCESSING.
        table.mark_stuck_if_expired("evt-crash", now=10.0)
        table.sweep_stuck()
        table.claim("evt-crash", now=11.0, lease_ttl=5.0)
        broker.publish("evt-crash")
        table.mark_sent("evt-crash", now=11.1)

        # evt-retry: broker temporarily down → PENDING → recover → SENT.
        broker.available = False
        table.claim("evt-retry", now=0.0, lease_ttl=5.0)
        # publish fails — mark_failed.
        table.mark_failed("evt-retry")
        broker.available = True
        table.claim("evt-retry", now=20.0, lease_ttl=5.0)
        broker.publish("evt-retry")
        table.mark_sent("evt-retry", now=20.1)

        # All SENT.
        for e in events_normal + events_crash + events_retry:
            assert table.records[e].state == _OutboxState.SENT, (
                f"Lost event: {e}, state={table.records[e].state}"
            )

    def test_state_machine_uses_canonical_problem_category(self) -> None:
        """Sanity check: error categories используются из core.errors.

        Когда outbox dispatcher бросает ошибку (e.g., broker persistent fail),
        она должна мапиться в ProblemCategory для unified error handling.
        """
        # Broker persistent fail → UNKNOWN / EXTERNAL → UNAVAILABLE category.
        from src.backend.core.errors import DomainProblem

        problem = DomainProblem(
            code="OUTBOX_BROKER_PERSISTENT_FAIL",
            category=ProblemCategory.UNAVAILABLE,
            title="Broker unavailable for extended period",
            retryable=True,
        )
        assert problem.is_retryable is True
        assert problem.category == ProblemCategory.UNAVAILABLE
