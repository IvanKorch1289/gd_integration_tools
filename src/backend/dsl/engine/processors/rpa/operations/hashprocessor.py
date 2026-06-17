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

    Args:
        algorithm: ``md5`` / ``sha256`` / ``sha512``.
        source: W34 — где читать input (``"body"`` для in_message.body,
            или property name для ``exchange.properties[source]``).
        target: W34 — куда писать result (``"body"`` для set_out, или
            property name для ``exchange.set_property(target, ...)``).
        name: имя процессора для observability.
    """

    def __init__(
        self,
        *,
        algorithm: str = "sha256",
        source: str = "body",
        target: str | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"hash:{algorithm}")
        self._algorithm = algorithm
        self._source = source
        self._target = target

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Обработать exchange согласно логике процессора. Читает body / properties, мутирует exchange, выбрасывает exceptions для error handling pipeline."""
        import hashlib

        # W34: source resolution (body vs property).
        if self._source == "body":
            body = exchange.in_message.body
        else:
            body = exchange.properties.get(self._source)
        if isinstance(body, str):
            data = body.encode("utf-8")
        elif isinstance(body, bytes):
            data = body
        else:
            import orjson

            data = orjson.dumps(body, default=str)
        h = hashlib.new(self._algorithm, data)
        result = h.hexdigest()

        # W34: target resolution (set_out vs set_property).
        if self._target is None or self._target == "body":
            exchange.set_out(body=result, headers=dict(exchange.in_message.headers))
            exchange.set_property("hash_algorithm", self._algorithm)
        else:
            exchange.set_property(self._target, result)
            exchange.set_property("hash_algorithm", self._algorithm)

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализовать конфигурацию процессора в dict. Возвращает None для non-serializable runtime state."""
        spec: dict[str, Any] = {}
        if self._algorithm != "sha256":
            spec["algorithm"] = self._algorithm
        if self._source != "body":
            spec["source"] = self._source
        if self._target is not None:
            spec["target"] = self._target
        return {"hash": spec}
