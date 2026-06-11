from __future__ import annotations

from src.backend.core.errors import BaseError


def _safe_error(exc: Exception, correlation_id: str) -> str:
    """Формирует безопасное сообщение об ошибке для gRPC client (IL-CRIT1.2).

    Политика:
      * ``BaseError`` (наши domain errors) — выдаём ``exc.message`` как есть:
        это типизированные, контролируемые сообщения без sensitive data.
      * Любые другие Exception — generic "Internal server error" +
        correlation_id для корреляции с server-side logs.

    Никогда не отправляем клиенту ``str(exc)`` / traceback / module-path —
    это leak информации о внутренней реализации (кроме контролируемых
    BaseError сообщений).
    """
    if isinstance(exc, BaseError):
        return exc.message
    return f"Internal server error; ref={correlation_id}"
