"""Unit tests for src.backend.core.interfaces.notification."""

from __future__ import annotations

import pytest

from src.backend.core.interfaces.notification import (
    NotificationAdapter,
    NotificationMessage,
)


class TestNotificationMessage:
    def test_defaults(self) -> None:
        msg = NotificationMessage(recipient="u1")
        assert msg.recipient == "u1"
        assert msg.subject == ""
        assert msg.body == ""
        assert msg.metadata == {}

    def test_full(self) -> None:
        msg = NotificationMessage(
            recipient="u1", subject="s", body="b", metadata={"k": "v"}
        )
        assert msg.metadata == {"k": "v"}


class TestNotificationAdapter:
    def test_cannot_instantiate(self) -> None:
        with pytest.raises(TypeError):
            NotificationAdapter()  # type: ignore[abstract]

    def test_partial_subclass_fails(self) -> None:
        class Partial(NotificationAdapter):
            async def send(self, message: NotificationMessage) -> str:
                return ""

        with pytest.raises(TypeError):
            Partial()  # type: ignore[abstract]

    def test_valid_subclass(self) -> None:
        class Full(NotificationAdapter):
            async def send(self, message: NotificationMessage) -> str:
                return "id"

            async def is_available(self) -> bool:
                return True

        inst = Full()
        assert inst.channel == "base"
