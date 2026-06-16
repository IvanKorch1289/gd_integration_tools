"""S63 W3 — processors.py part of marshal decomp.

MarshalProcessor + UnmarshalProcessor.
"""

from __future__ import annotations

import threading
from typing import Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind

# Security: defusedxml guards against XXE / billion-laughs in XML unmarshal.
# ``pickle`` and ``xml.etree.ElementTree`` are stdlib defaults but unsafe for
# untrusted input — we import defusedxml lazily and use it for the public
# surface; stdlib ET is only used for the controlled marshal path (we generate
# the tree ourselves from a dict, never parse untrusted XML).
try:
    import defusedxml.ElementTree as DET  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover — dev-light fallback
    DET = None  # type: ignore[assignment]
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error
from src.backend.dsl.engine.processors.eip.marshal.base import (
    DataFormat,  # S63 W3: cross-import
)

_log = get_logger(__name__)

# ── DataFormat abstract + concrete impls ─────────────────────────────


class MarshalProcessor(BaseProcessor):
    """Конвертация in-memory object → wire format (Camel Marshal).

    Args:
        data_format: ``DataFormat`` instance (e.g., ``JsonDataFormat()``).
        content_type_header: имя header для ``Content-Type`` (default
            ``content_type``). Если exchange содержит значение — оно
            перезаписывается через ``DataFormat.content_type``.
        encoding_header: имя header для charset (default ``encoding``).
        name: имя процессора.

    Body in: ``Any``. Body out: ``bytes`` (или ``str`` для XML pretty).
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(
        self,
        data_format: DataFormat,
        *,
        content_type_header: str = "content_type",
        encoding_header: str = "encoding",
        name: str | None = None,
    ) -> None:
        if data_format is None:
            raise ValueError("MarshalProcessor: data_format is required")
        super().__init__(name=name or f"marshal_{data_format.name}")
        self._data_format = data_format
        self._content_type_header = content_type_header
        self._encoding_header = encoding_header
        self._lock = threading.Lock()
        self._count = 0

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        encoded = self._data_format.marshal(exchange.in_message.body)
        exchange.in_message.body = encoded
        exchange.in_message.set_header(
            self._content_type_header, self._data_format.content_type
        )
        if isinstance(encoded, bytes):
            exchange.in_message.set_header(self._encoding_header, "utf-8")
        with self._lock:
            self._count += 1
        _log.debug(
            "Marshal[%s]: encoded %d bytes", self._data_format.name, len(encoded)
        )

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {"marshals": self._count}

    def to_spec(self) -> dict[str, Any] | None:
        return {
            "type": "marshal",
            "format": self._data_format.name,
            "content_type": self._data_format.content_type,
        }


class UnmarshalProcessor(BaseProcessor):
    """Конвертация wire format → in-memory object (Camel Unmarshal).

    Args:
        data_format: ``DataFormat`` instance.
        target_type: optional constructor hint (e.g., ``dict``, ``list``,
            ``MyModel``). Если None — DataFormat решает сам.
        content_type_header: имя header для проверки (default ``content_type``).
            Если задан и в header тип, который НЕ соответствует
            ``data_format.content_type`` — warning + proceed anyway.
        name: имя процессора.

    Body in: ``bytes`` / ``str``. Body out: ``Any``.
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(
        self,
        data_format: DataFormat,
        *,
        target_type: type | None = None,
        content_type_header: str = "content_type",
        strict_content_type: bool = False,
        name: str | None = None,
    ) -> None:
        if data_format is None:
            raise ValueError("UnmarshalProcessor: data_format is required")
        super().__init__(name=name or f"unmarshal_{data_format.name}")
        self._data_format = data_format
        self._target_type = target_type
        self._content_type_header = content_type_header
        self._strict_content_type = strict_content_type
        self._lock = threading.Lock()
        self._count = 0

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        if strict_content_type_check := self._strict_content_type:
            existing_ct = exchange.in_message.get_header(self._content_type_header)
            if (
                existing_ct
                and str(existing_ct) != self._data_format.content_type
                and strict_content_type_check
            ):
                _log.warning(
                    "Unmarshal[%s]: content_type mismatch: header=%s expected=%s",
                    self._data_format.name,
                    existing_ct,
                    self._data_format.content_type,
                )
        decoded = self._data_format.unmarshal(body, self._target_type)
        exchange.in_message.body = decoded
        with self._lock:
            self._count += 1
        _log.debug("Unmarshal[%s]: decoded", self._data_format.name)

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {"unmarshals": self._count}

    def to_spec(self) -> dict[str, Any] | None:
        return {
            "type": "unmarshal",
            "format": self._data_format.name,
            "target_type": (
                self._target_type.__name__ if self._target_type is not None else None
            ),
        }
