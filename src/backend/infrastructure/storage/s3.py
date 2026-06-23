"""S3/MinIO/AWS реализация :class:`ObjectStorage` (S61 W3 refactor).

Закрывает stub из :mod:`src.backend.infrastructure.storage.factory`,
который при ``provider != "local"`` падал в LocalFS-fallback.

Реализована поверх :mod:`aioboto3` (high-level async boto3 wrapper).
Каждая операция открывает собственный ``async with session.client(...)`` —
это идиоматический паттерн aioboto3 и одновременно избавляет от
lifecycle-issues (``aclose``, idle connections, retry state).

Для горячих путей ingestion (миллионы объектов в час) — :class:`S3Client`
из ``infrastructure/clients/storage/s3_pool.py`` с aiobotocore long-lived
pool. Здесь (admin/blueprint/extension deployment, DSL processors) —
aioboto3 проще и совместим с moto-mock без отдельного MinIO.

S61 W3 refactor: введён :class:`_S3Session` (proper async context manager)
вместо ручного ``(s3, aexit)`` tuple + per-method ``try/finally``.
Каждая операция теперь::

    async with self._session() as s3:
        await s3.put_object(...)

Безопасность:
* ``key`` валидируется на path-traversal (mirror LocalFSStorage):
  ``..``, абсолютные пути, пустые строки — ``ValueError``.
* ``key_prefix`` из настроек добавляется автоматически.
* SSL: ``verify`` прокидывается из ``FileStorageSettings``.
* Credentials берутся ТОЛЬКО из настроек (Vault/ENV), не из kwargs.
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Any

from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError

from src.backend.core.config.services.storage import FileStorageSettings
from src.backend.core.errors import ServiceError
from src.backend.core.interfaces.storage import ObjectStorage
from src.backend.core.logging import get_logger

__all__ = ("S3ObjectStorage",)


def _import_aioboto3() -> Any:
    """Lazy-import aioboto3; raises ImportError с инструкцией по установке."""
    try:
        import aioboto3
    except ImportError as exc:
        raise ImportError(
            "S3ObjectStorage requires aioboto3. Install: uv pip install aioboto3"
        ) from exc
    return aioboto3


# ── internal session helper ──────────────────────────────────────────────


class _S3Session(AbstractAsyncContextManager[Any]):
    """Async context manager для aioboto3 client + lazy bucket init.

    Используется через :meth:`S3ObjectStorage._session`::

        async with storage._session() as s3:
            await s3.put_object(...)

    На выходе из ``__aexit__`` корректно закрывает underlying client
    (важно для hot-path: idle connection leak prevention).
    """

    def __init__(self, storage: "S3ObjectStorage") -> None:
        self._storage = storage
        self._cm: Any = None
        self._s3: Any = None

    async def __aenter__(self) -> Any:
        self._cm = self._storage._session.client(**self._storage._client_kwargs)
        self._s3 = await self._cm.__aenter__()
        try:
            await self._storage._ensure_bucket(self._s3)
        except BaseException:
            await self._cm.__aexit__(None, None, None)
            self._cm = None
            self._s3 = None
            raise
        return self._s3

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._cm is not None:
            try:
                await self._cm.__aexit__(exc_type, exc, tb)
            finally:
                self._cm = None
                self._s3 = None


# ── public class ─────────────────────────────────────────────────────────


class S3ObjectStorage(ObjectStorage):
    """S3/MinIO/AWS-совместимая реализация :class:`ObjectStorage`.

    Параметры:
        settings: конфигурация из :class:`FileStorageSettings` (Vault-managed).
        key_prefix: override префикса из настроек (для tenant-изоляции);
            ``None`` → ``settings.key_prefix``.

    Используется как singleton (через :func:`get_object_storage` фабрику).
    Соединение устанавливается на каждую операцию (aioboto3 contract);
    для высокочастотных сценариев — ``S3Client`` с persistent pool.
    """

    def __init__(
        self, settings: FileStorageSettings, *, key_prefix: str | None = None
    ) -> None:
        self._settings = settings
        self._bucket = settings.bucket
        self._prefix = (
            key_prefix if key_prefix is not None else settings.key_prefix
        ).rstrip("/")
        self._session = _import_aioboto3().Session()
        self._bucket_ready: bool = False
        self.logger = get_logger(__name__)

    # ── internal helpers ─────────────────────────────────────────────────

    def _boto_config(self) -> BotoConfig:
        return BotoConfig(
            connect_timeout=self._settings.timeout,
            read_timeout=self._settings.read_timeout,
            retries={"max_attempts": self._settings.retries or 3, "mode": "adaptive"},
            max_pool_connections=self._settings.max_pool_connections,
            user_agent_extra="gd-integration-tools/S3ObjectStorage",
        )

    @property
    def _client_kwargs(self) -> dict[str, Any]:
        return dict(
            service_name="s3",
            endpoint_url=self._settings.endpoint,
            aws_access_key_id=self._settings.access_key,
            aws_secret_access_key=self._settings.secret_key,
            config=self._boto_config(),
            use_ssl=self._settings.use_ssl,
            verify=self._settings.verify,
        )

    def _open(self) -> _S3Session:
        """Вернуть async context manager для s3 client (для ``async with``)."""
        return _S3Session(self)

    @staticmethod
    def _is_not_found(exc: ClientError) -> bool:
        """True если ``exc`` указывает на 404 / NoSuchKey / NotFound."""
        code = exc.response.get("Error", {}).get("Code", "")
        return code in ("404", "NoSuchKey", "NotFound")

    def _safe_key(self, key: str) -> str:
        """Валидация + применение prefix; ``..``/absolute/empty → ValueError."""
        if not key:
            raise ValueError("Пустой ключ объекта")
        if key.startswith("/"):
            raise ValueError(f"Абсолютный ключ запрещён: {key!r}")
        if ".." in key.split("/"):
            raise ValueError(f"Path-traversal в ключе: {key!r}")
        # S3 hard limit: 1024 bytes for key; control chars and double-slash are unsafe.
        if len(key.encode("utf-8")) > 1024:
            raise ValueError(f"Ключ превышает 1024 байт: {key!r}")
        if any(ord(ch) < 32 for ch in key):
            raise ValueError(f"Control-символы в ключе запрещены: {key!r}")
        if "//" in key:
            raise ValueError(f"Двойной слэш в ключе запрещён: {key!r}")
        if self._prefix:
            return f"{self._prefix}/{key.lstrip('/')}"
        return key

    def _strip_prefix(self, full_key: str) -> str:
        """Убирает ``_prefix/`` из полного ключа (для list_keys output)."""
        if self._prefix and full_key.startswith(self._prefix + "/"):
            return full_key[len(self._prefix) + 1 :]
        return full_key

    async def _ensure_bucket(self, s3: Any) -> None:
        """Lazy-инициализация bucket (idempotent, один раз на инстанс)."""
        if self._bucket_ready:
            return
        try:
            await s3.head_bucket(Bucket=self._bucket)
        except ClientError as exc:
            if self._is_not_found(exc):
                try:
                    await s3.create_bucket(Bucket=self._bucket)
                except ClientError as create_exc:
                    self.logger.error(
                        "S3ObjectStorage: create_bucket failed bucket=%s err=%s",
                        self._bucket,
                        create_exc,
                    )
                    raise ServiceError(
                        f"S3 create_bucket failed: {create_exc}"
                    ) from create_exc
            else:
                self.logger.error(
                    "S3ObjectStorage: head_bucket failed bucket=%s err=%s",
                    self._bucket,
                    exc,
                )
                raise ServiceError(f"S3 head_bucket failed: {exc}") from exc
        self._bucket_ready = True

    def _wrap_boto(self, op: str, full_key: str) -> "ServiceError":
        """Вернуть ServiceError-обёртку для boto-исключений (helper)."""
        return ServiceError(f"S3 {op} failed: {{}}").__class__(  # type: ignore[arg-type]
            f"S3 {op} failed for key={full_key}"
        )

    # ── ObjectStorage interface ──────────────────────────────────────────

    async def upload(
        self, key: str, data: bytes, content_type: str | None = None
    ) -> str:
        """Upload data to S3.

        Args:
            key: Object key.
            data: Binary data to upload.
            content_type: MIME type.

        Returns:
            S3 object key.
        """
        full_key = self._safe_key(key)
        params: dict[str, Any] = {"Bucket": self._bucket, "Key": full_key, "Body": data}
        if content_type:
            params["ContentType"] = content_type
        async with self._open() as s3:
            try:
                await s3.put_object(**params)
            except (BotoCoreError, ClientError) as exc:
                self.logger.error(
                    "S3ObjectStorage.upload failed key=%s err=%s", full_key, exc
                )
                raise ServiceError(f"S3 upload failed: {exc}") from exc
        return full_key

    async def upload_stream(
        self,
        key: str,
        stream: Any,
        content_type: str | None = None,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Multipart streaming upload из async-итератора чанков (S13 K2 W1).

        Чанки накапливаются до ``part_size`` (минимум 5MB по S3 API),
        затем отправляются как ``upload_part``. При ошибке выполняется
        ``abort_multipart_upload``.
        """
        from collections.abc import AsyncIterable

        full_key = self._safe_key(key)
        part_size = 8 * 1024 * 1024
        upload_id: str | None = None
        parts: list[dict[str, Any]] = []

        async with self._open() as s3:
            try:
                create_kwargs: dict[str, Any] = {
                    "Bucket": self._bucket,
                    "Key": full_key,
                }
                if content_type:
                    create_kwargs["ContentType"] = content_type
                if metadata:
                    create_kwargs["Metadata"] = metadata
                response = await s3.create_multipart_upload(**create_kwargs)
                upload_id = response["UploadId"]

                buffer = bytearray()
                part_number = 1
                if not isinstance(stream, AsyncIterable):
                    raise TypeError(
                        f"S3ObjectStorage.upload_stream expects AsyncIterable[bytes], "
                        f"got {type(stream).__name__}"
                    )
                async for chunk in stream:
                    if not chunk:
                        continue
                    buffer.extend(chunk)
                    while len(buffer) >= part_size:
                        part_bytes = bytes(buffer[:part_size])
                        del buffer[:part_size]
                        part_resp = await s3.upload_part(
                            Bucket=self._bucket,
                            Key=full_key,
                            UploadId=upload_id,
                            PartNumber=part_number,
                            Body=part_bytes,
                        )
                        parts.append(
                            {"PartNumber": part_number, "ETag": part_resp["ETag"]}
                        )
                        part_number += 1

                if buffer:
                    part_resp = await s3.upload_part(
                        Bucket=self._bucket,
                        Key=full_key,
                        UploadId=upload_id,
                        PartNumber=part_number,
                        Body=bytes(buffer),
                    )
                    parts.append({"PartNumber": part_number, "ETag": part_resp["ETag"]})

                if not parts:
                    await s3.abort_multipart_upload(
                        Bucket=self._bucket, Key=full_key, UploadId=upload_id
                    )
                    return full_key

                await s3.complete_multipart_upload(
                    Bucket=self._bucket,
                    Key=full_key,
                    UploadId=upload_id,
                    MultipartUpload={"Parts": parts},
                )
                return full_key
            except (OSError, RuntimeError, KeyError, ValueError) as exc:
                if upload_id is not None:
                    try:
                        await s3.abort_multipart_upload(
                            Bucket=self._bucket, Key=full_key, UploadId=upload_id
                        )
                    except (OSError, RuntimeError, KeyError) as abort_exc:
                        self.logger.exception(
                            "S3ObjectStorage.upload_stream abort failed key=%s: %s",
                            full_key,
                            abort_exc,
                        )
                raise ServiceError(f"S3 upload_stream failed: {exc}") from exc

    async def download(self, key: str) -> bytes:
        """Download data from S3.

        Args:
            key: Object key.

        Returns:
            File contents as bytes.

        Raises:
            FileNotFoundError: If object not found.
        """
        full_key = self._safe_key(key)
        async with self._open() as s3:
            try:
                resp = await s3.get_object(Bucket=self._bucket, Key=full_key)
            except ClientError as exc:
                if self._is_not_found(exc):
                    raise FileNotFoundError(f"Object not found: {key}") from exc
                self.logger.error(
                    "S3ObjectStorage.download failed key=%s err=%s", full_key, exc
                )
                raise ServiceError(f"S3 download failed: {exc}") from exc
            async with resp["Body"] as stream:
                return await stream.read()

    async def delete(self, key: str) -> None:
        """Delete object from S3.

        Args:
            key: Object key.
        """
        full_key = self._safe_key(key)
        async with self._open() as s3:
            try:
                await s3.delete_object(Bucket=self._bucket, Key=full_key)
            except (BotoCoreError, ClientError) as exc:
                self.logger.error(
                    "S3ObjectStorage.delete failed key=%s err=%s", full_key, exc
                )
                raise ServiceError(f"S3 delete failed: {exc}") from exc

    async def exists(self, key: str) -> bool:
        """Check if object exists in S3.

        Args:
            key: Object key.

        Returns:
            True if object exists, False otherwise.
        """
        full_key = self._safe_key(key)
        async with self._open() as s3:
            try:
                await s3.head_object(Bucket=self._bucket, Key=full_key)
                return True
            except ClientError as exc:
                if self._is_not_found(exc):
                    return False
                self.logger.error(
                    "S3ObjectStorage.exists failed key=%s err=%s", full_key, exc
                )
                raise ServiceError(f"S3 head failed: {exc}") from exc

    async def list_keys(self, prefix: str = "") -> list[str]:
        """List all object keys with given prefix.

        Args:
            prefix: Key prefix to filter by.

        Returns:
            Sorted list of matching keys.
        """
        full_prefix = self._safe_key(prefix) if prefix else (self._prefix or "")
        keys: list[str] = []
        async with self._open() as s3:
            try:
                paginator = s3.get_paginator("list_objects_v2")
                async for page in paginator.paginate(
                    Bucket=self._bucket, Prefix=full_prefix
                ):
                    for obj in page.get("Contents", []):
                        keys.append(self._strip_prefix(obj["Key"]))
            except ClientError as exc:
                self.logger.error(
                    "S3ObjectStorage.list_keys failed prefix=%s err=%s",
                    full_prefix,
                    exc,
                )
                raise ServiceError(f"S3 list failed: {exc}") from exc
        return sorted(keys)

    async def presigned_url(self, key: str, expires_in: int = 3600) -> str:
        """Generate presigned URL for S3 object.

        Args:
            key: Object key.
            expires_in: URL expiration time in seconds.

        Returns:
            Presigned URL string.
        """
        full_key = self._safe_key(key)
        async with self._open() as s3:
            try:
                url = await s3.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self._bucket, "Key": full_key},
                    ExpiresIn=expires_in,
                )
            except (BotoCoreError, ClientError) as exc:
                self.logger.error(
                    "S3ObjectStorage.presigned_url failed key=%s err=%s", full_key, exc
                )
                raise ServiceError(f"S3 presign failed: {exc}") from exc
        # aioboto3 может вернуть корутину или строку в зависимости от версии
        if hasattr(url, "__await__"):
            url = await url  # type: ignore[unreachable]
        return str(url)

    def supports_presigned(self) -> bool:
        """Check if backend supports presigned URLs.

        Returns:
            True for S3, False for LocalFS.
        """
        return True

    # ── health probe ─────────────────────────────────────────────────────

    async def healthcheck(self) -> bool:
        """Лёгкая проверка доступности bucket (для /healthz)."""
        try:
            async with self._open() as s3:
                await s3.head_bucket(Bucket=self._bucket)
            return True
        except (BotoCoreError, ClientError, OSError) as exc:
            self.logger.warning("S3ObjectStorage.healthcheck failed: %s", exc)
            return False
