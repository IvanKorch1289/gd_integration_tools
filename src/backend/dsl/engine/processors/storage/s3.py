"""S3 DSL-процессоры (S61 W3).

Закрывает gap "storage operations в routes" — пользовательский DSL-flow
может выгружать/загружать/перечислять S3-объекты без Python-кода::

    - to_s3:
        data_property: payload
        key_from: properties.target_key
        content_type_from: properties.mime
        result_property: s3_key
    - from_s3:
        key_from: properties.s3_key
        result_property: payload_bytes
    - s3_presign:
        key_from: properties.s3_key
        expires_in: 900
        result_property: download_url
    - s3_delete:
        key_from: properties.s3_key
    - s3_list:
        prefix_from: properties.prefix
        result_property: keys

Безопасно: key validation через :meth:`S3ObjectStorage._safe_key`
(path-traversal/absolute/empty → ``ValueError`` → ``exchange.fail``).

Использует :func:`get_object_storage` из
:mod:`src.backend.infrastructure.storage.factory` — provider=local
даёт LocalFSStorage (без network), provider=s3/minio/aws даёт
S3ObjectStorage поверх aioboto3.
"""

from __future__ import annotations

from typing import Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.engine.processors.entity import _resolve
from src.backend.dsl.registry.processor import processor

__all__ = (
    "FromS3Processor",
    "S3DeleteProcessor",
    "S3ListProcessor",
    "S3PresignProcessor",
    "ToS3Processor",
)

_logger = get_logger("dsl.storage.s3")


def _get_storage() -> Any:
    """Lazy import storage factory (чтобы избежать cycle на startup)."""
    from src.backend.infrastructure.storage import factory

    return factory.get_object_storage()


# ── to_s3 ─────────────────────────────────────────────────────────────────


@processor("to_s3", namespace="core", capabilities=("storage.write",))
class ToS3Processor(BaseProcessor):
    """Загружает байты из exchange-property в S3/MinIO/LocalFS.

    Args:
        data_property: имя property с ``bytes``/``str`` (default ``"body"``).
        key_from: выражение для целевого S3-ключа (default ``"data"``).
        content_type_from: выражение для ContentType (опционально).
        result_property: имя property для записи фактического ключа
            (с применённым prefix, default ``"s3_key"``).
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.SIDE_EFFECTING
    compensatable: ClassVar[bool] = False  # upload необратим без S3.Delete

    def __init__(
        self,
        *,
        data_property: str = "body",
        key_from: str = "data",
        content_type_from: str | None = None,
        result_property: str = "s3_key",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "to_s3")
        self._data_property = data_property
        self._key_from = key_from
        self._content_type_from = content_type_from
        self._result_property = result_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        data = _resolve(exchange, self._data_property)
        key = _resolve(exchange, self._key_from)
        content_type = (
            _resolve(exchange, self._content_type_from)
            if self._content_type_from
            else None
        )
        if not isinstance(key, str):
            exchange.fail(f"to_s3: key must be str, got {type(key).__name__}")
            return
        if isinstance(data, str):
            data = data.encode("utf-8")
        if not isinstance(data, (bytes, bytearray)):
            exchange.fail(f"to_s3: data must be bytes/str, got {type(data).__name__}")
            return
        try:
            storage = _get_storage()
            full_key = await storage.upload(key, bytes(data), content_type=content_type)
        except (ValueError, OSError) as exc:
            exchange.fail(f"to_s3: {exc}")
            return
        except Exception as exc:  # noqa: BLE001
            _logger.error("to_s3 failed key=%s err=%s", key, exc)
            exchange.fail(f"to_s3: {type(exc).__name__}: {exc}")
            return
        exchange.properties[self._result_property] = full_key

    def to_spec(self) -> dict[str, Any]:
        spec: dict[str, Any] = {
            "data_property": self._data_property,
            "key_from": self._key_from,
            "result_property": self._result_property,
        }
        if self._content_type_from is not None:
            spec["content_type_from"] = self._content_type_from
        return {"to_s3": spec}


# ── from_s3 ───────────────────────────────────────────────────────────────


@processor("from_s3", namespace="core", capabilities=("storage.read",))
class FromS3Processor(BaseProcessor):
    """Скачивает байты из S3/MinIO/LocalFS в exchange-property.

    Args:
        key_from: выражение для S3-ключа (default ``"s3_key"``).
        result_property: имя property для записи ``bytes`` (default ``"body"``).
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.STATEFUL

    def __init__(
        self,
        *,
        key_from: str = "s3_key",
        result_property: str = "body",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "from_s3")
        self._key_from = key_from
        self._result_property = result_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        key = _resolve(exchange, self._key_from)
        if not isinstance(key, str):
            exchange.fail(f"from_s3: key must be str, got {type(key).__name__}")
            return
        try:
            storage = _get_storage()
            data = await storage.download(key)
        except FileNotFoundError as exc:
            exchange.fail(f"from_s3: {exc}")
            return
        except (ValueError, OSError) as exc:
            exchange.fail(f"from_s3: {exc}")
            return
        except Exception as exc:  # noqa: BLE001
            _logger.error("from_s3 failed key=%s err=%s", key, exc)
            exchange.fail(f"from_s3: {type(exc).__name__}: {exc}")
            return
        exchange.properties[self._result_property] = data

    def to_spec(self) -> dict[str, Any]:
        return {
            "from_s3": {
                "key_from": self._key_from,
                "result_property": self._result_property,
            }
        }


