"""Контракты обмена сообщениями (Outbox/Inbox/DLQ Protocol + Fake).

Реализации находятся в `infrastructure/messaging/`. Этот пакет содержит
только Protocol-контракты и Fake-реализации для unit-тестов и frontend UI
до полной выкатки реальных backend'ов в Sprint 5 К2.
"""

from __future__ import annotations

from src.backend.core.messaging.outbox import (
    FakeOutbox,
    OutboxBackend,
    OutboxEvent,
    OutboxEventStatus,
)

__all__ = ("FakeOutbox", "OutboxBackend", "OutboxEvent", "OutboxEventStatus")
