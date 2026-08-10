"""D-AUDIT-FIX-184-4 regression test — DLQ cleanup uses PARTITION DROP.

Closes D-AUDIT-FIX-184-4 (S184 W4 #4): DLQ cleanup_job.py:82 used
``DELETE FROM ...`` (full-table mutation, slow on production scale).
Post-fix: ``ALTER TABLE ... DROP PARTITION ID 'YYYYMM'`` (per
b69d6b49 PARTITION migration).

Strict-test policy per D-LESSON-11: NO lax assertions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.core.messaging.dlq_policy import DLQPolicy, DLQPolicyRegistry
from src.backend.infrastructure.messaging.dlq.cleanup_job import (
    DLQCleanupJob,
    _iso_to_yyyymm,
)


def test_iso_to_yyyymm_helper() -> None:
    """Helper converts ISO-8601 → YYYYMM (ClickHouse partition suffix)."""
    assert _iso_to_yyyymm("2026-08-05T14:30:00+00:00") == "202608"
    assert _iso_to_yyyymm("2025-12-31T23:59:59+00:00") == "202512"
    assert _iso_to_yyyymm("2024-01-01T00:00:00+00:00") == "202401"


@pytest.mark.asyncio
async def test_cleanup_run_uses_drop_partition() -> None:
    """``run()`` issues ``ALTER TABLE ... DROP PARTITION ID 'YYYYMM'``."""
    policy = DLQPolicy(
        class_name="operational", retention_days=30,
        max_replays=3, auto_archive_after_days=90,
    )
    registry = DLQPolicyRegistry()
    registry.register(policy)
    ch_client = MagicMock()
    ch_client.execute = AsyncMock()

    fixed_clock = datetime(2026, 8, 5, 14, 30, 0, tzinfo=UTC)
    job = DLQCleanupJob(ch_client=ch_client, registry=registry, clock=lambda: fixed_clock)

    await job.run()

    # Verify at least one call was ALTER TABLE ... DROP PARTITION
    assert ch_client.execute.await_count >= 1
    all_sqls = [call.args[0] for call in ch_client.execute.await_args_list]
    assert any("ALTER TABLE" in s and "DROP PARTITION" in s for s in all_sqls), (
        f"D-AUDIT-FIX-184-4: expected ALTER TABLE ... DROP PARTITION. "
        f"Got: {all_sqls}"
    )
    drop_sql = next(s for s in all_sqls if "DROP PARTITION" in s)
    # 2026-08-05 minus 30 days = 2026-07-06 → partition YYYYMM = 202607
    assert "202607" in drop_sql, (
        f"D-AUDIT-FIX-184-4: expected partition 202607 (Aug 2026 - 30 days). "
        f"Got: {drop_sql}"
    )


@pytest.mark.asyncio
async def test_cleanup_run_does_not_use_delete() -> None:
    """Post-fix: no DELETE statement is generated (P0 migration target)."""
    policy = DLQPolicy(
        class_name="operational", retention_days=7,
        max_replays=3, auto_archive_after_days=90,
    )
    registry = DLQPolicyRegistry()
    registry.register(policy)
    ch_client = MagicMock()
    ch_client.execute = AsyncMock()

    fixed_clock = datetime(2026, 8, 5, 14, 30, 0, tzinfo=UTC)
    job = DLQCleanupJob(ch_client=ch_client, registry=registry, clock=lambda: fixed_clock)

    await job.run()

    actual_sql = ch_client.execute.await_args.args[0]
    # Pre-fix used "DELETE FROM"; post-fix should NOT have it
    assert "DELETE FROM" not in actual_sql, (
        "D-AUDIT-FIX-184-4: pre-fix used DELETE FROM (O(n) full-table). "
        "Post-fix should use ALTER TABLE ... DROP PARTITION (O(log n)). "
        f"Got SQL: {actual_sql}"
    )
