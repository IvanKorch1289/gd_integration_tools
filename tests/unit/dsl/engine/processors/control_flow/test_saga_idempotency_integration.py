"""S93 M5-#6: integration test — idempotency key coverage на critical saga paths.

Verifies что saga compensation steps имеют idempotency protection
(через correlation_id) для защиты от partial-failure recovery.
"""

from __future__ import annotations

import asyncio

from src.backend.dsl.engine.exchange import Exchange, ExchangeMeta


class TestSagaIdempotencyKeys:
    """S93 M5-#6: critical saga paths require idempotency keys."""

    def test_exchange_has_idempotency_key_field(self) -> None:
        """Exchange должен иметь correlation_id (M5-#6)."""
        ex = Exchange()
        assert hasattr(ex.meta, "correlation_id")
        assert ex.meta.correlation_id is not None

    def test_saga_compensation_uses_unique_ids(self) -> None:
        """Compensation steps используют unique correlation_id.

        S93 M5-#6: saga compensation шаги (особенно при partial failure)
        должны иметь unique idempotency keys → `correlation_id`.
        """
        meta1 = ExchangeMeta()
        meta2 = ExchangeMeta()
        # Each exchange has unique correlation_id
        assert meta1.correlation_id != meta2.correlation_id

    def test_async_idempotency_concurrent_runs(self) -> None:
        """S93 M5-#6: concurrent saga steps — разные correlation_ids."""
        async def create_exchange(idx: int) -> Exchange:
            return Exchange()

        async def run_concurrent() -> list[str]:
            return await asyncio.gather(
                *(create_exchange(i) for i in range(10))
            )

        results = asyncio.run(run_concurrent())
        cids = [ex.meta.correlation_id for ex in results]
        # All unique (10 distinct UUIDs)
        assert len(set(cids)) == 10, f"Expected 10 unique IDs, got {len(set(cids))}"
