"""S61 W2 — compression.py part of enrichment decomp.

Classes: CompressProcessor, DecompressProcessor.

compression + decompression.
"""

from __future__ import annotations

from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor


class CompressProcessor(BaseProcessor):
    """Compress body через gzip/brotli/zstd.

    Usage::
        .compress(algorithm="gzip")
    """

    def __init__(
        self, *, algorithm: str = "gzip", level: int = 6, name: str | None = None
    ) -> None:
        super().__init__(name=name or f"compress:{algorithm}")
        self._algo = algorithm
        self._level = level

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Обработать exchange согласно логике процессора. Читает body / properties, мутирует exchange, raises exceptions для error handling pipeline."""
        import orjson

        body = exchange.in_message.body
        if isinstance(body, str):
            data = body.encode("utf-8")
        elif isinstance(body, bytes):
            data = body
        else:
            data = orjson.dumps(body, default=str)
        try:
            if self._algo == "gzip":
                import gzip

                compressed = gzip.compress(data, compresslevel=self._level)
            elif self._algo == "brotli":
                import brotli

                compressed = brotli.compress(data, quality=self._level)
            elif self._algo == "zstd":
                import zstandard

                cctx = zstandard.ZstdCompressor(level=self._level)
                compressed = cctx.compress(data)
            else:
                exchange.fail(f"Unknown compression algorithm: {self._algo}")
                return
            exchange.set_property("compress_original_size", len(data))
            exchange.set_property(
                "compress_ratio", round(len(compressed) / max(len(data), 1), 3)
            )
            exchange.set_out(body=compressed, headers=dict(exchange.in_message.headers))
        except ImportError as exc:
            exchange.fail(f"Compression library missing: {exc}")

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализовать конфигурацию процессора в dict (для YAML/JSON spec). Returns None для non-serializable state."""
        spec: dict[str, Any] = {}
        if self._algo != "gzip":
            spec["algorithm"] = self._algo
        if self._level != 6:
            spec["level"] = self._level
        return {"compress": spec}


class DecompressProcessor(BaseProcessor):
    """Decompress body (auto-detect или указанный algorithm)."""

    def __init__(self, *, algorithm: str = "auto", name: str | None = None) -> None:
        super().__init__(name=name or f"decompress:{algorithm}")
        self._algo = algorithm

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Обработать exchange согласно логике процессора. Читает body / properties, мутирует exchange, raises exceptions для error handling pipeline."""
        body = exchange.in_message.body
        if not isinstance(body, bytes):
            exchange.fail("DecompressProcessor requires bytes body")
            return
        algo = self._algo
        if algo == "auto":
            if body[:2] == b"\x1f\x8b":
                algo = "gzip"
            elif body[:4] == b"(\xb5/\xfd":
                algo = "zstd"
            else:
                algo = "brotli"
        try:
            if algo == "gzip":
                import gzip

                data = gzip.decompress(body)
            elif algo == "brotli":
                import brotli

                data = brotli.decompress(body)
            elif algo == "zstd":
                import zstandard

                dctx = zstandard.ZstdDecompressor()
                data = dctx.decompress(body)
            else:
                exchange.fail(f"Unknown algorithm: {algo}")
                return
            exchange.set_out(body=data, headers=dict(exchange.in_message.headers))
        except ImportError as exc:
            exchange.fail(f"Decompression library missing: {exc}")
        except Exception as exc:
            exchange.fail(f"Decompress failed: {exc}")

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализовать конфигурацию процессора в dict (для YAML/JSON spec). Returns None для non-serializable state."""
        spec: dict[str, Any] = {}
        if self._algo != "auto":
            spec["algorithm"] = self._algo
        return {"decompress": spec}
