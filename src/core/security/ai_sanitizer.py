"""Маскировка PII перед отправкой данных в внешние LLM.

Обеспечивает reversible masking: заменяет чувствительные данные
на плейсхолдеры перед отправкой в AI, восстанавливает оригинал
после получения ответа.

Паттерны маскировки:
- Email → [EMAIL_1], [EMAIL_2], ...
- Телефон → [PHONE_1], [PHONE_2], ...
- ИНН → [INN_1], ...
- СНИЛС → [SNILS_1], ...
- Паспорт → [PASSPORT_1], ...
- Номер карты → [CARD_1], ...
- API-ключи/токены → [REDACTED]
"""

import re
from dataclasses import dataclass, field
from typing import Any

__all__ = ("AIDataSanitizer", "SanitizationResult")

# Регулярные выражения для PII
_EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
_PHONE_RE = re.compile(r"\+?[78][\d\s\-()]{9,}\d")
_INN_RE = re.compile(r"\b\d{10,12}\b")
_SNILS_RE = re.compile(r"\b\d{3}-\d{3}-\d{3}\s?\d{2}\b")
_PASSPORT_RE = re.compile(r"\b\d{2}\s?\d{2}\s?\d{6}\b")
_CARD_RE = re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b")
_API_KEY_RE = re.compile(
    r"(?:Bearer|Token|sk-|hf_|api[_-]?key[=:]\s*)[a-zA-Z0-9_\-./]{10,}",
    re.IGNORECASE,
)

_SENSITIVE_DICT_KEYS = frozenset({
    "password", "secret", "token", "api_key", "apikey",
    "access_token", "refresh_token", "authorization",
    "private_key", "secret_key", "credentials",
})


@dataclass(slots=True)
class SanitizationResult:
    """Результат маскировки с возможностью восстановления."""
    sanitized: str
    _mapping: dict[str, str] = field(default_factory=dict)

    def restore(self, text: str) -> str:
        """Восстанавливает оригинальные значения в тексте."""
        result = text
        for placeholder, original in self._mapping.items():
            result = result.replace(placeholder, original)
        return result


class AIDataSanitizer:
    """Маскировка PII перед отправкой в внешние AI-модели.

    Поддерживает reversible masking — маскирует перед отправкой,
    восстанавливает после получения ответа.
    """

    def __init__(
        self,
        *,
        mask_emails: bool = True,
        mask_phones: bool = True,
        mask_inn: bool = True,
        mask_snils: bool = True,
        mask_passport: bool = True,
        mask_cards: bool = True,
        mask_api_keys: bool = True,
        custom_patterns: list[tuple[str, re.Pattern]] | None = None,
    ) -> None:
        self._rules: list[tuple[str, re.Pattern]] = []

        if mask_api_keys:
            self._rules.append(("REDACTED", _API_KEY_RE))
        if mask_emails:
            self._rules.append(("EMAIL", _EMAIL_RE))
        if mask_phones:
            self._rules.append(("PHONE", _PHONE_RE))
        if mask_cards:
            self._rules.append(("CARD", _CARD_RE))
        if mask_snils:
            self._rules.append(("SNILS", _SNILS_RE))
        if mask_passport:
            self._rules.append(("PASSPORT", _PASSPORT_RE))
        if mask_inn:
            self._rules.append(("INN", _INN_RE))

        if custom_patterns:
            self._rules.extend(custom_patterns)

    def sanitize_text(self, text: str) -> SanitizationResult:
        """Маскирует PII в тексте.

        Args:
            text: Исходный текст с возможными PII.

        Returns:
            SanitizationResult с замаскированным текстом
            и маппингом для восстановления.
        """
        mapping: dict[str, str] = {}
        counters: dict[str, int] = {}
        result = text

        for label, pattern in self._rules:
            for match in pattern.finditer(result):
                original = match.group()
                if original in mapping.values():
                    continue

                if label == "REDACTED":
                    placeholder = "[REDACTED]"
                else:
                    counters.setdefault(label, 0)
                    counters[label] += 1
                    placeholder = f"[{label}_{counters[label]}]"

                mapping[placeholder] = original

        for placeholder, original in mapping.items():
            result = result.replace(original, placeholder)

        return SanitizationResult(sanitized=result, _mapping=mapping)

    def sanitize_dict(self, data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
        """Маскирует PII в словаре (рекурсивно).

        Args:
            data: Словарь с возможными PII в значениях.

        Returns:
            Кортеж (замаскированный словарь, маппинг для восстановления).
        """
        full_mapping: dict[str, str] = {}
        sanitized = self._sanitize_value(data, full_mapping)
        return sanitized, full_mapping

    def _sanitize_value(self, value: Any, mapping: dict[str, str]) -> Any:
        if isinstance(value, str):
            result = self.sanitize_text(value)
            mapping.update(result._mapping)
            return result.sanitized

        if isinstance(value, dict):
            out: dict[str, Any] = {}
            for k, v in value.items():
                if k.lower() in _SENSITIVE_DICT_KEYS:
                    out[k] = "***"
                else:
                    out[k] = self._sanitize_value(v, mapping)
            return out

        if isinstance(value, list):
            return [self._sanitize_value(item, mapping) for item in value]

        return value

    def sanitize_messages(
        self, messages: list[dict[str, str]]
    ) -> tuple[list[dict[str, str]], dict[str, str]]:
        """Маскирует PII в списке сообщений для LLM.

        Args:
            messages: [{role: ..., content: ...}].

        Returns:
            Кортеж (замаскированные сообщения, маппинг).
        """
        full_mapping: dict[str, str] = {}
        sanitized: list[dict[str, str]] = []

        for msg in messages:
            content = msg.get("content", "")
            result = self.sanitize_text(content)
            full_mapping.update(result._mapping)
            sanitized.append({**msg, "content": result.sanitized})

        return sanitized, full_mapping

    @staticmethod
    def restore_text(text: str, mapping: dict[str, str]) -> str:
        """Восстанавливает оригинальные значения."""
        result = text
        for placeholder, original in mapping.items():
            result = result.replace(placeholder, original)
        return result


def get_ai_sanitizer() -> AIDataSanitizer:
    """Фабрика AIDataSanitizer с настройками из конфига."""
    from app.core.config.ai_settings import ai_providers_settings as cfg

    return AIDataSanitizer(
        mask_emails=cfg.sanitize_emails,
        mask_phones=cfg.sanitize_phones,
        mask_inn=cfg.sanitize_inn,
        mask_snils=cfg.sanitize_snils,
        mask_passport=cfg.sanitize_passport,
        mask_cards=cfg.sanitize_card_numbers,
        mask_api_keys=cfg.sanitize_api_keys,
    )
