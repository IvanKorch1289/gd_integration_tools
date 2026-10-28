"""S3/MinIO/AWS реализация :class:`ObjectStorage` (S61 W3 refactor).

Закрывает stub из :mod:`src.backend.infrastructure.storage.factory`,
который при ``provider != "local"`` падал в LocalFS-fallback.

Реализована поверх :mod:`aiobotocore` — асинхронного слоя над botocore.

**Почему не ``aioboto3``** (цикл 172, аудит CRITICAL-06):
весь опубликованный ``aioboto3`` (12.x–15.x) жёстко пинит
``aiobotocore[boto3]==2.x``, а тот — ``botocore<1.40.62``, что несовместимо с
зафиксированным в ``uv.lock`` ``botocore 1.43.75``. ``aiobotocore 3.9.1``
(в ``uv.lock`` уже транзитивно) требует ``botocore<1.43.76,>=1.43.66`` — то есть
совместим, и предоставляет ``get_session().create_client(...)`` — прямой
drop-in для ``aioboto3.Session().client(...)``.

**Долгоживущий клиент** (цикл 172, аудит HIGH-01): раньше клиент создавался и
закрывался на каждую операцию, поэтому ``max_pool_connections`` применялся к
пулу, который умирал сразу, и каждое обращение платило полный TCP+TLS
handshake. Теперь клиент один на инстанс, переиспользуется между операциями и
закрывается явно — через :meth:`S3ObjectStorage.aclose` (вызывается на
shutdown). Транспортный отказ помечает клиент как stale — следующая операция
поднимает новый.

Каждая операция теперь::

    async with self._open() as s3:
        await s3.put_object(...)

Безопасность:
* ``key`` валидируется на path-traversal (mirror LocalFSStorage):
  ``..``, абсолютные пути, пустые строки — ``ValueError``.
* ``key_prefix`` из настроек добавляется автоматически.
* SSL: ``verify`` прокидывается из ``FileStorageSettings``.
* Credentials берутся ТОЛЬКО из настроек (Vault/ENV), не из kwargs.
"""

from __future__ import annotations

import asyncio
from contextlib import AbstractAsyncContextManager
from typing import Any, Literal

from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError

from src.backend.core.config.secret import secret_value
from src.backend.core.config.services.storage import FileStorageSettings
from src.backend.core.errors import ServiceError
from src.backend.core.interfaces.storage import ObjectStorage
from src.backend.core.logging import get_logger
from src.backend.infrastructure.clients.base_connector import HealthResult

__all__ = ("S3ObjectStorage",)


def _import_aiobotocore() -> Any:
    """Lazy-import aiobotocore; raises ImportError с инструкцией по установке.

    Цикл 172 (CRITICAL-06): раньше здесь импортировался ``aioboto3``, который
    не был объявлен ни в ``pyproject.toml``, ни в ``uv.lock``, ни в окружении —
    S3-бэкенд не поднимался вовсе, а его тесты пропускались на 100%.
    ``aiobotocore`` — та же асинхронная обёртка над botocore без конфликта
    версий (см. docstring модуля).
    """
    try:
        from aiobotocore.session import get_session
    except ImportError as exc:
        raise ImportError(
            "S3ObjectStorage requires aiobotocore. Install: uv pip install aiobotocore"
        ) from exc
    return get_session


