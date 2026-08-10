"""PII fail-CLOSED contract (cycle-4/D-AUDIT-109).

Централизованный fail-CLOSED contract для PII processing.
Ранее (cycle 1+2+3) ``services.pii.facade.PIIFacade.mask/tokenize`` и
``services.ai.rag_ingest_service._maybe_mask_pii`` при sanitizer exception
возвращали raw PII обратно caller'у — fail-OPEN, что приводило к PII-leak
в vector store / логи / downstream.

Контракт: при любой sanitizer failure — emit audit event + raise
:class:`PIIFailClosedError`. Caller НЕ ДОЛЖЕН пробрасывать raw PII
downstream. Catching не разрешён кроме explicit quarantine path
(например, ``RagIngestService._run`` ловит и добавляет в errors list
вместо ``rag.ingest``).

DSL/extensions: при вызове ``pii.mask`` через Action, обработка
должна быть обёрнута в try/except с конкретным handling
(quarantine index, drop, user-error 4xx).
"""

from __future__ import annotations

from typing import NoReturn

from src.backend.core.logging import get_logger

__all__ = ("PIIFailClosedError", "raise_pii_fail_closed")

_logger = get_logger("core.policy.pii_fail_closed")


class PIIFailClosedError(RuntimeError):
    """Raised when PII processing fails — caller MUST NOT receive raw PII.

    Поднимается из :func:`raise_pii_fail_closed`. ``__cause__`` содержит
    оригинальное исключение от sanitizer'а (через ``raise ... from exc``).
    """


def raise_pii_fail_closed(
    *, source: str, payload_size: int, exc: BaseException
) -> NoReturn:
    """cycle-4/D-AUDIT-109 — concrete handling для PII sanitizer failure.

    Паттерн: ``logger.error`` + ``log_audit_event_lite(event="pii.sanitizer_failure")``
    + raise :class:`PIIFailClosedError`. Используется в ``except`` блоках
    ``services.pii.facade.PIIFacade.mask/tokenize`` и
    ``services.ai.rag_ingest_service._maybe_mask_pii``.

    Args:
        source: Identifier точки failure (например ``"pii.facade.mask"``).
        payload_size: Size of original payload (для audit metadata).
        exc: Original exception от sanitizer'а.

    Raises:
        PIIFailClosedError: Всегда — caller видит fail-CLOSED contract.
    """
    # cycle-4/D-AUDIT-109 — fail-CLOSED: logger.error (НЕ warning) +
    # audit event. Никакого silent return raw PII.
    _logger.error(
        "PII sanitizer failure: source=%s payload_size=%d err=%s",
        source,
        payload_size,
        exc,
    )
    try:
        from src.backend.core.observability.logging_helpers import log_audit_event_lite

        log_audit_event_lite(
            _logger,
            severity="error",
            event="pii.sanitizer_failure",
            source=source,
            payload_size=payload_size,
            error_class=type(exc).__name__,
        )
    except Exception as audit_exc:  # pragma: no cover — audit is best-effort
        _logger.warning("pii fail-closed audit emit failed: %s", audit_exc)
    raise PIIFailClosedError(source) from exc
