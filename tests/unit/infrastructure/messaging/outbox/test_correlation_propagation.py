"""Регрессионный тест для T4.12 (S17 DoD-12): correlation-id propagation в outbox.

Контекст:
    :class:`OutboxRepository` должен автоматически inject ``correlation_id``
    из ``RequestContext`` (через ``get_correlation_id()``) в outbox-headers,
    если caller не передал явное значение. Это закрывает S17 K3 W3
    correlation-id e2e для асинхронных consumers (Kafka/RabbitMQ workers
    читают headers и восстанавливают bind в свой RequestContext).

Wave: ``[wave:s17/k3-w3-correlation-id-end-to-end]``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.infrastructure.messaging.outbox.repository import OutboxRepository


@pytest.fixture
def _session() -> MagicMock:
    """AsyncSession-mock с awaitable flush."""
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


@pytest.fixture(autouse=True)
def _reset_correlation_var() -> object:
    """Изолировать correlation_id_var между тестами."""
    from src.backend.infrastructure.observability.correlation import correlation_id_var

    token = correlation_id_var.set("")
    yield
    correlation_id_var.reset(token)


async def test_enqueue_injects_correlation_id_from_context(_session: MagicMock) -> None:
    """Если RequestContext имеет correlation_id, он попадает в headers."""
    from src.backend.infrastructure.observability.correlation import correlation_id_var

    correlation_id_var.set("test-correlation-abc123")

    repo = OutboxRepository(_session)
    msg = await repo.enqueue(topic="orders.created", payload={"order_id": 42})

    assert msg.headers["correlation_id"] == "test-correlation-abc123"


async def test_enqueue_explicit_header_overrides_context(_session: MagicMock) -> None:
    """Явный correlation_id в headers побеждает значение из RequestContext."""
    from src.backend.infrastructure.observability.correlation import correlation_id_var

    correlation_id_var.set("from-context")

    repo = OutboxRepository(_session)
    msg = await repo.enqueue(
        topic="orders.created", payload={}, headers={"correlation_id": "explicit-cid"}
    )

    assert msg.headers["correlation_id"] == "explicit-cid"


async def test_enqueue_without_context_yields_no_correlation_id(
    _session: MagicMock,
) -> None:
    """Если ни RequestContext, ни headers не задают cid — поле опускается."""
    repo = OutboxRepository(_session)
    msg = await repo.enqueue(topic="orders.created", payload={})

    assert "correlation_id" not in msg.headers


async def test_enqueue_preserves_other_headers(_session: MagicMock) -> None:
    """Прочие headers (tenant_id, custom) сохраняются вместе с cid."""
    from src.backend.infrastructure.observability.correlation import correlation_id_var

    correlation_id_var.set("test-cid")

    repo = OutboxRepository(_session)
    msg = await repo.enqueue(
        topic="orders.created",
        payload={},
        headers={"tenant_id": "acme", "X-Custom": "value"},
    )

    assert msg.headers["correlation_id"] == "test-cid"
    assert msg.headers["tenant_id"] == "acme"
    assert msg.headers["X-Custom"] == "value"
