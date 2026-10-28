"""S-30 (Wave 13, Q18): allowlist-валидация имени таблицы в InboxDLQWriter.

Имя таблицы подставляется в ``INSERT INTO {table}`` через f-string
(bind-параметры применимы только к значениям) → невалидное имя должно
отклоняться fail-fast, до похода в БД.

Примечание: ``InboxDLQWriter`` — НЕ мёртвый код: он создаётся в
composition root (``plugins/composition/di.py`` — DLQ-writer для
``CDCClient``) и в ``infrastructure/messaging/outbox/lifecycle.py``.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.infrastructure.messaging.dlq.inbox_writer import InboxDLQWriter
from src.backend.infrastructure.messaging.dlq_base import DLQEnvelope


class _FakeSession:
    """Сессия-заглушка: собирает исполняемые SQL-выражения."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    async def execute(self, statement: Any, params: Any = None) -> None:
        """Зафиксировать SQL-выражение (params не используются)."""
        self.statements.append(str(statement))

    async def commit(self) -> None:
        """Зафиксировать транзакцию (no-op)."""


class _FakeSessionContext:
    """Async-context-manager поверх fake-сессии."""

    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> _FakeSession:
        """Войти в контекст сессии."""
        return self._session

    async def __aexit__(self, *exc_info: object) -> bool:
        """Выйти из контекста сессии без подавления исключений."""
        return False


class _FakeSessionFactory:
    """Фабрика сессий: каждый вызов отдаёт один и тот же fake-контекст."""

    def __init__(self) -> None:
        self.session = _FakeSession()

    def __call__(self) -> _FakeSessionContext:
        """Вернуть контекст fake-сессии."""
        return _FakeSessionContext(self.session)


@pytest.mark.unit
def test_inbox_writer_rejects_injection_in_table_name() -> None:
    """Невалидное имя таблицы → ValueError в конструкторе, INSERT не уходит."""
    factory = _FakeSessionFactory()

    with pytest.raises(ValueError, match="identifier"):
        InboxDLQWriter(session_factory=factory, table_name="dlq_inbox; DROP TABLE x")

    assert factory.session.statements == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_inbox_writer_accepts_valid_table_name() -> None:
    """Валидное имя таблицы → INSERT уходит в БД как раньше."""
    factory = _FakeSessionFactory()
    writer = InboxDLQWriter(session_factory=factory, table_name="dlq_inbox")
    envelope = DLQEnvelope(
        transport="http", error_class="httpx.ConnectTimeout", error_message="timeout"
    )

    await writer.write(envelope)

    assert len(factory.session.statements) == 1
    assert "INSERT INTO dlq_inbox" in factory.session.statements[0]
