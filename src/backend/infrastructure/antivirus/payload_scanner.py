"""ClamAV PayloadScanner для WAF (Sprint 16 Wave 6, B-3 finale).

Async-обёртка вокруг :class:`AntivirusBackend` (clamd unix/TCP), которая
соответствует :data:`src.backend.core.net.waf.AsyncPayloadScanner`
сигнатуре ``(bytes | None) -> Awaitable[str | None]``.

Поведение
~~~~~~~~~

* ``payload is None`` → ``None`` (нечего сканировать).
* Backend возвращает ``clean=True`` → ``None``.
* Backend возвращает ``clean=False`` → строка с именем сигнатуры
  (``"ClamAV signature: <name>"``) — далее WAF блокирует запрос с этой
  причиной.
* Backend бросает :class:`ConnectionError` или таймаут:
  - при ``fail_open=True`` (default) — лог WARNING + ``None`` (запрос
    проходит без сканирования; используется в dev/staging);
  - при ``fail_open=False`` — строка ``"clamav unavailable"`` — WAF
    блокирует запрос (рекомендуется в production-strict).

Wire в production
~~~~~~~~~~~~~~~~~

Не подключается автоматически. lifespan startup (опц. шаг) поднимает
:class:`ClamAVTcpBackend` / :class:`ClamAVUnixBackend` по env-конфигу
и устанавливает ``WafPolicy.async_payload_scanner`` в singleton
:class:`ClamAVPayloadScanner`. См. ADR-0053.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.backend.core.logging import get_logger
if TYPE_CHECKING:
    from src.backend.core.interfaces.antivirus import AntivirusBackend

__all__ = ("ClamAVPayloadScanner",)

_logger = get_logger("infrastructure.antivirus.payload_scanner")


class ClamAVPayloadScanner:
    """Async-обёртка ``AntivirusBackend`` для :class:`WafPolicy`.

    Args:
        backend: ClamAV backend (TCP / Unix socket).
        fail_open: При ``True`` (default) ошибка backend'а трактуется как
            ``clean`` (запрос проходит). При ``False`` — backend
            unavailable блокирует запрос с причиной ``"clamav unavailable"``.

    Использование::

        from src.backend.infrastructure.antivirus.backends.clamav_tcp import (
            ClamAVTcpBackend,
        )
        from src.backend.infrastructure.antivirus.payload_scanner import (
            ClamAVPayloadScanner,
        )
        from src.backend.core.net.waf import WafPolicy

        scanner = ClamAVPayloadScanner(ClamAVTcpBackend())
        policy = WafPolicy(strict=True, async_payload_scanner=scanner)
    """

    __slots__ = ("_backend", "_fail_open")

    def __init__(self, backend: AntivirusBackend, *, fail_open: bool = True) -> None:
        self._backend = backend
        self._fail_open = fail_open

    async def __call__(self, payload: bytes | None) -> str | None:
        """Реализует сигнатуру :data:`AsyncPayloadScanner`.

        Returns:
            ``None`` если payload чист (или не задан); иначе строка-причина.
        """
        if payload is None or len(payload) == 0:
            return None

        try:
            result = await self._backend.scan_bytes(payload)
        except ConnectionError as exc:
            _logger.warning(
                "clamav.scan.unavailable",
                extra={"backend": self._backend.name, "error": repr(exc)},
            )
            if self._fail_open:
                return None
            return "clamav unavailable"
        except Exception as exc:
            _logger.error(
                "clamav.scan.error",
                extra={"backend": self._backend.name, "error": repr(exc)},
            )
            if self._fail_open:
                return None
            return f"clamav error: {type(exc).__name__}"

        if result.clean:
            return None
        return f"ClamAV signature: {result.signature or 'unknown'}"