def _is_transport_error(exc: BaseException | None) -> bool:
    """True, если по цепочке ``__cause__``/``__context__`` найден транспортный сбой.

    Транспортный сбой означает, что TCP/TLS-соединение стало непригодным
    (connection refused, DNS, таймаут) — клиент нужно пересоздать. Ошибки
    уровня ``ClientError`` (404, AccessDenied и т.п.) транспортными не являются:
    пересоздание клиента их не исправит.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (BotoCoreError, OSError, TimeoutError)):
            return True
        current = current.__cause__ or current.__context__
    return False


# ── internal session helper ──────────────────────────────────────────────


class _S3Session(AbstractAsyncContextManager[Any]):
    """Async context manager поверх **долгоживущего** S3-клиента.

    Используется через :meth:`S3ObjectStorage._open`::

        async with storage._open() as s3:
            await s3.put_object(...)

    В отличие от прежней реализации (клиент создавался и закрывался на каждую
    операцию), здесь клиент создаётся один раз и переиспользуется — иначе
    ``max_pool_connections`` не даёт эффекта, а каждое обращение платит полный
    TCP+TLS handshake.

    Закрытие клиента — **не** здесь: клиент живёт вместе с инстансом
    хранилища и закрывается через :meth:`S3ObjectStorage.aclose`.
    """

    def __init__(self, storage: S3ObjectStorage) -> None:
        self._storage = storage

    async def __aenter__(self) -> Any:
        return await self._storage._get_client()

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        # Клиент долгоживущий — закрывать его здесь нельзя. Но если операция
        # упала с транспортным сбросом, клиент помечается stale: следующая
        # операция поднимет новый (старый пул уже мёртв).
        if exc is not None and _is_transport_error(exc):  # type: ignore[arg-type]
            await self._storage._invalidate_client()
        return None


# ── public class ─────────────────────────────────────────────────────────


class S3ObjectStorage(ObjectStorage):
    """S3/MinIO/AWS-совместимая реализация :class:`ObjectStorage`.

    Параметры:
        settings: конфигурация из :class:`FileStorageSettings` (Vault-managed).
        key_prefix: override префикса из настроек (для tenant-изоляции);
            ``None`` → ``settings.key_prefix``.

    Используется как singleton (через :func:`get_object_storage` фабрику).
    Клиент долгоживущий (цикл 172, HIGH-01): создаётся лениво при первой
    операции, переиспользуется между операциями — иначе
    ``max_pool_connections`` не даёт эффекта и каждое обращение платит полный
    TCP+TLS handshake — и закрывается явно через :meth:`aclose` на shutdown.
    """

    def __init__(
        self, settings: FileStorageSettings, *, key_prefix: str | None = None
    ) -> None:
        self._settings = settings
        self._bucket = settings.bucket
        self._prefix = (
            key_prefix if key_prefix is not None else settings.key_prefix
        ).rstrip("/")
        self._session = _import_aiobotocore()()
        self._bucket_ready: bool = False
        self.logger = get_logger(__name__)
        # Долгоживущий клиент (цикл 172, HIGH-01). Создаётся лениво при
        # первой операции и закрывается явно через aclose().
        self._client: Any = None
        self._client_cm: Any = None
        self._client_lock = asyncio.Lock()

    # ── client lifecycle ──────────────────────────────────────────────────

    async def _get_client(self) -> Any:
        """Вернуть долгоживущий S3-клиент, создав его при необходимости.

        Создание защищено ``_client_lock``: конкурентные операции не должны
        создать два клиента (и два пула соединений) параллельно.
        """
        if self._client is not None:
            return self._client
        async with self._client_lock:
            if self._client is not None:
                return self._client
            cm = self._session.create_client(**self._client_kwargs)
            client = await cm.__aenter__()
            try:
                await self._ensure_bucket(client)
            except BaseException:
                await cm.__aexit__(None, None, None)
                raise
            self._client_cm = cm
            self._client = client
            self.logger.debug(
                "S3ObjectStorage: client created bucket=%s pool=%s",
                self._bucket,
                self._settings.max_pool_connections,
            )
            return client

    async def _invalidate_client(self) -> None:
        """Пометить текущий клиент как непригодный и закрыть его.

        Вызывается при транспортном отказе: TCP/TLS-соединение может быть
        разорвано, и следующая операция должна получить свежий клиент с новым
        пулом, а не битый.
        """
        async with self._client_lock:
            cm, self._client_cm = self._client_cm, None
            self._client = None
        if cm is not None:
            try:
                await cm.__aexit__(None, None, None)
            except Exception as exc:  # noqa: BLE001 — закрытие не должно ронять вызывающего
                self.logger.warning("S3ObjectStorage: client close failed: %s", exc)
        self._bucket_ready = False

    async def aclose(self) -> None:
        """Закрыть долгоживущий клиент и освободить пул соединений.

        Вызывается на shutdown приложения. После вызова следующая операция
        lazily поднимет новый клиент.
        """
        await self._invalidate_client()

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
        return {
            "service_name": "s3",
            "endpoint_url": self._settings.endpoint,
            "aws_access_key_id": secret_value(self._settings.access_key),
            "aws_secret_access_key": secret_value(self._settings.secret_key),
            "config": self._boto_config(),
            "use_ssl": self._settings.use_ssl,
            "verify": self._settings.verify,
        }

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
        """Lazy-инициализация bucket (idempotent, один раз на инстанс).

        Cycle 271 (audit MEDIUM-01): ловились только ``ClientError``. Но
        ``_ensure_bucket`` вызывается из ``_S3Session.__aenter__``, то есть
        **вне** try/except каждой операции, поэтому ``BotoCoreError``
        (connection refused, DNS, таймаут) вылетал наружу не обёрнутым и
        ломал документированный контракт «все ошибки → ``ServiceError``».
        Теперь оба типа оборачиваются единообразно.
        """
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
        except BotoCoreError as exc:
            # Сетевой/транспортный отказ — раньше уходил наружу сырым.
            self.logger.error(
                "S3ObjectStorage: head_bucket transport error bucket=%s err=%s",
                self._bucket,
                exc,
            )
            raise ServiceError(f"S3 head_bucket unreachable: {exc}") from exc
        self._bucket_ready = True

    # NOTE (cycle 271, audit MEDIUM-04): прежний ``_wrap_boto`` удалён —
    # вызывающих не было, а тело строилось через ``ServiceError(...).__class__(...)``,
    # что не даёт никакой пользы поверх прямого ``ServiceError(f"...")``.

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
        # Cycle 271 (audit MEDIUM-02): SSE по умолчанию. Раньше настройки
        # не существовало вовсе, и объекты ложились с настройками бакета по
        # умолчанию — то есть шифрование зависело от конфигурации окружения.
        sse = (self._settings.server_side_encryption or "").strip()
        if sse:
            params["ServerSideEncryption"] = sse
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
            # D-AUDIT-#14 fix (S183 W2 #1, 2026-08-05):
            # CancelledError/MemoryError bypass the narrow tuple below and would
            # leak an in-flight multipart upload. Catch them BEFORE the OSError
            # branch (BaseException is parent), attempt abort, then re-raise
            # unchanged so the runtime/loop sees the original cancel signal.
            except asyncio.CancelledError, MemoryError:
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
                raise
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

        Cycle 271 (audit MEDIUM-02): ``expires_in`` теперь ограничен
        ``presign_ttl_max_seconds``. Раньше потолка не существовало, поэтому
        ``expires_in=10**9`` выдавал ссылку, практически неотличимую от
        постоянного доступа. Превышение не отвергается молча — оно логируется
        и обрезается, чтобы вызывающий знал о фактическом TTL.

        Args:
            key: Object key.
            expires_in: Запрошенный TTL в секундах; обрезается до потолка.

        Returns:
            Presigned URL string.

        """
        max_ttl = self._settings.presign_ttl_max_seconds
        if max_ttl > 0 and expires_in > max_ttl:
            self.logger.warning(
                "S3ObjectStorage.presigned_url TTL clamped key=%s requested=%ss "
                "max=%ss",
                key,
                expires_in,
                max_ttl,
            )
            expires_in = max_ttl

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
        # aiobotocore может вернуть корутину или строку в зависимости от версии
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

    async def health(self, mode: Literal["fast", "deep"] = "fast") -> HealthResult:
        """Лёгкая проверка доступности bucket (для /healthz)."""
        import time

        start = time.perf_counter()
        try:
            async with self._open() as s3:
                await s3.head_bucket(Bucket=self._bucket)
            latency_ms = (time.perf_counter() - start) * 1000.0
            return HealthResult.ok(latency_ms=latency_ms, mode=mode)
        except (BotoCoreError, ClientError, OSError) as exc:
            self.logger.warning("S3ObjectStorage.health failed: %s", exc)
            latency_ms = (time.perf_counter() - start) * 1000.0
            return HealthResult.failed(
                error=f"{type(exc).__name__}: {exc}", mode=mode, latency_ms=latency_ms
            )
