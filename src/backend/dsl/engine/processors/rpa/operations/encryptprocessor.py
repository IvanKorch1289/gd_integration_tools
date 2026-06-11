from __future__ import annotations

"""S65 W2 — EncryptProcessor extracted from rpa/operations.py.

Per-processor file split.
"""

from typing import Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

_rpa_logger = get_logger("dsl.rpa")


class EncryptProcessor(BaseProcessor):
    """AES шифрование body через Fernet (symmetric).

    key: Fernet-совместимый ключ (base64-encoded 32 bytes).
    Результат: bytes (зашифрованные данные).
    """

    def __init__(self, key: str, *, name: str | None = None) -> None:
        super().__init__(name=name or "encrypt")
        self._key = key

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Обработать exchange согласно логике процессора. Читает body / properties, мутирует exchange, выбрасывает exceptions для error handling pipeline."""
        try:
            from cryptography.fernet import Fernet
        except ImportError:
            exchange.fail("cryptography not installed: pip install cryptography")
            return
        body = exchange.in_message.body
        if isinstance(body, str):
            data = body.encode("utf-8")
        elif isinstance(body, bytes):
            data = body
        else:
            import orjson

            data = orjson.dumps(body, default=str)
        try:
            f = Fernet(self._key.encode() if isinstance(self._key, str) else self._key)
            encrypted = f.encrypt(data)
            exchange.set_out(body=encrypted, headers=dict(exchange.in_message.headers))
        except Exception as exc:
            exchange.fail(f"Encryption failed: {exc}")

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализовать конфигурацию процессора в dict. Возвращает None для non-serializable runtime state."""
        return {"encrypt": {"key": self._key}}
