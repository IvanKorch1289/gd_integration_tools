"""Pipeline-проверка: PII действительно маскируется в шине structlog.

Симулируем shared_processors из ``StructlogGraylogBackend.configure``,
включая :func:`mask_pii` ровно перед :func:`route_to_sinks`. Цель —
проверить, что email/phone в kwargs логгера попадают в финальный
event_dict уже маскированные.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.infrastructure.observability.pii_filter import mask_pii


@pytest.fixture()
def configured_structlog() -> Any:
    """Минимальная structlog-конфигурация с ``mask_pii`` в pipeline."""
    structlog = pytest.importorskip("structlog")
    captured: list[dict[str, Any]] = []

    def _capture(_logger: Any, _method_name: str, event_dict: dict[str, Any]) -> str:
        captured.append(event_dict)
        return ""

    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            mask_pii,
            _capture,
        ],
        wrapper_class=structlog.BoundLogger,
        cache_logger_on_first_use=False,
    )
    yield structlog, captured
    structlog.reset_defaults()


def test_email_masked_in_pipeline(configured_structlog: Any) -> None:
    """Лог с email-полем содержит ``<email>`` в финальном event_dict."""
    structlog, captured = configured_structlog
    log = structlog.get_logger("pii-test")
    log.info("user.created", email="alice@example.com", id=42)
    assert captured
    assert captured[0]["email"] == "<email>"
    assert captured[0]["id"] == 42


def test_phone_masked_in_pipeline(configured_structlog: Any) -> None:
    structlog, captured = configured_structlog
    log = structlog.get_logger("pii-test")
    log.warning("user.contact", phone="+7 (495) 123-45-67")
    assert "<phone>" in captured[0]["phone"]


def test_message_field_masked(configured_structlog: Any) -> None:
    """Поле ``event`` (само сообщение) тоже маскируется."""
    structlog, captured = configured_structlog
    log = structlog.get_logger("pii-test")
    log.info("user alice@example.com signed in")
    assert captured[0]["event"] == "user <email> signed in"
