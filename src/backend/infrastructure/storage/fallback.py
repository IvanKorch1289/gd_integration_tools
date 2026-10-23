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
from typing import Any, Literal

from src.backend.core.errors import ServiceError
from src.backend.core.interfaces.storage import ObjectStorage
from src.backend.core.logging import get_logger
from src.backend.infrastructure.clients.base_connector import HealthResult

__all__ = ("DEFAULT_FALLBACK_EXCEPTIONS", "FallbackObjectStorage", "QuarantineEntry")

_logger = get_logger("storage.fallback")

#: Исключения, означающие **отказ инфраструктуры** primary-backend'а, а не
#: ошибку в коде вызывающего. Значение по умолчанию изменено в cycle 171:
#: прежний ``(Exception,)`` глушил в том числе ``ValueError``/``TypeError``,
#: поэтому баг в вызывающем коде маскировался под «успешную» запись на диск.
#:
#: ``OSError`` покрывает ``ConnectionError``/``TimeoutError``/socket-ошибки
#: (все они — подклассы ``OSError``). ``ServiceError`` — обёртка boto-ошибок,
#: которую возвращает ``S3ObjectStorage``.
DEFAULT_FALLBACK_EXCEPTIONS: tuple[type[BaseException], ...] = (ServiceError, OSError)

#: Операции, меняющие состояние primary-backend'а. Их fallback на secondary
#: означает, что данные оказались на временном носителе и будут потеряны при
#: eviction пода — такие события логируются на уровне ERROR и требуют алертинга.
_WRITE_OPS = frozenset({"upload", "upload_stream", "delete"})


