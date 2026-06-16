"""S61 W2 — webhook.py part of enrichment decomp.

Classes: WebhookSignProcessor, WebhookSignVerifyProcessor.

webhook sign + verify.
"""

from __future__ import annotations

from typing import Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

logger = get_logger(__name__)


class WebhookSignProcessor(BaseProcessor):
    """Sign outgoing webhook body with HMAC-SHA256.

    Usage::
        .webhook_sign(secret="KEY", header="X-Webhook-Signature")
    """

    def __init__(
        self,
        *,
        secret: str,
        header: str = "X-Webhook-Signature",
        algorithm: str = "sha256",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"webhook_sign:{algorithm}")
        self._secret = secret
        self._header = header
        self._algo = algorithm

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Обработать exchange согласно логике процессора. Читает body / properties, мутирует exchange, raises exceptions для error handling pipeline."""
        import hashlib
        import hmac

        import orjson

        body = exchange.in_message.body
        if isinstance(body, str):
            data = body.encode("utf-8")
        elif isinstance(body, bytes):
            data = body
        else:
            data = orjson.dumps(body, default=str)
        algo = getattr(hashlib, self._algo, None)
        if algo is None:
            exchange.fail(f"Unknown hash algorithm: {self._algo}")
            return
        signature = hmac.new(self._secret.encode(), data, algo).hexdigest()
        exchange.in_message.set_header(self._header, signature)
        exchange.set_property("webhook_signature", signature)

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализовать конфигурацию процессора в dict (для YAML/JSON spec). Returns None для non-serializable state."""
        spec: dict[str, Any] = {"secret": self._secret}
        if self._header != "X-Webhook-Signature":
            spec["header"] = self._header
        if self._algo != "sha256":
            spec["algorithm"] = self._algo
        return {"webhook_sign": spec}


class WebhookSignVerifyProcessor(BaseProcessor):
    """Verify HMAC-SHA256 / JWS подпись входящего webhook (Sprint 9 K3 W5).

    Stripe-style: вычисляет HMAC и сравнивает с заголовком в
    constant-time. Поддерживает префикс ``sha256=`` в значении заголовка.

    Usage::

        .webhook_sign_verify(
            secret="whsec_xxx",
            header="X-Hub-Signature-256",
            algorithm="sha256",
            on_invalid="fail",  # fail | dlq | warn
        )

    Закрывает A-8 техдолг (отсутствие класса в enrichment.py).
    """

    def __init__(
        self,
        *,
        secret: str,
        header: str = "X-Webhook-Signature",
        algorithm: str = "sha256",
        prefix: str = "",
        on_invalid: str = "fail",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"webhook_verify:{algorithm}")
        self._secret = secret
        self._header = header
        self._algo = algorithm
        self._prefix = prefix
        if on_invalid not in {"fail", "dlq", "warn"}:
            raise ValueError(f"on_invalid must be fail/dlq/warn, got {on_invalid!r}")
        self._on_invalid = on_invalid

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Обработать exchange согласно логике процессора. Читает body / properties, мутирует exchange, raises exceptions для error handling pipeline."""
        import hashlib
        import hmac

        import orjson

        received = exchange.in_message.get_header(self._header)
        if not received:
            self._handle_invalid(exchange, f"Missing signature header {self._header!r}")
            return
        if self._prefix and received.startswith(self._prefix):
            received = received[len(self._prefix) :]
        body = exchange.in_message.body
        if isinstance(body, str):
            data = body.encode("utf-8")
        elif isinstance(body, bytes):
            data = body
        else:
            data = orjson.dumps(body, default=str)
        algo = getattr(hashlib, self._algo, None)
        if algo is None:
            self._handle_invalid(exchange, f"Unknown hash algorithm: {self._algo}")
            return
        expected = hmac.new(self._secret.encode(), data, algo).hexdigest()
        if not hmac.compare_digest(expected, received):
            self._handle_invalid(exchange, "Signature mismatch")
            return
        exchange.set_property("webhook_signature_verified", True)

    def _handle_invalid(self, exchange: Exchange[Any], reason: str) -> None:
        exchange.set_property("webhook_signature_error", reason)
        exchange.set_property("webhook_signature_verified", False)
        if self._on_invalid == "fail":
            exchange.fail(f"webhook_sign_verify: {reason}")
        elif self._on_invalid == "dlq":
            exchange.set_property("webhook_signature_dlq", True)
        logger.warning("webhook.signature_invalid", extra={"reason": reason})

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализовать конфигурацию процессора в dict (для YAML/JSON spec). Returns None для non-serializable state."""
        spec: dict[str, Any] = {"secret": self._secret}
        if self._header != "X-Webhook-Signature":
            spec["header"] = self._header
        if self._algo != "sha256":
            spec["algorithm"] = self._algo
        if self._prefix:
            spec["prefix"] = self._prefix
        if self._on_invalid != "fail":
            spec["on_invalid"] = self._on_invalid
        return {"webhook_sign_verify": spec}
