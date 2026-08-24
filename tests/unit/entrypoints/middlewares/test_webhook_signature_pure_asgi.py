"""Pure ASGI regression-тесты для WebhookSignatureMiddleware (cycle 44).

HMAC-SHA256 signature verification для входящих webhooks
(Stripe-style). Cycle 44: переписано с BaseHTTPMiddleware на pure
ASGI — body буферизуется в middleware, re-injected для downstream.
"""


from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest

from src.backend.entrypoints.middlewares.webhook_signature import (
    WebhookSignatureMiddleware,
)


def _start_message(send: AsyncMock) -> dict | None:
    for call in send.await_args_list:
        msg = call.args[0]
        if msg["type"] == "http.response.start":
            return msg
    return None


def _compute_signature(body: bytes, secret: str, timestamp: int) -> str:
    """Реальный HMAC-SHA256 для valid signature (round-trip с infra.security)."""
    from src.backend.infrastructure.security.signatures import sign_payload

    sig, _ = sign_payload(body, secret, timestamp)
    return sig


def _downstream_ok():
    """Downstream возвращающий 200 OK."""

    async def downstream(scope, receive, send):
        # consume body to verify replay works
        body = b""
        more_body = True
        while more_body:
            msg = await receive()
            if msg["type"] == "http.disconnect":
                break
            body += msg.get("body", b"")
            more_body = msg.get("more_body", False)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    return downstream


def _make_scope(
    method: str, path: str, headers: list[tuple[bytes, bytes]] | None = None
) -> dict:
    return {
        "type": "http",
        "method": method,
        "url": f"http://test{path}",
        "path": path,
        "headers": headers or [],
    }


def _make_receive(body: bytes):
    """ASGI receive callable возвращающая body chunk(s)."""

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return receive


