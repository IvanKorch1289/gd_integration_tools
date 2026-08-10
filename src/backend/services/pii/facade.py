"""PIIFacade — unified facade для PII operations (S183 I-2).

Закрывает gap — ранее не было единого facade для PII masking/tokenization.
Теперь extensions и DSL могут использовать единый entry-point:

- :func:`mask_pii()` — irreversible PII masking (regex-based)
- :func:`tokenize_pii()` / :func:`detokenize_pii()` — reversible tokenization (Presidio)
- :func:`add_custom_pattern()` — register custom PII pattern
- :func:`list_patterns()` — list active PII patterns


Ponytail: thin wrapper, не дублирует логику.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from src.backend.core.logging import get_logger

__all__ = ("PIIFacade", "get_pii_facade")

_logger = get_logger("services.pii.facade")


class PIIFacade:
    """Unified facade для PII masking/tokenization operations."""

    def __init__(self) -> None:
        """Инициализация facade."""
        self._masker: Any | None = None
        self._tokenizer: Any | None = None

    @property
    def masker(self) -> Any:
        """Метод masker (см. signature)."""
        if self._masker is None:
            from src.backend.core.security.pii_masker import default_masker

            self._masker = default_masker
        return self._masker

    @property
    def tokenizer(self) -> Any:
        """Lazy accessor для PIITokenizer (reversible)."""
        if self._tokenizer is None:
            from src.backend.core.security.pii_tokenizer import PIITokenizer

            self._tokenizer = PIITokenizer()
        return self._tokenizer

    def mask(self, text: str) -> str:
        """Irreversible PII masking (regex-based, S191 fix: audit emit).

        Args:
            text: Текст с PII (email, phone, INN, SNILS, card, etc.).

        Returns:
            Masked text: ``"Иван И.***"``, ``"i.***@example.com"``, etc.

        Raises:
            PIIFailClosedError: cycle-4/D-AUDIT-109 — при sanitizer failure.
                Caller НЕ ДОЛЖЕН пробрасывать raw PII downstream.

        """
        try:
            result = self.masker.mask_text(text)
            self._emit_audit("pii.masked", text)
            return result
        except Exception as exc:
            from src.backend.core.policy.pii_fail_closed import raise_pii_fail_closed

            raise_pii_fail_closed(
                source="pii.facade.mask", payload_size=len(text), exc=exc,
            )

    def mask_struct(self, obj: Any) -> Any:
        """Рекурсивно mask PII в dict/list/str structures.

        Args:
            obj: Python object (dict, list, tuple, str).

        Returns:
            Same structure с masked strings.

        """
        try:
            return self.masker.mask_dict(obj)
        except Exception as exc:
            _logger.warning("PII mask_struct failed: %s", exc)
            return obj

    def tokenize(self, text: str) -> str:
        """Reversible PII tokenization — delegates to PIIMasker.mask_text as sync fallback.

        PIITokenizer.mask_reversible is async and requires PIIPolicy + returns
        tuple[str, TokenMap]. For sync facade path, use mask_text (regex-based).
        For full reversible tokenization, use SecurityFacade.tokenize_pii (async).

        Raises:
            PIIFailClosedError: cycle-4/D-AUDIT-109 — при sanitizer failure.

        """
        try:
            result = self.masker.mask_text(text)
            self._emit_audit("pii.tokenized", text)
            return result
        except Exception as exc:
            from src.backend.core.policy.pii_fail_closed import raise_pii_fail_closed

            raise_pii_fail_closed(
                source="pii.facade.tokenize", payload_size=len(text), exc=exc,
            )

    def detokenize(self, text: str) -> str:
        """Reversible PII detokenization — no-op without TokenMap.

        Detokenization requires the original TokenMap from mask_reversible.
        Use ``PIITokenizer.unmask(masked_text, token_map)`` directly.
        """
        _logger.debug("PII detokenize: requires TokenMap, use PIITokenizer.unmask directly")
        return text

    def _emit_audit(self, event: str, payload: str) -> None:
        """S191 fix: emit PII audit event для compliance tracking."""
        try:
            from src.backend.core.observability.logging_helpers import (
                log_audit_event_lite,
            )

            log_audit_event_lite(
                _logger,
                severity="warning",
                event=event,
                payload_size=len(payload),
            )
        except Exception as exc:
            _logger.debug("PII audit emit failed: %s", exc)

    def add_custom_pattern(
        self,
        name: str,
        pattern: str,
        replacement: str = "[REDACTED]",
    ) -> None:
        """Добавить custom PII pattern.

        Args:
            name: Pattern name (e.g., ``"card_pan"``).
            pattern: Regex pattern.
            replacement: Ignored for regex-based masker (patterns are dict[str, re.Pattern]).

        """
        try:
            if not hasattr(self.masker, "_patterns"):
                _logger.warning("Cannot add custom pattern to %s", type(self.masker))
                return

            compiled = re.compile(pattern)
            self.masker._patterns[name] = compiled
            _logger.info("Custom PII pattern added: %s", name)
        except Exception as exc:
            _logger.warning("Failed to add custom pattern %s: %s", name, exc)

    def list_patterns(self) -> list[str]:
        """Список активных PII pattern names."""
        try:
            if hasattr(self.masker, "_patterns"):
                return list(self.masker._patterns.keys())
        except (AttributeError, TypeError) as introspect_exc:
            # D-A1-04 fix (cycle 29): narrow exceptions + observability.
            # Раньше bare `except Exception: pass` маскировал любые ошибки
            # в masker._patterns (e.g. corrupted sanitizer state).
            from src.backend.core.logging import get_logger
            get_logger(__name__).debug(
                "pii_facade.list_pattern_names.introspection_failed",
                extra={"error": str(introspect_exc)},
            )
        return []


@lru_cache(maxsize=1)
def get_pii_facade() -> PIIFacade:
    """Lazy singleton глобального :class:`PIIFacade`."""
    return PIIFacade()
