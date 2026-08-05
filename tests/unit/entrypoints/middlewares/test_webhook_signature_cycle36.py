"""Regression-тесты B-14 fix (cycle 36): webhook_signature 503 → unified error envelope.

Проверяет, что ``WebhookSignatureMiddleware._send_503`` использует
:func:`src.backend.core.errors.build_error_envelope` и body содержит
поля ``code``, ``detail``, ``error_id``, ``correlation_id``. Legacy
поле ``{"error": ...}`` сохранено как backward-compat alias, а
``{"detail": ...}`` (отдельно) НЕ присутствует как отдельный ключ —
только внутри envelope под именем ``detail``.
"""

# ruff: noqa: S101

from __future__ import annotations

import json
import re
from unittest.mock import AsyncMock

import pytest

from src.backend.entrypoints.middlewares.webhook_signature import (
    WebhookSignatureMiddleware,
)

_UUID4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


def _start_message(send: AsyncMock) -> dict | None:
    for call in send.await_args_list:
        msg = call.args[0]
        if msg["type"] == "http.response.start":
            return msg
    return None


def _body_message(send: AsyncMock) -> dict | None:
    for call in send.await_args_list:
        msg = call.args[0]
        if msg["type"] == "http.response.body":
            return msg
    return None


def _make_scope(path: str, *, correlation_id: str | None = None) -> dict:
    """Создаёт ASGI scope с опциональным correlation_id в ``state``."""
    scope: dict = {
        "type": "http",
        "method": "POST",
        "url": f"http://test{path}",
        "path": path,
        "headers": [],
    }
    if correlation_id is not None:
        scope["state"] = {"correlation_id": correlation_id}
    return scope


def _make_receive(body: bytes):
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return receive


class TestWebhookSignature503Envelope:
    """B-14 fix: 503 response использует build_error_envelope."""

    @pytest.mark.asyncio
    async def test_503_body_has_envelope_keys_and_correlation_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """503 body содержит code/detail/error_id/correlation_id.

        Также проверяется, что correlation_id из scope пробрасывается
        в envelope (фиксирует cycle 35 A2 контракт).
        """
        monkeypatch.delenv("APP_ENVIRONMENT", raising=False)
        monkeypatch.delenv("WEBHOOK_ALLOW_MISSING_SECRET", raising=False)

        app = AsyncMock()

        async def downstream(scope, receive, send):
            raise AssertionError("downstream не должен быть вызван")

        app.side_effect = downstream
        mw = WebhookSignatureMiddleware(
            app=app, path_prefixes=("/webhooks/",), secrets_by_prefix={}
        )

        send = AsyncMock()
        await mw(
            _make_scope("/webhooks/stripe", correlation_id="corr-cycle36-abc"),
            _make_receive(b'{"event":"test"}'),
            send,
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 503

        body = _body_message(send)
        assert body is not None
        parsed = json.loads(body["body"].decode("utf-8"))

        # Envelope contract: обязательные поля.
        assert parsed["code"] == "webhook_not_configured"
        assert "secret" in parsed["detail"].lower()
        assert parsed["correlation_id"] == "corr-cycle36-abc"

        # error_id — uuid4 формат (сгенерированный envelope'ом).
        assert _UUID4_RE.match(parsed["error_id"]), (
            f"error_id={parsed['error_id']!r} is not uuid4 format"
        )

        # Backward-compat alias: ``error`` всё ещё в теле (старые клиенты).
        assert parsed["error"] == "webhook_not_configured"

    @pytest.mark.asyncio
    async def test_503_body_no_longer_has_legacy_bare_detail_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Legacy ``{"detail": ...}`` теперь НЕ отдельный top-level ключ.

        До B-14 fix тело 503 было ``{"error":..., "detail":...}`` —
        ``detail`` существовал как bare ключ, конфликтующий с envelope.
        После миграции ``detail`` — это поле envelope, а не
        самостоятельный ключ уровнем выше ``code``. Проверяем, что в
        body ровно один ``detail`` и он принадлежит envelope.
        """
        monkeypatch.delenv("APP_ENVIRONMENT", raising=False)
        monkeypatch.delenv("WEBHOOK_ALLOW_MISSING_SECRET", raising=False)

        app = AsyncMock()

        async def downstream(scope, receive, send):
            raise AssertionError("downstream не должен быть вызван")

        app.side_effect = downstream
        mw = WebhookSignatureMiddleware(
            app=app, path_prefixes=("/webhooks/",), secrets_by_prefix={}
        )

        send = AsyncMock()
        await mw(_make_scope("/webhooks/stripe"), _make_receive(b"{}"), send)

        body = _body_message(send)
        assert body is not None
        parsed = json.loads(body["body"].decode("utf-8"))

        # Envelope contract: ровно один detail, его значение — строка с
        # упоминанием secret (как раньше).
        assert isinstance(parsed["detail"], str)
        assert "secret" in parsed["detail"].lower()

        # Полный набор ключей envelope (без лишних legacy-полей).
        assert set(parsed.keys()) >= {"code", "detail", "error_id", "correlation_id"}
        # Не должно быть дубля ``detail`` на верхнем уровне — envelope
        # ровно один. Проверяем отсутствие произвольных legacy-keys
        # кроме разрешённых (code, detail, error_id, correlation_id,
        # request_id, error как backward-compat alias).
        allowed_keys = {
            "code",
            "detail",
            "error_id",
            "correlation_id",
            "request_id",
            "error",
        }
        extra_keys = set(parsed.keys()) - allowed_keys
        assert extra_keys == set(), f"unexpected legacy keys in envelope: {extra_keys}"
