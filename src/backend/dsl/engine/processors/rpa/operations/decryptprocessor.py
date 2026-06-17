"""S65 W2 — DecryptProcessor extracted from rpa/operations.py.

Per-processor file split.
"""

from __future__ import annotations

from typing import Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

_rpa_logger = get_logger("dsl.rpa")


class DecryptProcessor(BaseProcessor):
    """AES расшифровка body через Fernet.

    key: тот же Fernet-ключ что при шифровании.
    Результат: bytes (расшифрованные данные).

    Args:
        key: Fernet-ключ.
        source: W34 — где читать encrypted input.
        target: W34 — куда писать decrypted result.
        name: имя процессора.
    """

    def __init__(
        self,
        key: str,
        *,
        source: str = "body",
        target: str | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "decrypt")
        self._key = key
        self._source = source
        self._target = target

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Обработать exchange согласно логике процессора. Читает body / properties, мутирует exchange, выбрасывает exceptions для error handling pipeline."""
        try:
            from cryptography.fernet import Fernet
        except ImportError:
            exchange.fail("cryptography not installed: pip install cryptography")
            return
        # W34: source resolution.
        if self._source == "body":
            body = exchange.in_message.body
        else:
            body = exchange.properties.get(self._source)
        if not isinstance(body, bytes):
            exchange.fail("decrypt expects bytes (encrypted data)")
            return
        try:
            f = Fernet(self._key.encode() if isinstance(self._key, str) else self._key)
            decrypted = f.decrypt(body)
            # W34: target resolution.
            if self._target is None or self._target == "body":
                exchange.set_out(body=decrypted, headers=dict(exchange.in_message.headers))
            else:
                exchange.set_property(self._target, decrypted)
        except Exception as exc:
            exchange.fail(f"Decryption failed: {exc}")

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализовать конфигурацию процессора в dict. Возвращает None для non-serializable runtime state."""
        # ponytail: don't leak encryption key in serialized spec
        spec: dict[str, Any] = {"key": "***"}
        if self._source != "body":
            spec["source"] = self._source
        if self._target is not None:
            spec["target"] = self._target
        return {"decrypt": spec}
