"""Markitdown-engine — конвертация документов в Markdown (Sprint S5).

Microsoft markitdown поддерживает PDF/DOCX/PPTX/XLSX/HTML/CSV/JSON и
сохраняет структуру (заголовки, таблицы, списки), что критично для
качества LLM-контекста.

Особенности реализации:

* Lazy ``import markitdown`` — пакет необязателен (fallback на legacy);
* ``tempfile.TemporaryDirectory()`` для on-disk-buffer'а markitdown
  (R-V15-11 leak prevention);
* ``asyncio.wait_for(..., timeout=settings.MARKITDOWN_TIMEOUT_S)`` —
  жёсткий деадлайн (R-V15-13);
* network-isolation default-OFF (см. ``_network.markitdown_network_disabled``).
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

from src.backend.core.config.ai import markitdown_settings
from src.backend.infrastructure.logging.factory import get_logger
from src.backend.services.ai.document_parsers._network import (
    markitdown_network_disabled,
)

__all__ = ("MarkitdownEngine", "MarkitdownUnavailableError")

logger = get_logger(__name__)


_EXT_BY_MIME: dict[str, str] = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "text/html": ".html",
    "text/csv": ".csv",
    "application/json": ".json",
}


class MarkitdownUnavailableError(RuntimeError):
    """markitdown пакет не установлен или инициализация упала."""


class MarkitdownEngine:
    """Конвертер документов в Markdown через Microsoft markitdown.

    Engine ленив: ``markitdown`` импортируется при первом
    :meth:`convert`. Если пакет отсутствует — поднимается
    :class:`MarkitdownUnavailableError` (orchestrator делает fallback
    на legacy).

    Args:
        timeout_s: Таймаут одной конвертации (по умолчанию из settings).
        max_bytes: Максимальный размер документа в байтах.
        network_enabled: ``True`` — разрешить outbound (через WAF, future),
            ``False`` — silent-skip (default).
    """

    def __init__(
        self,
        *,
        timeout_s: int | None = None,
        max_bytes: int | None = None,
        network_enabled: bool | None = None,
    ) -> None:
        self._timeout_s = (
            timeout_s if timeout_s is not None else markitdown_settings.timeout_s
        )
        self._max_bytes = (
            max_bytes if max_bytes is not None else markitdown_settings.max_bytes
        )
        self._network_enabled = (
            network_enabled
            if network_enabled is not None
            else markitdown_settings.network_mode != "off"
        )
        self._md: Any | None = None

    def _ensure_loaded(self) -> Any:
        """Ленивая инициализация markitdown.MarkItDown."""
        if self._md is not None:
            return self._md
        try:
            from markitdown import MarkItDown
        except ImportError as exc:
            raise MarkitdownUnavailableError(
                "markitdown пакет не установлен (uv add markitdown)"
            ) from exc
        try:
            self._md = MarkItDown(enable_plugins=False)
        except Exception as exc:
            raise MarkitdownUnavailableError(f"markitdown init failed: {exc}") from exc
        return self._md

    async def convert(
        self, content: bytes, mime: str, filename: str | None = None
    ) -> tuple[str, list[str]]:
        """Конвертирует bytes в Markdown.

        Args:
            content: Сырое содержимое файла.
            mime: Эффективный MIME-type (после ``sniff_mime``).
            filename: Опциональное оригинальное имя файла (для расширения).

        Returns:
            Кортеж ``(markdown, warnings)``.

        Raises:
            MarkitdownUnavailableError: пакет/инстанс недоступен.
            ValueError: размер превышает ``max_bytes``.
            asyncio.TimeoutError: конвертация дольше ``timeout_s``.
        """
        if len(content) > self._max_bytes:
            raise ValueError(
                f"markitdown: размер {len(content)} > max_bytes={self._max_bytes}"
            )

        md = self._ensure_loaded()
        warnings: list[str] = []

        suffix = _EXT_BY_MIME.get(mime, "")
        if not suffix and filename:
            lower = filename.lower()
            dot = lower.rfind(".")
            if dot != -1:
                suffix = lower[dot:]

        async def _run() -> str:
            return await asyncio.to_thread(self._convert_sync, md, content, suffix)

        try:
            text = await asyncio.wait_for(_run(), timeout=self._timeout_s)
        except TimeoutError:
            warnings.append(f"markitdown timeout after {self._timeout_s}s")
            raise

        return text, warnings

    def _convert_sync(self, md: Any, content: bytes, suffix: str) -> str:
        """Синхронный вызов markitdown.convert на временном файле."""
        with tempfile.TemporaryDirectory(prefix="markitdown_") as tmp:
            tmp_path = Path(tmp) / f"input{suffix or '.bin'}"
            tmp_path.write_bytes(content)
            if self._network_enabled:
                result = md.convert(str(tmp_path))
            else:
                with markitdown_network_disabled():
                    result = md.convert(str(tmp_path))
        # markitdown >=0.1: DocumentConverterResult.text_content;
        # ранее .markdown — поддерживаем оба.
        text = getattr(result, "text_content", None)
        if text is None:
            text = getattr(result, "markdown", "")
        return text or ""
