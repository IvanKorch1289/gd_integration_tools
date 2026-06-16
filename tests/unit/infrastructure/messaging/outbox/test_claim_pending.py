"""Unit-тесты для outbox.claim_pending (S64 W1).

Проверяет multi-instance safety primitives:

* ``_advisory_lock_key`` — детерминистичный hash → 64-bit int.
* ``claim_pending(worker_id="")`` — ValueError.
* ``claim_pending`` при lock-not-acquired → возврат ``[]``.
* ``claim_pending`` при lock-acquired + DB-empty → возврат ``[]``.

Integration test (с реальной PG + ``pg_try_advisory_xact_lock``) — manual,
через ``make test-integration`` или CI (SQLite не поддерживает advisory locks).
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest


# Stub for ``main_session_manager`` ДО импорта outbox.py — pre-existing
# lazy-accessor chain в project ломает collection (см. S64 W1 review).
# Достаточно MagicMock, потому что test-ы ниже monkeypatch-ат его явно.
class _StubSessionManager:
    def transaction(self) -> "MagicMock":
        m = MagicMock()
        m.__aenter__ = AsyncMock(return_value=MagicMock())
        m.__aexit__ = AsyncMock(return_value=None)
        return m

    def create_session(self) -> "MagicMock":
        m = MagicMock()
        m.__aenter__ = AsyncMock(return_value=MagicMock())
        m.__aexit__ = AsyncMock(return_value=None)
        return m


import sys
import types

_stub_sm = types.ModuleType("src.backend.infrastructure.database.session_manager")
_stub_sm.main_session_manager = _StubSessionManager()  # type: ignore[attr-defined]
sys.modules["src.backend.infrastructure.database.session_manager"] = _stub_sm

# Импорт outbox-модели тоже требует session_manager (для Base.metadata),
# но sqlalchemy-mapped класс импортируется без runtime DB connection.
from src.backend.infrastructure.repositories.outbox import (  # noqa: E402
    _advisory_lock_key,
    claim_pending,
)


def test_advisory_lock_key_deterministic() -> None:
    """Hash → 64-bit int, детерминистичный per worker_id."""
    k1 = _advisory_lock_key("worker-1")
    k2 = _advisory_lock_key("worker-1")
    k3 = _advisory_lock_key("worker-2")
    assert k1 == k2, "Same worker_id → same key"
    assert k1 != k3, "Different worker_id → different key"
    assert 0 <= k1 < 2**63, "63-bit signed positive (Postgres bigint range)"


def test_advisory_lock_key_unicode() -> None:
    """worker_id с unicode (hostnames, pod-names)."""
    k_unicode = _advisory_lock_key("pod-сад-αβγ-001")
    assert 0 <= k_unicode < 2**63


@pytest.mark.asyncio
async def test_claim_pending_empty_worker_id_raises() -> None:
    """``worker_id=""`` → ValueError (защита от опечаток)."""
    with pytest.raises(ValueError, match="worker_id обязателен"):
        await claim_pending(worker_id="")


@pytest.mark.asyncio
async def test_claim_pending_lock_not_acquired_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Если ``pg_try_advisory_xact_lock`` возвращает False → ``[]``.

    Сценарий: 2 worker'а тикают одновременно. Worker A уже держит lock
    (длительный claim). Worker B вызывает ``claim_pending`` → получает
    ``False`` от ``pg_try_advisory_xact_lock`` → возвращает ``[]``.
    Worker B попробует на следующем tick.
    """
    fake_session = MagicMock()
    # 1-й execute → pg_try_advisory_xact_lock → scalar=False
    advisory_result = MagicMock()
    advisory_result.scalar.return_value = False
    fake_session.execute = AsyncMock(return_value=advisory_result)

    fake_txn = MagicMock()
    fake_txn.__aenter__ = AsyncMock(return_value=fake_session)
    fake_txn.__aexit__ = AsyncMock(return_value=None)

    monkeypatch.setattr(
        "src.backend.infrastructure.repositories.outbox.main_session_manager.transaction",
        lambda: fake_txn,
    )

    result = await claim_pending(limit=10, worker_id="worker-B")
    assert result == []
    # 1 execute (advisory lock try) — UPDATE/RETURNING НЕ вызван
    assert fake_session.execute.await_count == 1


@pytest.mark.asyncio
async def test_claim_pending_lock_acclaimed_db_empty_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lock получен, но pending пуст → ``[]``."""
    fake_session = MagicMock()
    # 1-й execute → advisory lock → scalar=True
    # 2-й execute → UPDATE RETURNING → fetchall() = []
    advisory_result = MagicMock()
    advisory_result.scalar.return_value = True
    update_result = MagicMock()
    update_result.fetchall.return_value = []
    fake_session.execute = AsyncMock(side_effect=[advisory_result, update_result])

    fake_txn = MagicMock()
    fake_txn.__aenter__ = AsyncMock(return_value=fake_session)
    fake_txn.__aexit__ = AsyncMock(return_value=None)

    monkeypatch.setattr(
        "src.backend.infrastructure.repositories.outbox.main_session_manager.transaction",
        lambda: fake_txn,
    )

    result = await claim_pending(limit=10, worker_id="worker-A")
    assert result == []
    assert fake_session.execute.await_count == 2


@pytest.mark.asyncio
async def test_claim_pending_lock_acclaimed_returns_orm_objects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lock + claimed rows → list[OutboxMessage] с инкрементированным retry_count."""
    fake_row = MagicMock()
    fake_row.id = 1
    fake_row.topic = "orders.created"
    fake_row.payload = {"order_id": 42}
    fake_row.headers = None
    fake_row.status = "pending"
    fake_row.retry_count = 1  # было 0, инкрементировано в SQL
    fake_row.last_error = None
    fake_row.transport = "kafka"
    fake_row.published_at = None
    fake_row.next_attempt_at = datetime.now(UTC)
    fake_row.created_at = datetime.now(UTC)
    fake_row.updated_at = datetime.now(UTC)

    fake_session = MagicMock()
    advisory_result = MagicMock()
    advisory_result.scalar.return_value = True
    update_result = MagicMock()
    update_result.fetchall.return_value = [fake_row]
    fake_session.execute = AsyncMock(side_effect=[advisory_result, update_result])

    fake_txn = MagicMock()
    fake_txn.__aenter__ = AsyncMock(return_value=fake_session)
    fake_txn.__aexit__ = AsyncMock(return_value=None)

    monkeypatch.setattr(
        "src.backend.infrastructure.repositories.outbox.main_session_manager.transaction",
        lambda: fake_txn,
    )

    result = await claim_pending(limit=10, worker_id="worker-A")
    assert len(result) == 1
    msg = result[0]
    assert msg.id == 1
    assert msg.topic == "orders.created"
    assert msg.payload == {"order_id": 42}
    assert msg.retry_count == 1
    assert msg.headers == {}, "NULL headers → empty dict (ORM default)"
