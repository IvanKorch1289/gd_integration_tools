"""IngestFileProcessor (Sprint S5) — конвертация файла в Markdown через markitdown.

Подгружает байты файла (S3 или exchange-property), парсит через
``services.ai.document_parsers.parse_document`` и сохраняет результат
в exchange-property. Используется как pre-step перед ``rag_upsert`` или
``llm_call`` — даёт LLM структурированный Markdown вместо plain-text.

Источники файла (приоритет, как в :class:`ScanFileProcessor`):

1. ``s3_key_from`` — выражение, возвращающее S3-ключ;
2. ``data_property`` — exchange-property с готовыми ``bytes``/``str``.

Использование в YAML::

    - ingest_file:
        s3_key_from: properties.uploaded_key
        mime_from: properties.declared_mime
        result_property: doc_md
        on_unsupported: warn
        engine: auto
"""

from __future__ import annotations
from src.backend.infrastructure.logging.factory import get_logger


from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.engine.processors.entity import _resolve
from src.backend.dsl.registry.processor import processor

__all__ = ("IngestFileProcessor",)

_logger = get_logger("dsl.ingest_file")

_VALID_ON_UNSUPPORTED = frozenset({"fail", "warn"})
_VALID_ENGINE = frozenset({"auto", "markitdown", "legacy"})


@processor("ingest_file", namespace="core", capabilities=("documents.parse",))
class IngestFileProcessor(BaseProcessor):
    """Парсит файл в Markdown/plain-text и сохраняет в exchange-property.

    Результат — dict с полями: ``text``, ``markdown`` (bool),
    ``engine``, ``mime``, ``size_bytes``, ``warnings``, ``filename``.

    Args:
        s3_key_from: Выражение S3-ключа (опционально).
        data_property: Имя exchange-property с ``bytes``/``str`` (опционально).
        mime_from: Выражение для MIME-override (опционально).
        result_property: Куда сохранить результат (default ``ingested_doc``).
        on_unsupported: ``fail`` (default) — exchange.fail() при MIME без
            поддержки; ``warn`` — записать warning, оставить text=None.
        engine: ``auto`` (default) — markitdown→legacy; ``markitdown``
            форсирует markitdown (fail на провале); ``legacy`` — только
            legacy (через disabled markitdown). Sprint S5: ``auto``
            покрывает 95% случаев.
    """

    def __init__(
        self,
        *,
        s3_key_from: str | None = None,
        data_property: str | None = None,
        mime_from: str | None = None,
        result_property: str = "ingested_doc",
        on_unsupported: str = "fail",
        engine: str = "auto",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "ingest_file")
        if not s3_key_from and not data_property:
            raise ValueError(
                "IngestFileProcessor: укажите s3_key_from или data_property"
            )
        if on_unsupported not in _VALID_ON_UNSUPPORTED:
            raise ValueError(
                f"IngestFileProcessor: on_unsupported={on_unsupported!r} не из "
                f"{sorted(_VALID_ON_UNSUPPORTED)}"
            )
        if engine not in _VALID_ENGINE:
            raise ValueError(
                f"IngestFileProcessor: engine={engine!r} не из {sorted(_VALID_ENGINE)}"
            )
        self._s3_key_from = s3_key_from
        self._data_property = data_property
        self._mime_from = mime_from
        self._result_property = result_property
        self._on_unsupported = on_unsupported
        self._engine = engine

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Загружает байты, парсит, сохраняет в property."""
        payload, filename = await self._load_bytes(exchange)
        if payload is None:
            exchange.fail("IngestFileProcessor: не удалось получить байты файла")
            return

        declared_mime: str | None = None
        if self._mime_from:
            value = _resolve(exchange, self._mime_from)
            if value:
                declared_mime = str(value)

        from src.backend.services.ai.document_parsers import parse_document, sniff_mime

        effective_mime = sniff_mime(filename, declared_mime)

        # Принудительный engine: переключаем глобальный settings-флаг
        # на время вызова (in-process; thread-safe не критично — DSL
        # выполнение последовательно в рамках одного exchange).
        try:
            text, meta = await self._invoke_parse(
                parse_document, payload, effective_mime, filename
            )
        except ValueError as exc:
            if self._on_unsupported == "fail":
                exchange.fail(f"IngestFileProcessor: {exc}")
                return
            _logger.warning("IngestFileProcessor: unsupported mime — warn: %s", exc)
            exchange.set_property(
                self._result_property,
                {
                    "text": None,
                    "markdown": False,
                    "engine": "skipped",
                    "mime": effective_mime,
                    "size_bytes": len(payload),
                    "warnings": [str(exc)],
                    "filename": filename,
                },
            )
            return

        exchange.set_property(
            self._result_property,
            {
                "text": text,
                "markdown": bool(meta.get("markdown")),
                "engine": meta.get("engine"),
                "mime": meta.get("mime"),
                "size_bytes": meta.get("size_bytes"),
                "warnings": list(meta.get("warnings") or []),
                "filename": meta.get("filename"),
            },
        )

    async def _invoke_parse(
        self, parse_document, content: bytes, mime: str, filename: str | None
    ):
        """Выбор engine: auto / markitdown / legacy с подменой settings."""
        if self._engine == "auto":
            return await parse_document(content, mime, filename=filename)

        from src.backend.core.config.ai import markitdown_settings

        original = markitdown_settings.engine_enabled
        markitdown_settings.engine_enabled = self._engine == "markitdown"
        try:
            text, meta = await parse_document(content, mime, filename=filename)
            if self._engine == "markitdown" and meta.get("engine") != "markitdown":
                raise ValueError("markitdown engine required but unavailable")
            return text, meta
        finally:
            markitdown_settings.engine_enabled = original

    async def _load_bytes(
        self, exchange: Exchange[Any]
    ) -> tuple[bytes | None, str | None]:
        """Загружает файл из S3 → exchange-property; возвращает (bytes, filename)."""
        filename: str | None = None
        if self._s3_key_from:
            key = _resolve(exchange, self._s3_key_from)
            if key:
                filename = str(key).rsplit("/", 1)[-1]
                try:
                    from src.backend.infrastructure.clients.storage.s3_pool import (
                        s3_client,
                    )

                    data = await s3_client.get_object_bytes(str(key))
                    if data is not None:
                        return data, filename
                except Exception as exc:
                    _logger.warning(
                        "IngestFile: S3 read для key=%r упал: %s — fallback property",
                        key,
                        exc,
                    )

        if self._data_property:
            data = exchange.properties.get(self._data_property)
            if isinstance(data, bytes):
                return data, filename
            if isinstance(data, str):
                return data.encode("utf-8"), filename
        return None, filename

    def to_spec(self) -> dict:
        """YAML-spec round-trip."""
        spec: dict[str, Any] = {
            "result_property": self._result_property,
            "on_unsupported": self._on_unsupported,
            "engine": self._engine,
        }
        if self._s3_key_from is not None:
            spec["s3_key_from"] = self._s3_key_from
        if self._data_property is not None:
            spec["data_property"] = self._data_property
        if self._mime_from is not None:
            spec["mime_from"] = self._mime_from
        return {"ingest_file": spec}
