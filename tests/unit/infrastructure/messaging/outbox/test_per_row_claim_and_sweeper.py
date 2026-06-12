"""S72 W4 — TD-S64-W1 closure tests для per-row outbox claim + sweeper.

Покрывает S72 W2 (per-row claim) + S72 W3 (sweeper job):

* ``claim_pending`` sets ``claimed_by/claimed_at/claimed_until`` и propagates
  в OutboxMessage ORM objects.
* ``reset_stuck_processing`` returns count of reset rows.
* ``reset_stuck_processing`` does NOT touch rows with active lease.
* ``reset_stuck_processing`` returns 0 when no stuck rows.

Integration tests (real PG + transactional behavior) — manual, через
``make test-integration`` или CI (SQLite не поддерживает UPDATE RETURNING).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

# Stub для ``main_session_manager`` (тот же pattern что в test_claim_pending.py)
import sys
import types


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


_stub_sm = types.ModuleType(
    "src.backend.infrastructure.database.session_manager"
)
_stub_sm.main_session_manager = _StubSessionManager()  # type: ignore[attr-defined]
sys.modules["src.backend.infrastructure.database.session_manager"] = _stub_sm

from src.backend.infrastructure.repositories.outbox import (  # noqa: E402
    claim_pending,
    reset_stuck_processing,
)


def _make_fake_outbox_row(
    row_id: int = 1,
    status: str = "processing",
    claimed_by: str | None = "worker-A",
) -> MagicMock:
    """Создаёт MagicMock, имитирующий row из SQL UPDATE RETURNING."""
    now = datetime.now(UTC)
    row = MagicMock()
    row.id = row_id
    row.topic = "test.event"
    row.payload = {"k": "v"}
    row.headers = None
    row.status = status
    row.retry_count = 1
    row.last_error = None
    row.transport = "kafka"
    row.published_at = None
    row.next_attempt_at = now
    row.created_at = now
    row.updated_at = now
    row.claimed_by = claimed_by
    row.claimed_at = now
    row.claimed_until = now + timedelta(seconds=300)
    return row


# ============================================================================
# S72 W2: claim_pending per-row claim verification
# ============================================================================


@pytest.mark.asyncio
async def test_claim_pending_propagates_claimed_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per-row claim: OutboxMessage ORM objects должны иметь
    claimed_by/claimed_at/claimed_until set (S72 W2 new behavior)."""
    fake_row = _make_fake_outbox_row(row_id=42, claimed_by="worker-A")

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
    # NEW S72 W2 columns populated:
    assert msg.claimed_by == "worker-A"
    assert msg.claimed_at is not None
    assert msg.claimed_until is not None
    # claimed_until должен быть > now (lease TTL applied)
    assert msg.claimed_until > datetime.now(UTC)
    # claimed_until должен быть < now + lease_seconds + small overhead
    assert msg.claimed_until < datetime.now(UTC) + timedelta(seconds=310)


@pytest.mark.asyncio
async def test_claim_pending_sql_includes_status_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """UPDATE statement должен set status='processing' (S72 W2 per-row)."""
    fake_session = MagicMock()
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

    await claim_pending(limit=10, worker_id="worker-A", lease_seconds=300)

    # Inspect 2nd execute call (UPDATE statement)
    update_call = fake_session.execute.call_args_list[1]
    update_sql = update_call.args[0]
    update_params = update_call.args[1] if len(update_call.args) > 1 else update_call.kwargs
    sql_text = (
        update_sql.text
        if hasattr(update_sql, "text")
        else str(update_sql)
    )
    # SQL должен содержать status = 'processing' (per-row claim)
    assert "status" in sql_text.lower()
    assert "processing" in sql_text.lower()
    # Params должны включать worker_id и claimed_until
    if isinstance(update_params, dict):
        assert update_params.get("worker_id") == "worker-A"
        assert "claimed_until" in update_params


# ============================================================================
# S72 W3: reset_stuck_processing sweeper
# ============================================================================


