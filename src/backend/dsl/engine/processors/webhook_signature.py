"""DSL-процессор ``webhook_signature`` — HMAC/JWS-проверка webhooks.

Wave ``[wave:s5/k3-w2-processor-pack-2]``.

Stripe-style проверка signature через библиотеку ``standardwebhooks``
(spec https://www.standardwebhooks.com/). Lazy-import: если библиотека
не установлена, процессор fallback на ручную HMAC-SHA256 проверку.

Контракт DSL::

    .webhook_signature(secret="whsec_xxx", header="webhook-signature")

YAML::

    - webhook_signature:
        secret: ${env.WEBHOOK_SECRET}
        header: webhook-signature
        on_error: fail

Feature flag: ``feature_flags.proc_webhook_signature`` (default-OFF).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from typing import TYPE_CHECKING, Any

from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import processor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


__all__ = ("WebhookSignatureProcessor",)


_ALLOWED_ON_ERROR = frozenset({"fail", "dlq", "warn"})


@processor(
    "webhook_signature",
    namespace="core",
    spec_schema={
        "type": "object",
        "properties": {
            "secret": {"type": "string"},
            "header": {"type": "string"},
            "msg_id_header": {"type": "string"},
            "timestamp_header": {"type": "string"},
            "on_error": {"type": "string", "enum": sorted(_ALLOWED_ON_ERROR)},
        },
        "required": ["secret"],
    },
    capabilities=("auth.webhook_signature.verify",),
    meta={"tier": 1, "category": "security"},
    tags=("webhook", "signature", "hmac", "security"),
)
class WebhookSignatureProcessor(BaseProcessor):
    """Verify HMAC-SHA256 / JWS подпись входящего webhook.

    Args:
        secret: Секрет для подписи (whsec_xxx или просто bytes).
        header: Заголовок с подписью (default ``webhook-signature``).
        msg_id_header: Заголовок с идентификатором сообщения (для standardwebhooks).
        timestamp_header: Заголовок с timestamp (для standardwebhooks).
        on_error: ``fail`` / ``dlq`` / ``warn``.
    """

    def __init__(
        self,
        secret: str,
        *,
        header: str = "webhook-signature",
        msg_id_header: str = "webhook-id",
        timestamp_header: str = "webhook-timestamp",
        on_error: str = "fail",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "webhook_signature")
        if not secret:
            raise ValueError("webhook_signature: secret must be non-empty")
        if on_error not in _ALLOWED_ON_ERROR:
            allowed = ", ".join(sorted(_ALLOWED_ON_ERROR))
            raise ValueError(
                f"webhook_signature: on_error must be one of {allowed}, got {on_error!r}"
            )
        self._secret = secret
        self._header = header
        self._msg_id_header = msg_id_header
        self._timestamp_header = timestamp_header
        self._on_error = on_error

    def _read_body_bytes(self, body: Any) -> bytes:
        if isinstance(body, bytes):
            return body
        if isinstance(body, str):
            return body.encode("utf-8")
        import orjson

        return orjson.dumps(body)

    def _verify_manual(
        self, body_bytes: bytes, signature_header: str, msg_id: str, timestamp: str
    ) -> bool:
        """Ручная HMAC-SHA256 проверка (fallback без standardwebhooks)."""
        # standardwebhooks-формат: v1,<base64>
        if not signature_header:
            return False
        secret_bytes = self._secret
        if secret_bytes.startswith("whsec_"):
            try:
                secret_bytes_raw = base64.b64decode(secret_bytes[len("whsec_") :])
            except Exception as _:  # noqa: BLE001
                secret_bytes_raw = secret_bytes.encode()
        else:
            secret_bytes_raw = secret_bytes.encode()
        signed_payload = f"{msg_id}.{timestamp}.".encode() + body_bytes
        expected = hmac.new(secret_bytes_raw, signed_payload, hashlib.sha256).digest()
        expected_b64 = base64.b64encode(expected).decode()
        # Проверка любого из переданных vN,sig пар
        for part in signature_header.split(" "):
            if "," not in part:
                continue
            _, sig = part.split(",", 1)
            if hmac.compare_digest(sig, expected_b64):
                return True
        return False

    def _handle_failure(self, exchange: "Exchange[Any]", reason: str) -> None:
        message = f"webhook_signature: {reason}"
        match self._on_error:
            case "fail":
                exchange.fail(message)
            case "dlq":
                exchange.set_property("_dlq", True)
                exchange.set_property("_signature_error", reason)
            case "warn":
                exchange.set_property("webhook_signature_status", "warn")
                exchange.set_property("_signature_error", reason)

    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        try:
            from src.backend.core.config.features import feature_flags

            if not feature_flags.proc_webhook_signature:
                exchange.set_property("webhook_signature_status", "skipped")
                return
        except Exception as _:  # noqa: BLE001
            pass

        headers = exchange.in_message.headers
        signature_header = str(headers.get(self._header, "") or "")
        msg_id = str(headers.get(self._msg_id_header, "") or "")
        timestamp = str(headers.get(self._timestamp_header, "") or "")

        if not signature_header:
            self._handle_failure(exchange, "missing signature header")
            return

        body_bytes = self._read_body_bytes(exchange.in_message.body)

        verified = False
        try:
            from standardwebhooks import Webhook  # type: ignore[import-not-found]

            wh = Webhook(self._secret)
            try:
                wh.verify(
                    body_bytes,
                    {
                        "webhook-id": msg_id,
                        "webhook-timestamp": timestamp,
                        "webhook-signature": signature_header,
                    },
                )
                verified = True
            except Exception as _:  # noqa: BLE001
                verified = False
        except ImportError:
            verified = self._verify_manual(
                body_bytes, signature_header, msg_id, timestamp
            )

        if not verified:
            self._handle_failure(exchange, "invalid signature")
            return

        exchange.set_property("webhook_signature_status", "ok")

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {"secret": self._secret}
        if self._header != "webhook-signature":
            spec["header"] = self._header
        if self._msg_id_header != "webhook-id":
            spec["msg_id_header"] = self._msg_id_header
        if self._timestamp_header != "webhook-timestamp":
            spec["timestamp_header"] = self._timestamp_header
        if self._on_error != "fail":
            spec["on_error"] = self._on_error
        return {"webhook_signature": spec}
