"""S3Sink — выгрузка payload в S3/MinIO (Sprint 3 W1 K3, GAP-03 symmetry).

Закрывает ассиметрию: S3-чтение уже представлено
``S3ReadProcessor`` (через ``storage_client.download_file``), а
исходящий канал поднимается до полноценного Sink-а в линейке
``SinkKind`` (см. остальные 10 Sink-классов).

Реализован поверх ``infrastructure.clients.storage.s3_pool``
(lazy-импорт — общий ``storage_client`` уже представлен в стеке).
Без подключённого S3-клиента ``send`` возвращает
``SinkResult(ok=False, ...)`` — graceful как остальные Sink-классы
(см. :mod:`infrastructure.sinks`).

``payload`` интерпретируется так:

* ``bytes`` — пишется как есть;
* ``str``  — кодируется UTF-8;
* ``dict``/``list`` — сериализуется JSON (orjson, default=str);
* всё остальное — приводится к ``str()`` (для отладочных режимов).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.backend.core.interfaces.sink import Sink, SinkKind, SinkResult

__all__ = ("S3Sink",)


@dataclass(slots=True)
class S3Sink(Sink):
    """Sink для выгрузки payload в S3-bucket по фиксированному key.

    Args:
        sink_id: Уникальный идентификатор.
        bucket: Имя bucket-а (используется только для аудита; реальное
            имя bucket-а определяется конфигурацией ``storage_client``).
        key: S3-key назначения (например, ``"audit/2026/05/event.json"``).
        content_type: HTTP ``Content-Type`` (``application/json`` для
            JSON-нагрузок, ``application/octet-stream`` для бинарных).
    """

    sink_id: str
    bucket: str
    key: str
    content_type: str = "application/octet-stream"
    kind: SinkKind = field(default=SinkKind.S3, init=False)

    async def send(self, payload: Any) -> SinkResult:
        """Сериализует ``payload`` и выгружает в S3 через ``storage_client``."""
        try:
            from src.backend.infrastructure.clients.storage.s3_pool import (
                storage_client,
            )
        except ImportError as exc:
            return SinkResult(
                ok=False,
                details={"error": f"storage_client not available: {exc}"},
            )

        data = _coerce_payload(payload)

        try:
            await storage_client.upload_file(
                data, self.key, content_type=self.content_type
            )
        except Exception as exc:  # noqa: BLE001 — мап в SinkResult.
            return SinkResult(
                ok=False,
                details={"error": str(exc) or exc.__class__.__name__},
            )

        return SinkResult(
            ok=True,
            external_id=self.key,
            details={
                "bucket": self.bucket,
                "key": self.key,
                "bytes": len(data),
                "content_type": self.content_type,
            },
        )

    async def health(self) -> bool:
        """Health: попытка lazy-импорта ``storage_client``.

        Полноценную проверку bucket'а делать дорого (HEAD bucket
        требует прав ``s3:ListBucket``), поэтому ограничиваемся
        проверкой импорта клиента — как в большинстве Sink-классов.
        """
        try:
            from src.backend.infrastructure.clients.storage.s3_pool import (  # noqa: F401
                storage_client,
            )
        except ImportError:
            return False
        return True


def _coerce_payload(payload: Any) -> bytes:
    """Приводит ``payload`` к ``bytes`` для ``storage_client.upload_file``.

    Bytes → как есть; str → UTF-8; dict/list → JSON через orjson;
    всё остальное → ``str(payload)`` в UTF-8.
    """
    if isinstance(payload, (bytes, bytearray)):
        return bytes(payload)
    if isinstance(payload, str):
        return payload.encode("utf-8")
    try:
        import orjson

        return orjson.dumps(payload, default=str)
    except ImportError:
        import json

        return json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
