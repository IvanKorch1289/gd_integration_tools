"""PII-зона SecurityFacade (S3 сплит, из facade.py).

S3 (ledger, 2026-09-05): выделение зон ответственности из
``services/security/facade.py`` (453 LOC / 22 методов) по паттерну
закрытых M2-сплитов. Mixin использует ``self._assert`` ядра facade.
"""

from __future__ import annotations

from src.backend.core.logging import get_logger

_logger = get_logger("services.security.facade")


def _emit_pii_fail_audit(operation: str, exc: BaseException) -> None:
    """Helper: emit audit-event для fail-open PII operations (W9).

    S48 W9 swarm audit (A3 Services #5): tokenize_pii/mask_pii раньше возвращали
    raw text при exception без observability. Caller получал unmasked PII
    без следа в audit. Теперь audit-event с severity=error + failed_operation.
    Lazy import (избегаем circular с core.audit).
    """
    try:
        from src.backend.core.audit.facade._base import emit_audit_safe

        emit_audit_safe(
            event="security.pii.fail_open",
            action=operation,
            outcome="failure",
            severity="error",
            extra={
                "failed_operation": operation,
                "error_type": type(exc).__name__,
                "error_message": str(exc)[:200],
                "warning": (
                    f"{operation} returned raw text — PII NOT masked. "
                    "Caller should treat as unsafe."
                ),
            },
        )
    except Exception as audit_exc:
        _logger.warning(
            "Failed to emit pii.fail_open audit for %s: %s", operation, audit_exc,
        )


class PiiFacadeMixin:
    """PII-операции facade (tokenize/detokenize/mask)."""

    async def tokenize_pii(self, text: str) -> str:
        """Reversible PII tokenization (PIITokenizer).

        Args:
            text: Текст с PII (ФИО, email, телефон, etc.).

        Returns:
            Токенизированный текст с placeholders ``<PII_TYPE_xxx>``.

        """
        self._assert("security.pii.tokenize", "text")  # type: ignore[attr-defined]
        try:
            from src.backend.core.security.pii_tokenizer import PIIPolicy, PIITokenizer

            tokenizer = PIITokenizer()
            policy = PIIPolicy(name="ru_strict_reversible")
            masked_text, _token_map = await tokenizer.mask_reversible(text, policy)
            return masked_text
        except Exception as exc:
            _logger.warning("tokenize_pii failed: %s", exc)
            # S48 W9 swarm audit (A3 Services #5): fail-open — caller получает
            # raw text без маскирования при ошибке tokenizer. PII leak risk.
            # Теперь emit audit-warning с severity=error.
            _emit_pii_fail_audit("tokenize_pii", exc)
            return text

    async def detokenize_pii(self, text: str) -> str:
        """Reversible PII detokenization.

        Note: detokenization requires the original TokenMap. This method
        returns the text as-is if no token map is available (caller must
        pass it through PIITokenizer.unmask directly).
        """
        self._assert("security.pii.detokenize", "text")  # type: ignore[attr-defined]
        _logger.debug(
            "detokenize_pii: use PIITokenizer.unmask(masked_text, token_map) directly"
        )
        return text

    async def mask_pii(self, text: str) -> str:
        """One-way PII masking (irreversible).

        Args:
            text: Текст с PII.

        Returns:
            Masked text: ``"Иван И.О."``, ``"i.***@example.com"``, etc.

        """
        self._assert("security.pii.mask", "text")  # type: ignore[attr-defined]
        try:
            from src.backend.core.security.pii_masker import PIIMasker

            masker = PIIMasker()
            return masker.mask_text(text)
        except Exception as exc:
            _logger.warning("mask_pii failed: %s", exc)
            # S48 W9 swarm audit (A3 Services #5): fail-open — caller получает
            # raw text. Audit-event (consistent с tokenize_pii fix).
            _emit_pii_fail_audit("mask_pii", exc)
            return text