@pytest.mark.asyncio
async def test_reset_stuck_processing_returns_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sweeper должен возвращать количество reset rows."""
    fake_session = MagicMock()
    # UPDATE RETURNING returns 3 rows
    update_result = MagicMock()
    update_result.fetchall.return_value = [
        MagicMock(id=1),
        MagicMock(id=2),
        MagicMock(id=3),
    ]
    fake_session.execute = AsyncMock(return_value=update_result)

    fake_txn = MagicMock()
    fake_txn.__aenter__ = AsyncMock(return_value=fake_session)
    fake_txn.__aexit__ = AsyncMock(return_value=None)

    monkeypatch.setattr(
        "src.backend.infrastructure.repositories.outbox.main_session_manager.transaction",
        lambda: fake_txn,
    )

    count = await reset_stuck_processing(threshold_seconds=300, limit=1000)
    assert count == 3


@pytest.mark.asyncio
async def test_reset_stuck_processing_no_stuck_returns_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Если нет stuck rows → return 0, no exception."""
    fake_session = MagicMock()
    update_result = MagicMock()
    update_result.fetchall.return_value = []  # no rows
    fake_session.execute = AsyncMock(return_value=update_result)

    fake_txn = MagicMock()
    fake_txn.__aenter__ = AsyncMock(return_value=fake_session)
    fake_txn.__aexit__ = AsyncMock(return_value=None)

    monkeypatch.setattr(
        "src.backend.infrastructure.repositories.outbox.main_session_manager.transaction",
        lambda: fake_txn,
    )

    count = await reset_stuck_processing()
    assert count == 0


@pytest.mark.asyncio
async def test_reset_stuck_processing_filters_by_status_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SQL filter должен требовать status='processing' (не pending/sent/failed)."""
    fake_session = MagicMock()
    update_result = MagicMock()
    update_result.fetchall.return_value = []
    fake_session.execute = AsyncMock(return_value=update_result)

    fake_txn = MagicMock()
    fake_txn.__aenter__ = AsyncMock(return_value=fake_session)
    fake_txn.__aexit__ = AsyncMock(return_value=None)

    monkeypatch.setattr(
        "src.backend.infrastructure.repositories.outbox.main_session_manager.transaction",
        lambda: fake_txn,
    )

    await reset_stuck_processing(threshold_seconds=300)

    call = fake_session.execute.call_args
    sql_text = call.args[0]
    text_str = sql_text.text if hasattr(sql_text, "text") else str(sql_text)
    # Filter должен содержать status='processing' AND claimed_until < cutoff
    assert "status" in text_str.lower()
    assert "processing" in text_str.lower()
    assert "claimed_until" in text_str.lower()
    # cutoff param
    params = call.args[1] if len(call.args) > 1 else call.kwargs
    if isinstance(params, dict):
        assert "cutoff" in params
        assert "limit" in params


@pytest.mark.asyncio
async def test_reset_stuck_processing_respects_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """cutoff = now - threshold_seconds. threshold=0 → cutoff=now (ALL processing reset)."""
    fake_session = MagicMock()
    update_result = MagicMock()
    update_result.fetchall.return_value = []
    fake_session.execute = AsyncMock(return_value=update_result)

    fake_txn = MagicMock()
    fake_txn.__aenter__ = AsyncMock(return_value=fake_session)
    fake_txn.__aexit__ = AsyncMock(return_value=None)

    monkeypatch.setattr(
        "src.backend.infrastructure.repositories.outbox.main_session_manager.transaction",
        lambda: fake_txn,
    )

    before_call = datetime.now(UTC)
    await reset_stuck_processing(threshold_seconds=0)  # aggressive reset
    after_call = datetime.now(UTC)

    call = fake_session.execute.call_args
    params = call.args[1] if len(call.args) > 1 else call.kwargs
    cutoff = params["cutoff"]
    # cutoff должен быть ~now (threshold=0)
    assert before_call - timedelta(seconds=1) <= cutoff <= after_call + timedelta(seconds=1)