class TestWebhookSignatureMiddlewarePureASGI:
    """Cycle 44: pure ASGI regression-тесты для WebhookSignatureMiddleware."""

    @pytest.mark.asyncio
    async def test_unprotected_path_passes_through(self) -> None:
        """Path вне prefix-allowlist → пробрасывается без verify."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        mw = WebhookSignatureMiddleware(app=app, path_prefixes=("/webhooks/",))

        send = AsyncMock()
        await mw(
            _make_scope("POST", "/api/v1/users"), _make_receive(b'{"test": 1}'), send
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200

    @pytest.mark.asyncio
    async def test_valid_signature_passes_through(self) -> None:
        """Valid HMAC signature → пробрасывает downstream с body replay."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        secret = "wh_secret_test"
        mw = WebhookSignatureMiddleware(
            app=app,
            path_prefixes=("/webhooks/",),
            secrets_by_prefix={"/webhooks/": secret},
        )

        body = b'{"event": "test"}'
        ts = int(time.time())
        sig = _compute_signature(body, secret, ts)

        headers = [
            (b"x-webhook-signature", sig.encode("latin-1")),
            (b"x-webhook-timestamp", str(ts).encode("latin-1")),
            (b"content-type", b"application/json"),
        ]
        send = AsyncMock()
        await mw(
            _make_scope("POST", "/webhooks/stripe", headers=headers),
            _make_receive(body),
            send,
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200

    @pytest.mark.asyncio
    async def test_invalid_signature_returns_401(self) -> None:
        """Invalid signature → 401 через send (no-raise, cycle 39)."""
        app = AsyncMock()

        async def downstream(scope, receive, send):
            raise AssertionError("downstream НЕ должен быть вызван")

        app.side_effect = downstream
        secret = "wh_secret_test"
        mw = WebhookSignatureMiddleware(
            app=app,
            path_prefixes=("/webhooks/",),
            secrets_by_prefix={"/webhooks/": secret},
        )

        body = b'{"event": "test"}'
        ts = int(time.time())
        # Wrong signature (valid format, wrong content).
        sig = "0" * 64  # 64 hex chars but wrong HMAC.

        headers = [
            (b"x-webhook-signature", sig.encode("latin-1")),
            (b"x-webhook-timestamp", str(ts).encode("latin-1")),
        ]
        send = AsyncMock()
        await mw(
            _make_scope("POST", "/webhooks/stripe", headers=headers),
            _make_receive(body),
            send,
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 401

    @pytest.mark.asyncio
    async def test_missing_signature_headers_returns_401(self) -> None:
        """Missing signature/timestamp headers → 401."""
        app = AsyncMock()
        secret = "wh_secret_test"
        mw = WebhookSignatureMiddleware(
            app=app,
            path_prefixes=("/webhooks/",),
            secrets_by_prefix={"/webhooks/": secret},
        )

        send = AsyncMock()
        await mw(_make_scope("POST", "/webhooks/stripe"), _make_receive(b"{}"), send)

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 401

    @pytest.mark.asyncio
    async def test_invalid_timestamp_header_returns_401(self) -> None:
        """Non-integer timestamp → 401."""
        app = AsyncMock()
        secret = "wh_secret_test"
        mw = WebhookSignatureMiddleware(
            app=app,
            path_prefixes=("/webhooks/",),
            secrets_by_prefix={"/webhooks/": secret},
        )

        headers = [
            (b"x-webhook-signature", b"0" * 64),
            (b"x-webhook-timestamp", b"not-a-number"),
        ]
        send = AsyncMock()
        await mw(
            _make_scope("POST", "/webhooks/stripe", headers=headers),
            _make_receive(b"{}"),
            send,
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 401

    @pytest.mark.asyncio
    async def test_protected_prefix_without_secret_returns_503(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """B-02 fix: path protected, но secret не сконфигурирован → 503 fail-closed.

        Раньше этот тест проверял fail-open (skip-verify с warning).
        Cycle 33 B-02: protected path без secret = misconfiguration
        = потенциальный обход подписи. Возвращаем 503 и инкрементируем
        ``webhook_signature_missing_secret_total`` для алертинга.
        Dev escape требует явного opt-in (см. test_webhook_signature.py).
        """
        monkeypatch.delenv("APP_ENVIRONMENT", raising=False)
        monkeypatch.delenv("WEBHOOK_ALLOW_MISSING_SECRET", raising=False)

        async def downstream(scope, receive, send):
            raise AssertionError(
                "downstream НЕ должен быть вызван при missing secret",
            )
    async def test_protected_prefix_without_secret_passes(self) -> None:
        """Path protected, но secret не сконфигурирован → fail-closed (503) по default.

        Используется явный ``fail_closed=False`` (dev/test opt-out).
        Request passes through to downstream (which returns 200).

        S44 W31: original test referenced ``downstream`` which was defined
        in the previous test method scope (test_protected_prefix_without_secret_returns_503).
        Define ``downstream`` locally to fix NameError. Also fix the
        downstream to actually send a 200 response (production behavior:
        fail_closed=False + no secret → call self.app which is downstream).
        """

        async def downstream(scope, receive, send):  # noqa: ARG001
            """Downstream sends 200 OK (simulates success)."""
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": b'{"ok": true}',
                }
            )

        app = AsyncMock()
        app.side_effect = downstream
        mw = WebhookSignatureMiddleware(
            app=app,
            path_prefixes=("/webhooks/",),
            secrets_by_prefix={},  # No secret для protected path.
            fail_closed=False,
        )

        send = AsyncMock()
        await mw(_make_scope("POST", "/webhooks/stripe"), _make_receive(b"{}"), send)

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200

    @pytest.mark.asyncio
    async def test_protected_prefix_without_secret_fail_closed_returns_503(
        self,
    ) -> None:
        """Default fail_closed=True: missing secret → 503 (server misconfiguration)."""
        app = AsyncMock()

        async def downstream(scope, receive, send):
            raise AssertionError("downstream НЕ должен быть вызван при 503")

        app.side_effect = downstream
        mw = WebhookSignatureMiddleware(
            app=app,
            path_prefixes=("/webhooks/",),
            secrets_by_prefix={},  # No secret для protected path.
        )

        send = AsyncMock()
        await mw(_make_scope("POST", "/webhooks/stripe"), _make_receive(b"{}"), send)

        send = AsyncMock()
        await mw(_make_scope("POST", "/webhooks/stripe"), _make_receive(b"{}"), send)

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 503
        # Проверяем тело ответа с detail.
        body_msgs = [
            c.args[0]
            for c in send.await_args_list
            if c.args[0]["type"] == "http.response.body"
        ]
        assert body_msgs, "503 response должен содержать body с detail"
        body = body_msgs[0]["body"].decode("utf-8")
        assert "not configured" in body.lower()

    @pytest.mark.asyncio
    async def test_most_specific_prefix_wins(self) -> None:
        """Если multiple prefixes match — наиболее специфичный (длинный) wins."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        # Два secret'а: /webhooks/stripe/ (более специфичный) и /webhooks/.
        # Для path /webhooks/stripe/payment — должен использоваться
        # /webhooks/stripe/ secret.
        secret_specific = "secret_specific"
        secret_generic = "secret_generic"
        mw = WebhookSignatureMiddleware(
            app=app,
            path_prefixes=("/webhooks/",),
            secrets_by_prefix={
                "/webhooks/": secret_generic,
                "/webhooks/stripe/": secret_specific,
            },
        )

        body = b'{"event": "stripe"}'
        ts = int(time.time())
        sig = _compute_signature(body, secret_specific, ts)

        headers = [
            (b"x-webhook-signature", sig.encode("latin-1")),
            (b"x-webhook-timestamp", str(ts).encode("latin-1")),
        ]
        send = AsyncMock()
        await mw(
            _make_scope("POST", "/webhooks/stripe/payment", headers=headers),
            _make_receive(body),
            send,
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200

    @pytest.mark.asyncio
    async def test_passes_through_non_http_scope(self) -> None:
        """Non-HTTP scope (websocket) пробрасывается без verify."""
        app = AsyncMock()

        async def downstream(scope, receive, send):
            await send({"type": "websocket.accept"})

        app.side_effect = downstream
        mw = WebhookSignatureMiddleware(app=app)

        send = AsyncMock()
        await mw(
            {"type": "websocket", "path": "/webhooks/stripe", "headers": []},
            AsyncMock(),
            send,
        )

        msgs = [c.args[0] for c in send.await_args_list]
        assert any(m["type"] == "websocket.accept" for m in msgs)

    @pytest.mark.asyncio
    async def test_does_not_call_downstream_when_invalid(self) -> None:
        """Cycle 44 invariant: при 401 downstream НЕ вызывается."""
        app = AsyncMock()

        async def downstream(scope, receive, send):
            raise AssertionError("downstream НЕ должен быть вызван")

        app.side_effect = downstream
        secret = "wh_secret_test"
        mw = WebhookSignatureMiddleware(
            app=app,
            path_prefixes=("/webhooks/",),
            secrets_by_prefix={"/webhooks/": secret},
        )

        body = b'{"event": "test"}'
        ts = int(time.time())
        sig = "0" * 64  # wrong signature

        headers = [
            (b"x-webhook-signature", sig.encode("latin-1")),
            (b"x-webhook-timestamp", str(ts).encode("latin-1")),
        ]
        send = AsyncMock()
        await mw(
            _make_scope("POST", "/webhooks/stripe", headers=headers),
            _make_receive(body),
            send,
        )

        # 401 отправлен.
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 401
