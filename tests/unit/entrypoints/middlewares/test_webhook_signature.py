"""Regression-тесты B-02 fix: webhook signature fail-closed при missing secret.

P0 security fix (cycle 33): раньше ``WebhookSignatureMiddleware`` skip-verify
с ``logger.debug`` для protected path-prefix без сконфигурированного secret.
Это давало обход HMAC-проверки в любой среде, где оператор забыл
прописать ``secrets_by_prefix``. Новый контракт: 503 + JSON
``{"error":"webhook_not_configured","detail":"..."}`` + инкремент
``webhook_signature_missing_secret_total{path_prefix}``. Dev escape
допустим только при ``APP_ENVIRONMENT=dev`` И
``WEBHOOK_ALLOW_MISSING_SECRET=true`` (явный opt-in).
"""


from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from src.backend.core.observability.metrics import (
    webhook_signature_missing_secret_total,
)
from src.backend.entrypoints.middlewares.webhook_signature import (
    WebhookSignatureMiddleware,
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


def _downstream_ok():
    async def downstream(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    return downstream


def _make_scope(path: str) -> dict:
    return {
        "type": "http",
        "method": "POST",
        "url": f"http://test{path}",
        "path": path,
        "headers": [],
    }


def _make_receive(body: bytes):
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return receive


def _read_counter_value(path_prefix: str) -> float:
    """Возвращает текущее значение counter для path_prefix (0 если нет)."""
    try:
        sample = webhook_signature_missing_secret_total.labels(
            path_prefix=path_prefix,
        )
    except Exception:
        return 0.0
    # prometheus_client.Counter.labels(...) → child без _value; читаем
    # через _value.get() для корректного multi-process семантики.
    try:
        return sample._value.get()  # type: ignore[attr-defined]
    except Exception:
        return 0.0


class TestWebhookSignatureMissingSecret:
    """B-02 fix: protected path-prefix без secret → 503 fail-closed."""

    @pytest.mark.asyncio
    async def test_webhook_signature_missing_secret_returns_503(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Path protected, но secret не сконфигурирован → 503 JSON."""
        monkeypatch.delenv("APP_ENVIRONMENT", raising=False)
        monkeypatch.delenv("WEBHOOK_ALLOW_MISSING_SECRET", raising=False)

        before = _read_counter_value("/webhooks/")

        async def downstream(scope, receive, send):
            raise AssertionError(
                "downstream НЕ должен быть вызван при missing secret",
            )

        app = AsyncMock()
        app.side_effect = downstream
        mw = WebhookSignatureMiddleware(
            app=app,
            path_prefixes=("/webhooks/",),
            secrets_by_prefix={},  # No secret для protected path.
        )

        send = AsyncMock()
        await mw(
            _make_scope("/webhooks/stripe"),
            _make_receive(b'{"event":"test"}'),
            send,
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 503

        body = _body_message(send)
        assert body is not None
        parsed = json.loads(body["body"].decode("utf-8"))
        assert parsed["error"] == "webhook_not_configured"
        assert "secret" in parsed["detail"].lower()

        # Downstream НЕ вызван.
        app.assert_not_called()

        # Метрика инкрементирована.
        after = _read_counter_value("/webhooks/")
        assert after == before + 1

    @pytest.mark.asyncio
    async def test_webhook_signature_missing_secret_does_not_call_downstream(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Cycle 33 invariant: при 503 downstream НЕ вызывается."""
        monkeypatch.delenv("APP_ENVIRONMENT", raising=False)
        monkeypatch.delenv("WEBHOOK_ALLOW_MISSING_SECRET", raising=False)

        async def downstream(scope, receive, send):
            raise AssertionError("downstream должен быть skipped")

        app = AsyncMock()
        app.side_effect = downstream
        mw = WebhookSignatureMiddleware(
            app=app,
            path_prefixes=("/webhooks/",),
            secrets_by_prefix={},
        )

        send = AsyncMock()
        await mw(
            _make_scope("/webhooks/stripe"),
            _make_receive(b"{}"),
            send,
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 503
        app.assert_not_called()

    @pytest.mark.asyncio
    async def test_dev_escape_with_both_env_vars(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """APP_ENVIRONMENT=dev + WEBHOOK_ALLOW_MISSING_SECRET=true → passthrough."""
        monkeypatch.setenv("APP_ENVIRONMENT", "dev")
        monkeypatch.setenv("WEBHOOK_ALLOW_MISSING_SECRET", "true")

        app = AsyncMock()
        app.side_effect = _downstream_ok()
        mw = WebhookSignatureMiddleware(
            app=app,
            path_prefixes=("/webhooks/",),
            secrets_by_prefix={},
        )

        send = AsyncMock()
        await mw(
            _make_scope("/webhooks/stripe"),
            _make_receive(b"{}"),
            send,
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200

    @pytest.mark.asyncio
    async def test_dev_escape_requires_both_env_vars(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Только opt-in env var БЕЗ APP_ENVIRONMENT=dev → 503 (fail-closed)."""
        monkeypatch.delenv("APP_ENVIRONMENT", raising=False)
        monkeypatch.setenv("WEBHOOK_ALLOW_MISSING_SECRET", "true")

        async def downstream(scope, receive, send):
            raise AssertionError("downstream должен быть skipped без dev env")

        app = AsyncMock()
        app.side_effect = downstream
        mw = WebhookSignatureMiddleware(
            app=app,
            path_prefixes=("/webhooks/",),
            secrets_by_prefix={},
        )

        send = AsyncMock()
        await mw(
            _make_scope("/webhooks/stripe"),
            _make_receive(b"{}"),
            send,
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 503

    @pytest.mark.asyncio
    async def test_dev_env_alone_does_not_escape(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """APP_ENVIRONMENT=dev БЕЗ opt-in env var → 503 (нет implicit escape)."""
        monkeypatch.setenv("APP_ENVIRONMENT", "dev")
        monkeypatch.delenv("WEBHOOK_ALLOW_MISSING_SECRET", raising=False)

        async def downstream(scope, receive, send):
            raise AssertionError(
                "downstream должен быть skipped без explicit opt-in",
            )

        app = AsyncMock()
        app.side_effect = downstream
        mw = WebhookSignatureMiddleware(
            app=app,
            path_prefixes=("/webhooks/",),
            secrets_by_prefix={},
        )

        send = AsyncMock()
        await mw(
            _make_scope("/webhooks/stripe"),
            _make_receive(b"{}"),
            send,
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 503

    @pytest.mark.asyncio
    async def test_production_with_optin_env_still_fail_closed(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """APP_ENVIRONMENT=production + opt-in → всё равно 503 (defense in depth)."""
        monkeypatch.setenv("APP_ENVIRONMENT", "production")
        monkeypatch.setenv("WEBHOOK_ALLOW_MISSING_SECRET", "true")

        async def downstream(scope, receive, send):
            raise AssertionError("escape НЕ должен сработать в production")

        app = AsyncMock()
        app.side_effect = downstream
        mw = WebhookSignatureMiddleware(
            app=app,
            path_prefixes=("/webhooks/",),
            secrets_by_prefix={},
        )

        send = AsyncMock()
        await mw(
            _make_scope("/webhooks/stripe"),
            _make_receive(b"{}"),
            send,
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 503

    @pytest.mark.asyncio
    async def test_metric_label_uses_most_specific_path_prefix(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Метка path_prefix в counter использует самый специфичный matched prefix."""
        monkeypatch.delenv("APP_ENVIRONMENT", raising=False)
        monkeypatch.delenv("WEBHOOK_ALLOW_MISSING_SECRET", raising=False)

        before = _read_counter_value("/webhooks/stripe/")

        app = AsyncMock()

        async def downstream(scope, receive, send):
            raise AssertionError("downstream должен быть skipped")

        app.side_effect = downstream
        mw = WebhookSignatureMiddleware(
            app=app,
            path_prefixes=("/webhooks/", "/webhooks/stripe/"),
            secrets_by_prefix={},  # no secret for any prefix
        )

        send = AsyncMock()
        await mw(
            _make_scope("/webhooks/stripe/payment"),
            _make_receive(b"{}"),
            send,
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 503

        after = _read_counter_value("/webhooks/stripe/")
        assert after == before + 1
