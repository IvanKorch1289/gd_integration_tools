"""CodecFacade — capability-checked фасад для кодирования/декодирования.

Предоставляет единый API для работы с различными форматами:
JSON (orjson), Base64, msgpack (опционально).

Контракт:
* encode/decode операции не требуют capability-check (pure функциональность).

Используется DSL-процессорами и extensions для сериализации данных.
"""

from __future__ import annotations

from typing import Any

from src.backend.core.errors import ServiceError
from src.backend.core.logging import get_logger

__all__ = ("CodecFacade",)

_logger = get_logger("services.codec.facade")

SUPPORTED_FORMATS = frozenset({"json", "base64", "msgpack"})


class CodecFacade:
    """Unified facade for encoding/decoding across formats.

    Usage::

        codec = CodecFacade()
        data = await codec.encode({"key": "value"}, format="json")
        result = await codec.decode(data, format="json")
    """

    def __init__(self) -> None:
        self._msgpack_available: bool | None = None

    def _check_format(self, fmt: str) -> None:
        if fmt not in SUPPORTED_FORMATS:
            raise ValueError(
                f"Unsupported format: {fmt}. Use one of: {SUPPORTED_FORMATS}"
            )

    async def encode(self, data: Any, *, fmt: str = "json") -> bytes:
        """Encode data to bytes in specified format.

        Args:
            data: Data to encode.
            fmt: Format: ``"json"``, ``"base64"``, ``"msgpack"``.

        Returns:
            Encoded bytes.

        Raises:
            ValueError: Unsupported format.
            ServiceError: Encoding error.
        """
        self._check_format(fmt)
        try:
            if fmt == "json":
                return self._encode_json(data)
            if fmt == "base64":
                return self._encode_base64(data)
            if fmt == "msgpack":
                return self._encode_msgpack(data)
        except Exception as exc:
            _logger.warning("CodecFacade encode failed fmt=%s: %s", fmt, exc)
            raise ServiceError(f"codec encode failed: {exc}") from exc
        raise ValueError(f"Unsupported format: {fmt}")  # pragma: no cover

    async def decode(self, data: bytes, *, fmt: str = "json") -> Any:
        """Decode bytes from specified format.

        Args:
            data: Bytes to decode.
            fmt: Format: ``"json"``, ``"base64"``, ``"msgpack"``.

        Returns:
            Decoded data.

        Raises:
            ValueError: Unsupported format.
            ServiceError: Decoding error.
        """
        self._check_format(fmt)
        try:
            if fmt == "json":
                return self._decode_json(data)
            if fmt == "base64":
                return self._decode_base64(data)
            if fmt == "msgpack":
                return self._decode_msgpack(data)
        except Exception as exc:
            _logger.warning("CodecFacade decode failed fmt=%s: %s", fmt, exc)
            raise ServiceError(f"codec decode failed: {exc}") from exc
        raise ValueError(f"Unsupported format: {fmt}")  # pragma: no cover

    def _encode_json(self, data: Any) -> bytes:
        import orjson

        from src.backend.dsl.codec.json import to_jsonable

        return orjson.dumps(to_jsonable(data))

    def _decode_json(self, data: bytes) -> Any:
        import orjson

        return orjson.loads(data)

    def _encode_base64(self, data: Any) -> bytes:
        from base64 import b64encode

        if isinstance(data, bytes):
            return b64encode(data)
        if isinstance(data, str):
            return b64encode(data.encode("utf-8"))
        # For complex types, JSON-serialize first then base64
        json_bytes = self._encode_json(data)
        return b64encode(json_bytes)

    def _decode_base64(self, data: bytes) -> Any:
        from base64 import b64decode

        decoded = b64decode(data)
        # Try to parse as JSON first
        try:
            return self._decode_json(decoded)
        except Exception:
            # Return raw bytes or string
            try:
                return decoded.decode("utf-8")
            except UnicodeDecodeError:
                return decoded

    def _encode_msgpack(self, data: Any) -> bytes:
        if self._msgpack_available is None:
            try:
                import msgpack  # noqa: F401

                self._msgpack_available = True
            except ImportError:
                self._msgpack_available = False
        if not self._msgpack_available:
            raise ServiceError("msgpack not installed")
        import msgpack

        from src.backend.dsl.codec.json import to_jsonable

        return msgpack.packb(to_jsonable(data), use_bin_type=True)

    def _decode_msgpack(self, data: bytes) -> Any:
        if self._msgpack_available is None:
            try:
                import msgpack  # noqa: F401

                self._msgpack_available = True
            except ImportError:
                self._msgpack_available = False
        if not self._msgpack_available:
            raise ServiceError("msgpack not installed")
        import msgpack

        return msgpack.unpackb(data, raw=False)
