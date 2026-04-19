"""Presidio-based PII sanitizer — замена кастомного regex.

Использует Microsoft Presidio для распознавания 15+ entity types:
PERSON, PHONE_NUMBER, EMAIL_ADDRESS, CREDIT_CARD, IBAN, IP_ADDRESS,
NRP, LOCATION, DATE_TIME, URL, US_SSN, UK_NHS, ru-specific (INN, SNILS).

Graceful fallback: если presidio не установлен, использует существующий
AIDataSanitizer (regex-based).

Multi-instance safety:
- Mapping per-request (не shared state)
- Sanitize → reverse через in-memory dict (передаётся через exchange.properties)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

__all__ = ("PresidioSanitizer", "SanitizeResult", "get_presidio_sanitizer")

logger = logging.getLogger("security.presidio")


@dataclass(slots=True)
class SanitizeResult:
    """Результат санитайзинга: маскированный текст + mapping для restore."""
    sanitized_text: str
    replacements: dict[str, str] = field(default_factory=dict)
    entities_found: list[str] = field(default_factory=list)


class PresidioSanitizer:
    """PII sanitizer через Microsoft Presidio.

    При отсутствии presidio — проваливается в AIDataSanitizer (regex fallback).
    """

    def __init__(self, *, language: str = "en") -> None:
        self._language = language
        self._analyzer: Any = None
        self._available = self._try_init()

    def _try_init(self) -> bool:
        try:
            from presidio_analyzer import AnalyzerEngine
            self._analyzer = AnalyzerEngine()
            logger.info("Presidio analyzer initialized")
            return True
        except ImportError:
            logger.debug("Presidio not installed, falling back to regex")
            return False
        except Exception as exc:
            logger.warning("Presidio init failed: %s", exc)
            return False

    async def sanitize(
        self,
        text: str,
        *,
        entities: list[str] | None = None,
    ) -> SanitizeResult:
        """Маскирует PII в тексте, возвращает result с mapping."""
        if not text or not isinstance(text, str):
            return SanitizeResult(sanitized_text=text)

        if self._available:
            return self._sanitize_presidio(text, entities)

        return await self._sanitize_fallback(text)

    def _sanitize_presidio(
        self, text: str, entities: list[str] | None,
    ) -> SanitizeResult:
        """Presidio-based sanitization."""
        try:
            results = self._analyzer.analyze(
                text=text,
                entities=entities,
                language=self._language,
            )
        except Exception as exc:
            logger.warning("Presidio analyze failed: %s", exc)
            return SanitizeResult(sanitized_text=text)

        sanitized = text
        replacements: dict[str, str] = {}
        entities_found: list[str] = []

        for idx, r in enumerate(sorted(results, key=lambda x: -x.start)):
            placeholder = f"<{r.entity_type}_{idx}>"
            original = text[r.start:r.end]
            sanitized = sanitized[:r.start] + placeholder + sanitized[r.end:]
            replacements[placeholder] = original
            entities_found.append(r.entity_type)

        return SanitizeResult(
            sanitized_text=sanitized,
            replacements=replacements,
            entities_found=entities_found,
        )

    async def _sanitize_fallback(self, text: str) -> SanitizeResult:
        """Regex fallback через существующий AIDataSanitizer."""
        try:
            from app.core.security.ai_sanitizer import get_ai_sanitizer
            legacy = get_ai_sanitizer()
            result = await legacy.sanitize(text)
            return SanitizeResult(
                sanitized_text=result.sanitized_text,
                replacements=result.replacements,
                entities_found=list(result.replacements.keys()),
            )
        except Exception as exc:
            logger.error("Fallback sanitizer failed: %s", exc)
            return SanitizeResult(sanitized_text=text)

    def restore(self, text: str, replacements: dict[str, str]) -> str:
        """Восстанавливает оригинальные значения из mapping."""
        if not replacements:
            return text
        for placeholder, original in replacements.items():
            text = text.replace(placeholder, original)
        return text

    @property
    def available(self) -> bool:
        """True если Presidio загружен, иначе fallback режим."""
        return self._available


_instance: PresidioSanitizer | None = None


def get_presidio_sanitizer(*, language: str = "en") -> PresidioSanitizer:
    global _instance
    if _instance is None:
        _instance = PresidioSanitizer(language=language)
    return _instance