# ── s3_presign ────────────────────────────────────────────────────────────


@processor("s3_presign", namespace="core", capabilities=("storage.read",))
class S3PresignProcessor(BaseProcessor):
    """Генерирует presigned URL для S3/MinIO (LocalFS возвращает ``file://``).

    Args:
        key_from: выражение для S3-ключа (default ``"s3_key"``).
        expires_in: TTL URL в секундах (default 3600).
        result_property: имя property для записи URL (default ``"download_url"``).
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(
        self,
        *,
        key_from: str = "s3_key",
        expires_in: int = 3600,
        result_property: str = "download_url",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "s3_presign")
        if expires_in <= 0:
            raise ValueError(
                f"s3_presign: expires_in должен быть > 0, получено {expires_in}"
            )
        self._key_from = key_from
        self._expires_in = expires_in
        self._result_property = result_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        key = _resolve(exchange, self._key_from)
        if not isinstance(key, str):
            exchange.fail(f"s3_presign: key must be str, got {type(key).__name__}")
            return
        try:
            storage = _get_storage()
            if not storage.supports_presigned():
                exchange.fail("s3_presign: backend не поддерживает presigned URLs")
                return
            url = await storage.presigned_url(key, expires_in=self._expires_in)
        except (ValueError, OSError) as exc:
            exchange.fail(f"s3_presign: {exc}")
            return
        except Exception as exc:  # noqa: BLE001
            _logger.error("s3_presign failed key=%s err=%s", key, exc)
            exchange.fail(f"s3_presign: {type(exc).__name__}: {exc}")
            return
        exchange.properties[self._result_property] = url

    def to_spec(self) -> dict[str, Any]:
        return {
            "s3_presign": {
                "key_from": self._key_from,
                "expires_in": self._expires_in,
                "result_property": self._result_property,
            }
        }


# ── s3_delete ─────────────────────────────────────────────────────────────


@processor("s3_delete", namespace="core", capabilities=("storage.write",))
class S3DeleteProcessor(BaseProcessor):
    """Удаляет объект из S3/MinIO/LocalFS (idempotent: missing → no-op).

    Args:
        key_from: выражение для S3-ключа (default ``"s3_key"``).
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.SIDE_EFFECTING
    compensatable: ClassVar[bool] = False  # delete нельзя «откатить»

    def __init__(self, *, key_from: str = "s3_key", name: str | None = None) -> None:
        super().__init__(name=name or "s3_delete")
        self._key_from = key_from

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        key = _resolve(exchange, self._key_from)
        if not isinstance(key, str):
            exchange.fail(f"s3_delete: key must be str, got {type(key).__name__}")
            return
        try:
            storage = _get_storage()
            await storage.delete(key)
        except (ValueError, OSError) as exc:
            exchange.fail(f"s3_delete: {exc}")
            return
        except Exception as exc:  # noqa: BLE001
            _logger.error("s3_delete failed key=%s err=%s", key, exc)
            exchange.fail(f"s3_delete: {type(exc).__name__}: {exc}")
            return

    def to_spec(self) -> dict[str, Any]:
        return {"s3_delete": {"key_from": self._key_from}}


# ── s3_list ───────────────────────────────────────────────────────────────


@processor("s3_list", namespace="core", capabilities=("storage.read",))
class S3ListProcessor(BaseProcessor):
    """Возвращает список ключей в S3/MinIO/LocalFS bucket (с пагинацией).

    Args:
        prefix_from: выражение для префикса (опционально).
        result_property: имя property для записи ``list[str]``
            (default ``"s3_keys"``).
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.STATEFUL

    def __init__(
        self,
        *,
        prefix_from: str | None = None,
        result_property: str = "s3_keys",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "s3_list")
        self._prefix_from = prefix_from
        self._result_property = result_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        prefix: str = ""
        if self._prefix_from is not None:
            resolved = _resolve(exchange, self._prefix_from)
            if resolved is not None and not isinstance(resolved, str):
                exchange.fail(
                    f"s3_list: prefix must be str, got {type(resolved).__name__}"
                )
                return
            prefix = resolved or ""
        try:
            storage = _get_storage()
            keys = await storage.list_keys(prefix)
        except (ValueError, OSError) as exc:
            exchange.fail(f"s3_list: {exc}")
            return
        except Exception as exc:  # noqa: BLE001
            _logger.error("s3_list failed prefix=%s err=%s", prefix, exc)
            exchange.fail(f"s3_list: {type(exc).__name__}: {exc}")
            return
        exchange.properties[self._result_property] = keys

    def to_spec(self) -> dict[str, Any]:
        spec: dict[str, Any] = {"result_property": self._result_property}
        if self._prefix_from is not None:
            spec["prefix_from"] = self._prefix_from
        return {"s3_list": spec}
