"""S65 W2 — HashProcessor extracted from rpa/operations.py.

Per-processor file split.
"""

from __future__ import annotations

from typing import Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

_rpa_logger = get_logger("dsl.rpa")


class HashProcessor(BaseProcessor):
    """Вычисляет hash от body.

    Поддерживает: md5, sha256, sha512. Результат: hex string.
    """

    def __init__(self, *, algorithm: str = "sha256", name: str | None = None) -> None:
        super().__init__(name=name or f"hash:{algorithm}")
        self._algorithm = algorithm

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Обработать exchange согласно логике процессора. Читает body / properties, мутирует exchange, выбрасывает exceptions для error handling pipeline."""
        import hashlib

        body = exchange.in_message.body
        if isinstance(body, str):
            data = body.encode("utf-8")
        elif isinstance(body, bytes):
            data = body
        else:
            import orjson

            data = orjson.dumps(body, default=str)
        h = hashlib.new(self._algorithm, data)
        exchange.set_out(body=h.hexdigest(), headers=dict(exchange.in_message.headers))
        exchange.set_property("hash_algorithm", self._algorithm)

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализовать конфигурацию процессора в dict. Возвращает None для non-serializable runtime state."""
        spec: dict[str, Any] = {}
        if self._algorithm != "sha256":
            spec["algorithm"] = self._algorithm
        return {"hash": spec}