class QuarantineEntry:
    """Объект, записанный в secondary во время отказа primary.

    Хранится в памяти процесса. Нужен для re-upload при восстановлении
    primary: без него данные, ушедшие на pod-local диск, неотличимы от
    обычных локальных файлов.

    Attributes:
        key: Ключ объекта (без tenant-префикса secondary).
        operation: Какая операция деградировала.
        chain: Имя цепочки.
        size: Размер в байтах, если известен (``0`` для stream/delete).
        error: Текст исходной ошибки primary.
    """

    __slots__ = ("chain", "error", "key", "operation", "size")

    def __init__(
        self, *, key: str, operation: str, chain: str, size: int = 0, error: str = ""
    ) -> None:
        self.key = key
        self.operation = operation
        self.chain = chain
        self.size = size
        self.error = error

    def __repr__(self) -> str:
        return (
            f"QuarantineEntry(key={self.key!r}, operation={self.operation!r}, "
            f"chain={self.chain!r}, size={self.size})"
        )


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
            Default — ``DEFAULT_FALLBACK_EXCEPTIONS`` (``ServiceError`` +
            ``OSError``), то есть **только отказ инфраструктуры**. До
            cycle 171 дефолтом был ``(Exception,)``, из-за чего баг
            вызывающего кода (``ValueError``/``TypeError``) маскировался
            под успешную запись в secondary. Расширить дефолт осознанно:
            ``fallback_exceptions=DEFAULT_FALLBACK_EXCEPTIONS + (MyErr,)``.
        quarantine: Регистрировать write-операции, ушедшие в secondary, в
            списке карантина (для последующего re-upload). Default ``True``.
        quarantine_max: Максимум записей карантина; при переполнении
            вытесняется самая старая.
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
        fallback_exceptions: tuple[type[BaseException], ...] = (
            DEFAULT_FALLBACK_EXCEPTIONS
        ),
        name: str = "primary→secondary",
        quarantine: bool = True,
        quarantine_max: int = 10_000,
    ) -> None:
        self._primary = primary
        self._secondary = secondary
        self._fallback_exceptions = fallback_exceptions
        self._name = name
        self._quarantine_enabled = quarantine
        self._quarantine_max = quarantine_max
        self._quarantine: list[QuarantineEntry] = []
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

    @property
    def quarantined(self) -> list[QuarantineEntry]:
        """Объекты, записанные в secondary во время отказа primary.

        Пустой список означает, что primary отвечает штатно. Непустой —
        данные ждут re-upload и могут быть потеряны при eviction пода.
        """
        return list(self._quarantine)

    def drain_quarantine(self) -> list[QuarantineEntry]:
        """Возвращает накопленные записи карантина и очищает список.

        Вызывается re-upload-воркером после успешного восстановления
        primary: он перечитывает secondary и перезаливает в S3.
        """
        entries, self._quarantine = self._quarantine, []
        return entries

    def _should_fallback(self, exc: BaseException) -> bool:
        """True если exc в списке fallback_exceptions."""
        return isinstance(exc, self._fallback_exceptions)

    def _record_fallback(
        self, op: str, exc: BaseException, key: str | None = None, size: int = 0
    ) -> None:
        """Инкрементит счётчик, эмитит метрику и логирует fallback.

        Write-операции логируются на уровне ERROR: данные оказались на
        временном носителе (pod-local диск) и будут потеряны при eviction.
        Read-операции остаются WARNING — это деградация, но не потеря.
        """
        is_write = op in _WRITE_OPS
        self._fallback_count[op] += 1

        if is_write and self._quarantine_enabled:
            if len(self._quarantine) >= self._quarantine_max:
                self._quarantine.pop(0)
            self._quarantine.append(
                QuarantineEntry(
                    key=key or "",
                    operation=op,
                    chain=self._name,
                    size=size,
                    error=str(exc),
                )
            )

        # Local import: observalyzer тянет prometheus_client; не хотим его
        # в import-path самого storage.
        try:
            from src.backend.infrastructure.observability.metrics import (
                record_storage_fallback,
            )

            record_storage_fallback(self._name, op, is_write=is_write)
        except Exception:  # pragma: no cover - метрика не должна ронять I/O
            _logger.debug(
                "storage_fallback.metric_failed chain=%s op=%s",
                self._name,
                op,
                exc_info=True,
            )

        log = _logger.error if is_write else _logger.warning
        log(
            "FallbackObjectStorage[%s] %s primary failed (%s: %s), "
            "falling back to secondary%s",
            self._name,
            op,
            type(exc).__name__,
            str(exc),
            " — ДАННЫЕ ЗАПИСАНЫ НА ВРЕМЕННЫЙ НОСИТЕЛЬ, ТРЕБУЕТСЯ RE-UPLOAD"
            if is_write
            else "",
        )

    async def _with_fallback(
        self,
        op: str,
        primary_call: Any,
        secondary_call: Any,
        *,
        key: str = "",
        size: int = 0,
    ) -> Any:
        """Execute primary_call; при matched exception — secondary_call.

        Инкрементит счётчик, эмитит метрику и логирует (ERROR для write-операций,
        WARNING для read). Не-fallback-исключения пробрасываются без изменений.
        """
        try:
            return await primary_call()
        except BaseException as primary_exc:
            if not self._should_fallback(primary_exc):
                raise
            self._record_fallback(op, primary_exc, key=key, size=size)
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

        return await self._with_fallback(
            "upload", _primary, _secondary, key=key, size=len(data or b"")
        )

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
            self._record_fallback("delete", primary_exc, key=key)
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
            # Дочитываем остаток потока (если primary упала до полного чтения).
            try:
                async for chunk in stream:
                    buffer.extend(chunk)
            except (OSError, ConnectionError, RuntimeError) as stream_exc:
                # cycle-9/D-AUDIT-934: narrow exceptions + observability.
                # OSError/ConnectionError для stream, RuntimeError для
                # backend failure. Bare `except Exception` маскировал
                # unrelated runtime errors (KeyError, TypeError).
                import logging

                logging.getLogger(__name__).debug(
                    "storage_fallback.stream_drain_failed",
                    extra={"key": key, "error": str(stream_exc)},
                )
            payload = bytes(buffer)
            self._record_fallback(
                "upload_stream", primary_exc, key=key, size=len(payload)
            )
            return await self._secondary.upload(key, payload, content_type=content_type)

    def supports_presigned(self) -> bool:
        """True если primary supports presigned (default True)."""
        return self._primary.supports_presigned()

    async def aclose(self) -> None:
        """Закрыть долгоживущие клиенты primary и secondary (cycle 172, HIGH-01).

        Оба бэкенда могут держать пул соединений (S3 — долгоживущий клиент),
        поэтому закрываются оба; ошибка одного не должна мешать закрытию
        другого.
        """
        for backend in (self._primary, self._secondary):
            aclose = getattr(backend, "aclose", None)
            if aclose is None:
                continue
            try:
                await aclose()
            except Exception as exc:  # noqa: BLE001 — shutdown не должен падать
                _logger.warning(
                    "FallbackObjectStorage.aclose failed backend=%s: %s",
                    type(backend).__name__,
                    exc,
                )

    async def health(self, mode: Literal["fast", "deep"] = "fast") -> HealthResult:
        """Health: primary если available, иначе secondary.

        Используется ``ResilienceCoordinator`` (W26) для breaker state.
        """
        import time

        start = time.perf_counter()
        # --- primary ---
        primary_error: str | None = None
        try:
            if hasattr(self._primary, "health"):
                result = await self._primary.health(mode=mode)
                if result.status == "ok":
                    return result
                primary_error = result.error or "primary health not ok"
            else:
                # Legacy backend без health(): probe via exists().
                await self._primary.exists("__healthcheck__")
                latency_ms = (time.perf_counter() - start) * 1000.0
                return HealthResult.ok(latency_ms=latency_ms, mode=mode)
        except BaseException as exc:
            if not self._should_fallback(exc):
                latency_ms = (time.perf_counter() - start) * 1000.0
                return HealthResult.failed(
                    error=f"{type(exc).__name__}: {exc}",
                    mode=mode,
                    latency_ms=latency_ms,
                )
            primary_error = f"{type(exc).__name__}: {exc}"
            _logger.warning(
                "FallbackObjectStorage[%s] health primary failed: %s",
                self._name,
                type(exc).__name__,
            )

        # --- secondary ---
        try:
            if hasattr(self._secondary, "health"):
                result = await self._secondary.health(mode=mode)
                latency_ms = (time.perf_counter() - start) * 1000.0
                if result.status == "ok":
                    return HealthResult.degraded(
                        error=f"primary failed ({primary_error}); secondary ok",
                        mode=mode,
                        latency_ms=latency_ms,
                    )
                return HealthResult.failed(
                    error=f"primary failed ({primary_error}); "
                    f"secondary not ok: {result.error}",
                    mode=mode,
                    latency_ms=latency_ms,
                )
            await self._secondary.exists("__healthcheck__")
            latency_ms = (time.perf_counter() - start) * 1000.0
            return HealthResult.degraded(
                error=f"primary failed ({primary_error}); secondary ok via exists()",
                mode=mode,
                latency_ms=latency_ms,
            )
        except BaseException as exc:
            latency_ms = (time.perf_counter() - start) * 1000.0
            return HealthResult.failed(
                error=f"primary failed ({primary_error}); "
                f"secondary failed: {type(exc).__name__}: {exc}",
                mode=mode,
                latency_ms=latency_ms,
            )
