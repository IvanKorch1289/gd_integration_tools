"""``FallbackObjectStorage`` — runtime S3→LocalFS (или произвольный chain) fallback.

Закрывает FB-1 gap (S130 W3): ``config_profiles/base.yml`` уже содержит
``resilience.fallbacks.minio: {chain: ["local_fs"]}`` (W26), но runtime
try-primary-then-fallback logic в ``factory.py`` отсутствует — там только
init-time fallback (при отсутствии aioboto3).

Этот wrapper — ``Clean Architecture``-friendly: оборачивает любые два
``ObjectStorage`` backend'а (primary + secondary) и при каждой операции
пробует primary first, при exception — secondary.

Метрики: per-method ``fallback_count`` счётчик для observability.

Пример использования::

    primary = S3ObjectStorage(settings)
    secondary = LocalFSStorage("/var/fallback")
    storage = FallbackObjectStorage(primary, secondary)
    data = await storage.download("path/to/key")

Если primary.download("k") raises (например, network error) —
автоматически вызывается secondary.download("k"). Если secondary
тоже fails — проброс secondary exception (НЕ primary, т.к. primary
failure может быть "временный" — например 5xx от S3, который не
свидетельствует о missing data).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from src.backend.core.interfaces.storage import ObjectStorage
from src.backend.infrastructure.logging.factory import get_logger

__all__ = ("FallbackObjectStorage",)

_logger = get_logger("storage.fallback")


class FallbackObjectStorage(ObjectStorage):
    """Runtime fallback wrapper: primary → secondary при каждой операции.

    При ``presigned_url()``: secondary (LocalFS) отдаёт ``file://`` URL —
    в production это нежелательно. Используйте ``supports_presigned()``
    для проверки primary, или сконфигурируйте secondary как
    read-only-реплику S3 (если есть такая).

    Args:
        primary: Главный backend (обычно S3/MinIO/AWS).
        secondary: Fallback backend (обычно LocalFS или read-only S3).
        fallback_exceptions: Какие exceptions от primary триггерят fallback.
            Default — ``(Exception,)`` (любая ошибка). Для более
            безопасного поведения используйте ``(OSError, IOError,
            ConnectionError)`` чтобы НЕ fallback'ить на логических
            ошибках (например, ``KeyError``).
        name: Имя chain (для логов и метрик). Default — ``"primary→secondary"``.

    Raises:
        ``secondary`` exception если ОБА backend'a fails. ``primary``
            exception теряется (logged as warning). Это даёт более
            релевантный error в observability (текущее состояние
            secondary обычно показательнее).
    """

    def __init__(
        self,
        primary: ObjectStorage,
        secondary: ObjectStorage,
        *,
        fallback_exceptions: tuple[type[BaseException], ...] = (Exception,),
        name: str = "primary→secondary",
    ) -> None:
        self._primary = primary
        self._secondary = secondary
        self._fallback_exceptions = fallback_exceptions
        self._name = name
        # Per-method fallback count для observability
        self._fallback_count: dict[str, int] = {
            "download": 0,
            "upload": 0,
            "upload_stream": 0,
            "delete": 0,
            "exists": 0,
            "list_keys": 0,
            "presigned_url": 0,
        }

    @property
    def fallback_count(self) -> dict[str, int]:
        """Read-only view of per-method fallback counter (для тестов + metrics)."""
        return dict(self._fallback_count)

    def _should_fallback(self, exc: BaseException) -> bool:
        """True если exc в списке fallback_exceptions."""
        return isinstance(exc, self._fallback_exceptions)

    async def _with_fallback(
        self, op: str, primary_call: Any, secondary_call: Any
    ) -> Any:
        """Execute primary_call; при matched exception — secondary_call.

        Логирует warning на fallback, инкрементит счётчик.
        """
        try:
            return await primary_call()
        except BaseException as primary_exc:
            if not self._should_fallback(primary_exc):
                raise
            self._fallback_count[op] += 1
            _logger.warning(
                "FallbackObjectStorage[%s] %s primary failed (%s: %s), "
                "falling back to secondary",
                self._name,
                op,
                type(primary_exc).__name__,
                str(primary_exc),
            )
            return await secondary_call()

    async def download(self, key: str) -> bytes:
        """``download``: primary → secondary fallback."""

        async def _primary() -> bytes:
            return await self._primary.download(key)

        async def _secondary() -> bytes:
            return await self._secondary.download(key)

        return await self._with_fallback("download", _primary, _secondary)

    async def upload(
        self, key: str, data: bytes, content_type: str | None = None
    ) -> str:
        """``upload``: primary → secondary fallback (write-through).

        Returns location URL от успешного backend'а.
        """
        primary_loc: list[str] = []
        secondary_loc: list[str] = []

        async def _primary() -> str:
            loc = await self._primary.upload(key, data, content_type)
            primary_loc.append(loc)
            return loc

        async def _secondary() -> str:
            loc = await self._secondary.upload(key, data, content_type)
            secondary_loc.append(loc)
            return loc

        return await self._with_fallback("upload", _primary, _secondary)

    async def delete(self, key: str) -> None:
        """``delete``: primary → secondary fallback.

        Если primary delete fails, secondary attempts. Если оба fails —
        проброс secondary exception (primary might be optimistic).
        """
        primary_failed = False

        async def _primary() -> None:
            nonlocal primary_failed
            try:
                await self._primary.delete(key)
            except BaseException as exc:
                if not self._should_fallback(exc):
                    raise
                primary_failed = True
                raise

        async def _secondary() -> None:
            await self._secondary.delete(key)

        # Custom logic: even if primary throws, try secondary
        try:
            await _primary()
        except BaseException as primary_exc:
            if not self._should_fallback(primary_exc):
                raise
            self._fallback_count["delete"] += 1
            _logger.warning(
                "FallbackObjectStorage[%s] delete primary failed (%s: %s), "
                "attempting secondary",
                self._name,
                type(primary_exc).__name__,
                str(primary_exc),
            )
            await _secondary()

    async def exists(self, key: str) -> bool:
        """``exists``: primary → secondary fallback."""

        async def _primary() -> bool:
            return await self._primary.exists(key)

        async def _secondary() -> bool:
            return await self._secondary.exists(key)

        return await self._with_fallback("exists", _primary, _secondary)

    async def list_keys(self, prefix: str = "") -> list[str]:
        """``list_keys``: primary → secondary fallback."""

        async def _primary() -> list[str]:
            return await self._primary.list_keys(prefix)

        async def _secondary() -> list[str]:
            return await self._secondary.list_keys(prefix)

        return await self._with_fallback("list_keys", _primary, _secondary)

    async def presigned_url(self, key: str, expires_in: int = 3600) -> str:
        """``presigned_url``: primary → secondary fallback.

        NB: secondary (LocalFS) отдаёт ``file://`` URL. Это нормально
        для dev/staging, но в production primary должен быть доступен
        (S3/MinIO).
        """

        async def _primary() -> str:
            return await self._primary.presigned_url(key, expires_in)

        async def _secondary() -> str:
            return await self._secondary.presigned_url(key, expires_in)

        return await self._with_fallback("presigned_url", _primary, _secondary)

    async def upload_stream(
        self,
        key: str,
        stream: Any,
        content_type: str | None = None,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Streaming upload: primary first; fallback на secondary при ошибке.

        В отличие от обычного ``upload``, fallback для потока требует
        буферизации уже прочитанных чанков. Реализация делегирует primary;
        если primary падает — накапливает остаток потока и пишет во
        secondary через ``upload`` (best-effort fallback).
        """
        buffer = bytearray()

        async def _tee() -> AsyncGenerator[bytes]:
            async for chunk in stream:
                buffer.extend(chunk)
                yield chunk

        try:
            return await self._primary.upload_stream(
                key, _tee(), content_type=content_type, metadata=metadata
            )
        except BaseException as primary_exc:
            if not self._should_fallback(primary_exc):
                raise
            self._fallback_count["upload_stream"] += 1
            _logger.warning(
                "FallbackObjectStorage[%s] upload_stream primary failed (%s: %s), "
                "falling back to secondary upload",
                self._name,
                type(primary_exc).__name__,
                str(primary_exc),
            )
            # Дочитываем остаток потока (если primary упала до полного чтения).
            try:
                async for chunk in stream:
                    buffer.extend(chunk)
            except Exception:
                pass
            return await self._secondary.upload(
                key, bytes(buffer), content_type=content_type
            )

    def supports_presigned(self) -> bool:
        """True если primary supports presigned (default True)."""
        return self._primary.supports_presigned()

    async def healthcheck(self) -> bool:
        """Healthcheck: primary если available, иначе secondary.

        Используется ``ResilienceCoordinator`` (W26) для breaker state.
        """
        try:
            if hasattr(self._primary, "healthcheck"):
                return await self._primary.healthcheck()
            # Fallback: try exists() на well-known key
            return await self._primary.exists("__healthcheck__")
        except BaseException as exc:
            if not self._should_fallback(exc):
                return False
            _logger.warning(
                "FallbackObjectStorage[%s] healthcheck primary failed: %s",
                self._name,
                type(exc).__name__,
            )
            try:
                if hasattr(self._secondary, "healthcheck"):
                    return await self._secondary.healthcheck()
                return await self._secondary.exists("__healthcheck__")
            except BaseException:
                return False
