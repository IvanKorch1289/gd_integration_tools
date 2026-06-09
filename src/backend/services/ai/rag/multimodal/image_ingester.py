"""ImageIngester — pipeline для отдельных изображений.

Использует Pillow (lazy-import) для извлечения EXIF, формата, размера.
Возвращает ``ChunkDoc(kind="image", content=bytes)`` с метаданными.

Опционально: VLM-провайдер для генерации caption (заглушка-крючок).
"""

from __future__ import annotations

import asyncio
import hashlib
import io
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.backend.core.logging import get_logger
from src.backend.services.ai.rag.multimodal.types import ChunkDoc

logger = get_logger(__name__)

__all__ = ("ImageIngester",)

# Поддерживаемые форматы для sniff'а MIME из Pillow Image.format.
_PIL_FORMAT_TO_MIME: dict[str, str] = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "WEBP": "image/webp",
    "GIF": "image/gif",
    "BMP": "image/bmp",
    "TIFF": "image/tiff",
}


class ImageIngester:
    """Pipeline ingestion одиночного изображения.

    Извлекает:
        * формат и MIME через Pillow;
        * размеры (width, height);
        * EXIF (опционально, если присутствует);
        * sha256 контента (для deduplication).

    Возвращает один ChunkDoc(kind="image"). Caption через VLM-провайдер
    может быть добавлен через метод ``set_caption_provider``.

    Attributes:
        extract_exif: Если True — добавляет в metadata exif-словарь.
        caption_provider: Опциональный async-callable ``(bytes) -> str`` для
            генерации caption (VLM/Vision LLM). Если задан — caption пишется
            в metadata["caption"].
    """

    def __init__(
        self, *, extract_exif: bool = True, caption_provider: Any | None = None
    ) -> None:
        """Инициализирует ImageIngester.

        Args:
            extract_exif: Извлекать EXIF-метаданные.
            caption_provider: Async-вызываемый объект для VLM caption
                (опционально).
        """
        self.extract_exif = extract_exif
        self.caption_provider = caption_provider

    async def ingest(self, source: Path | bytes) -> ChunkDoc:
        """Возвращает ChunkDoc для изображения.

        Args:
            source: Путь к файлу или bytes.

        Returns:
            ChunkDoc(kind="image") с заполненными metadata.
        """
        if isinstance(source, Path):
            content = await asyncio.to_thread(source.read_bytes)
            source_path = str(source)
        else:
            content = source
            source_path = "<bytes>"

        meta: dict[str, Any] = {
            "source_path": source_path,
            "size_bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest()[:16],
        }

        try:
            pil_meta = await asyncio.to_thread(self._extract_pil_meta, content)
            meta.update(pil_meta)
        except ImportError:
            logger.warning("ImageIngester: Pillow не установлен — метаданные пропущены")
            meta["warnings"] = ["pillow_not_installed"]
        except Exception as exc:
            logger.warning("ImageIngester: ошибка чтения metadata: %s", exc)
            meta["warnings"] = [f"pil_failed: {exc}"]

        if self.caption_provider is not None:
            try:
                caption = await self.caption_provider(content)
                meta["caption"] = caption
            except Exception as exc:
                logger.warning("ImageIngester: caption provider упал: %s", exc)
                meta.setdefault("warnings", []).append(f"caption_failed: {exc}")

        return ChunkDoc(
            chunk_id=uuid4().hex,
            kind="image",
            content=content,
            metadata=meta,
            embedding_kind="clip",
        )

    def _extract_pil_meta(self, content: bytes) -> dict[str, Any]:
        """Sync-извлечение метаданных через Pillow.

        Args:
            content: Bytes изображения.

        Returns:
            ``{format, mime, width, height, mode, exif?}``.
        """
        from PIL import Image  # lazy-import (Pillow в base deps)

        meta: dict[str, Any] = {}
        with Image.open(io.BytesIO(content)) as img:
            meta["format"] = img.format
            meta["mime"] = _PIL_FORMAT_TO_MIME.get(
                img.format or "", "application/octet-stream"
            )
            meta["width"] = img.width
            meta["height"] = img.height
            meta["mode"] = img.mode

            if self.extract_exif:
                try:
                    exif = img.getexif()
                    if exif:
                        # Сохраняем только tag→str-значения для сериализуемости.
                        meta["exif"] = {
                            str(tag): str(val)
                            for tag, val in exif.items()
                            if val is not None
                        }
                except Exception as exc:
                    logger.debug("ImageIngester: EXIF недоступен: %s", exc)

        return meta
