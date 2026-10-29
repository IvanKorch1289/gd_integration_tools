"""Request-логирование идёт через structlog-стек, тела — замаскированы.

ADR-0392 (волна 18, кластер G3 — логирование).

Дефект: ``InnerRequestLoggingMiddleware`` брал логгер через
``get_app_logger_provider()`` → legacy ``external_apis.logging_service``
``app_logger`` (``propagate=False`` + ``QueueHandler``). Последствия:

* запись НЕ доходила до root-handler (проба аудита: ``reached root handler: []``);
* вывод plain-text — без JSON, ``correlation_id`` и PII-маскирования;
* тела запроса/ответа писались НЕЗАМАСКИРОВАННЫМИ (в dev ``log_requests: true``)
  → утечка PII.

Контракт после фикса:

* логгер — ``src.backend.core.logging.get_logger`` (structlog/JSON-стек);
* события — структурированные (``http.request`` / ``http.response`` /
  ``http.request_body`` / ``http.response_body``);
* тела проходят через канонический PII-маскер ``core.security.pii_masker``.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from unittest.mock import AsyncMock

import pytest

from src.backend.entrypoints.middlewares.request_log import (
    InnerRequestLoggingMiddleware,
)


@pytest.fixture
def root_records() -> Iterator[list[logging.LogRecord]]:
    """Перехватить записи, дошедшие до ROOT-handler'а stdlib logging.

    Legacy ``app_logger`` имеет ``propagate=False`` — такие записи сюда
    НЕ попадают, поэтому assert'ы ниже одновременно проверяют и сам факт
    перехода на structlog-стек.
    """
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Capture()
    root = logging.getLogger()
    previous_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        yield records
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)


def _downstream(status_code: int = 200, body: bytes = b"ok"):
    async def app(scope, receive, send):
        await send(
            {"type": "http.response.start", "status": status_code, "headers": []}
        )
        await send({"type": "http.response.body", "body": body})

    return app


def _scope(method: str = "GET", path: str = "/path", state: dict | None = None) -> dict:
    scope = {
        "type": "http",
        "method": method,
        "url": f"http://test{path}",
        "path": path,
        "headers": [],
        "query_string": b"",
    }
    if state is not None:
        scope["state"] = state
    return scope


def _messages(records: list[logging.LogRecord]) -> list[str]:
    """Тексты всех перехваченных записей."""
    return [record.getMessage() for record in records]


@pytest.mark.unit
class TestRequestLogReachesRootHandler:
    """Записи request-лога доходят до root-handler'а (structlog-стек)."""

    @pytest.mark.asyncio
    async def test_request_and_response_reach_root_handler(
        self, root_records: list[logging.LogRecord]
    ) -> None:
        """События запроса/ответа доходят до root-handler'а."""
        app = AsyncMock()
        app.side_effect = _downstream(status_code=201)
        middleware = InnerRequestLoggingMiddleware(app)

        send = AsyncMock()
        await middleware(_scope("GET", "/orders"), AsyncMock(), send)

        messages = _messages(root_records)
        assert any("http.request" in msg for msg in messages), messages
        assert any("http.response" in msg for msg in messages), messages

    @pytest.mark.asyncio
    async def test_response_event_carries_status_and_path(
        self, root_records: list[logging.LogRecord]
    ) -> None:
        """Структурированные поля (status/method/path) — в записи."""
        app = AsyncMock()
        app.side_effect = _downstream(status_code=503)
        middleware = InnerRequestLoggingMiddleware(app)

        send = AsyncMock()
        await middleware(_scope("GET", "/health"), AsyncMock(), send)

        joined = " ".join(_messages(root_records))
        assert "503" in joined
        assert "/health" in joined


@pytest.mark.unit
class TestRequestLogMasksBodies:
    """Тела запроса/ответа маскируются (PII не утекает в лог)."""

    @pytest.mark.asyncio
    async def test_request_body_pii_is_masked(
        self, root_records: list[logging.LogRecord]
    ) -> None:
        """Email/телефон в теле запроса не попадают в лог как есть."""
        app = AsyncMock()
        app.side_effect = _downstream()
        middleware = InnerRequestLoggingMiddleware(app)
        middleware.log_body = True

        body = b'{"email": "alice@example.com", "phone": "+79991234567"}'
        send = AsyncMock()
        await middleware(
            _scope("POST", "/register", state={"body": body}), AsyncMock(), send
        )

        joined = " ".join(_messages(root_records))
        assert "alice@example.com" not in joined
        assert "+79991234567" not in joined
        assert "http.request_body" in joined

    @pytest.mark.asyncio
    async def test_response_body_pii_is_masked(
        self, root_records: list[logging.LogRecord]
    ) -> None:
        """Email/телефон в теле ответа не попадают в лог как есть."""
        app = AsyncMock()
        app.side_effect = _downstream(
            body=b'{"contact": "bob@example.org", "msisdn": "+79001112233"}'
        )
        middleware = InnerRequestLoggingMiddleware(app)
        middleware.log_body = True

        send = AsyncMock()
        await middleware(_scope("GET", "/profile"), AsyncMock(), send)

        joined = " ".join(_messages(root_records))
        assert "bob@example.org" not in joined
        assert "+79001112233" not in joined
        assert "http.response_body" in joined

    @pytest.mark.asyncio
    async def test_non_pii_body_is_still_logged(
        self, root_records: list[logging.LogRecord]
    ) -> None:
        """Не-PII содержимое тела логируется (маскирование не съедает всё)."""
        app = AsyncMock()
        app.side_effect = _downstream()
        middleware = InnerRequestLoggingMiddleware(app)
        middleware.log_body = True

        send = AsyncMock()
        await middleware(
            _scope("POST", "/orders", state={"body": b'{"sku": "A-1"}'}),
            AsyncMock(),
            send,
        )

        joined = " ".join(_messages(root_records))
        assert "A-1" in joined
