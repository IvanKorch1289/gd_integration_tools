"""Converters / format / data-quality / transform-helpers миксин.

Группа: convert / convert_units / parse_ics / jsonpath / regex / hash /
encrypt / decrypt / render_template / format_text / pdf_* / word_* /
excel_* / ocr / image_resize / archive / compress / decompress /
dq_check / export / web_search / markdown_to_html / html_to_markdown /
avro_* / protobuf_* / toml_* / jsonl_* / polars_* / dask_compute /
duckdb_query / transform helpers (as_, pick, drop, merge, batch_window,
deduplicate, debounce, batch_by_field, poll_and_aggregate,
filter_dispatch, cache_response, geoip).

Stateless — см. контракт в ``base.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backend.dsl.builder import RouteBuilder


class ConvertersMixin:
    """Поведенческий миксин converters/transform-helpers для ``RouteBuilder``.

    Stage 2.1 PoC: первая партия методов перенесена из ``dsl/builder.py``
    (hash / encrypt / decrypt / compress / decompress). Остальные ~34 метода
    (convert / parse_ics / jsonpath / regex / archive / pdf_* / word_* / excel_* /
    polars_* / dask_compute / duckdb_query / transform helpers) — следующими
    порциями в Stage 2.1 продолжении.
    """

    __slots__ = ()  # type: ignore[var-annotated]

    def hash(self, *, algorithm: str = "sha256") -> RouteBuilder:
        """Hash данных (sha256/md5/sha512)."""
        return self._add_lazy(  # type: ignore[attr-defined,no-any-return]
            "src.backend.dsl.engine.processors.rpa",
            "HashProcessor",
            algorithm=algorithm,
        )

    def encrypt(self, key: str) -> RouteBuilder:
        """AES шифрование (Fernet)."""
        return self._add_lazy(  # type: ignore[attr-defined,no-any-return]
            "src.backend.dsl.engine.processors.rpa", "EncryptProcessor", key=key
        )

    def decrypt(self, key: str) -> RouteBuilder:
        """AES расшифровка (Fernet)."""
        return self._add_lazy(  # type: ignore[attr-defined,no-any-return]
            "src.backend.dsl.engine.processors.rpa", "DecryptProcessor", key=key
        )

    def compress(self, *, algorithm: str = "gzip", level: int = 6) -> RouteBuilder:
        """Сжатие body (gzip/brotli/zstd)."""
        return self._add_lazy(  # type: ignore[attr-defined,no-any-return]
            "src.backend.dsl.engine.processors.enrichment",
            "CompressProcessor",
            algorithm=algorithm,
            level=level,
        )

    def decompress(self, *, algorithm: str = "auto") -> RouteBuilder:
        """Распаковка body (auto-detect или явный algorithm)."""
        return self._add_lazy(  # type: ignore[attr-defined,no-any-return]
            "src.backend.dsl.engine.processors.enrichment",
            "DecompressProcessor",
            algorithm=algorithm,
        )
