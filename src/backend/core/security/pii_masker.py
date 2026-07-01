"""Reusable PII masker для DSL/audit/streaming контекстов (Sprint 8A K1 W4).

Универсальный движок маскировки PII в строках и структурах данных.
В отличие от ``infrastructure/observability/pii_filter.py`` (узкий
structlog-processor) и ``infrastructure/security/pii_streaming.py``
(streaming SSE/WS), этот класс предназначен для синхронной маскировки
в произвольных Python-объектах: ``dict``, ``list``, ``tuple``, ``str``.

Используется:

* DSL processor ``mask_pii`` (``dsl/engine/processors/security/mask_pii.py``)
  — явный шаг маршрута для request/response body/headers/query/path;
* Inbox dedup audit (K1 S5 W5 — flag ``inbox_audit_pii_mask``) — внешний
  потребитель использует :func:`default_masker` поверх audit-payload до
  записи в ``audit_events``;
* любой Python-код, которому нужна синхронная PII-маскировка без
  зависимостей от Presidio/structlog.

API:

* :class:`PIIMasker` — основной класс с настраиваемыми patterns/replacement;
* :func:`default_masker` — module-level singleton с дефолтным набором
  регулярных выражений.

Дефолтные patterns покрывают:

* email — ``user@host.tld``;
* phone — E.164/RU-формат (``+7 (xxx) xxx-xx-xx``, ``+7 999 ...``);
* INN — 10 или 12 цифр (legal/individual);
* SNILS — ``XXX-XXX-XXX XX``;
* passport — RU ``XXXX XXXXXX``;
* credit_card — 13–19 цифр группами;
* jwt — Bearer-токен ``eyJ...`` (3 base64-сегмента через точку);
* iban — IBAN до 34 символов;
* ssn — US Social Security Number ``XXX-XX-XXXX`` (M2.1).

Порядок применения регексов важен — более специфичные паттерны
применяются первыми, чтобы не быть «съеденными» более общими.
"""

from __future__ import annotations

import re
from typing import Any

__all__ = ("PIIMasker", "build_default_patterns", "default_masker")


# Дефолтные регулярные выражения. Порядок задаётся ``_DEFAULT_ORDER``
# в :func:`build_default_patterns` — specific-first.
_EMAIL = re.compile(r"[\w.+\-]+@[\w\-]+\.[\w.\-]+")
# Phone: знак ``+`` или цифра, затем ≥10 цифр с возможными пробелами/дефисами/скобками.
_PHONE = re.compile(r"\+?\d[\d\s()\-]{8,}\d")
# RU SNILS — ``XXX-XXX-XXX YY`` (с пробелом или без перед последними двумя).
_SNILS = re.compile(r"\b\d{3}-\d{3}-\d{3}\s?\d{2}\b")
# INN — 10 цифр (юр.лицо) или 12 цифр (физ.лицо) сплошняком.
_INN = re.compile(r"\b\d{12}\b|\b\d{10}\b")
# Credit card — 13–19 цифр группами через пробел/дефис.
_CARD = re.compile(r"\b(?:\d[ \-]?){13,19}\b")
# RU passport — 4 цифры + пробел + 6 цифр.
_RU_PASSPORT = re.compile(r"\b\d{4}\s\d{6}\b")
# JWT — три base64url-сегмента, разделённых точкой (Bearer-токены, OAuth).
_JWT = re.compile(r"\beyJ[\w\-]+\.[\w\-]+\.[\w\-]+\b")
# IBAN — 2 буквы страны + 2 контрольные + до 30 символов (всего 15–34 длиной).
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")
# SSN (US Social Security Number) — 3-2-4 через дефис (M2.1).
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


# Порядок применения. Specific-first: разделительные форматы и токены до
# сплошных цифровых последовательностей. См. docstring модуля.
_DEFAULT_ORDER: tuple[str, ...] = (
    "jwt",
    "iban",
    "ssn",
    "snils",
    "card",
    "passport",
    "email",
    "inn",
    "phone",
)


def build_default_patterns() -> dict[str, re.Pattern[str]]:
    """Возвращает копию словаря дефолтных compiled-regex-ов.

    Returns:
        Словарь ``{name: compiled_pattern}`` — порядок ключей соответствует
        :data:`_DEFAULT_ORDER`. Можно безопасно мутировать (это новый dict).
    """
    return {
        "jwt": _JWT,
        "iban": _IBAN,
        "ssn": _SSN,
        "snils": _SNILS,
        "card": _CARD,
        "passport": _RU_PASSPORT,
        "email": _EMAIL,
        "inn": _INN,
        "phone": _PHONE,
    }


class PIIMasker:
    """Маскировка PII в строках и структурах данных.

    Применяет набор compiled-regex-ов в детерминированном порядке.
    По умолчанию использует :func:`build_default_patterns` (9 типов PII).

    Examples:
        >>> masker = PIIMasker()
        >>> masker.mask_text("Звоните +7 (999) 123-45-67 или alice@example.com")
        'Звоните *** или ***'

        >>> masker.mask_dict({"user": {"email": "bob@x.io", "age": 30}})
        {'user': {'email': '***', 'age': 30}}

    Attributes:
        replacement: Строка, на которую заменяется каждый match.
    """

    def __init__(
        self,
        patterns: dict[str, re.Pattern[str]] | None = None,
        replacement: str = "***",
        *,
        order: tuple[str, ...] | None = None,
    ) -> None:
        """Инициализация маскера.

        Args:
            patterns: Словарь ``{name: compiled_pattern}``. Если ``None`` —
                используется :func:`build_default_patterns`.
            replacement: Строка-заменитель для всех match-ей.
            order: Tuple имён patterns в порядке применения. Если ``None`` —
                для дефолтных patterns используется :data:`_DEFAULT_ORDER`,
                иначе берётся порядок ключей словаря ``patterns``.
        """
        self._patterns: dict[str, re.Pattern[str]] = (
            dict(patterns) if patterns is not None else build_default_patterns()
        )
        self.replacement = replacement
        if order is not None:
            self._order = tuple(name for name in order if name in self._patterns)
        elif patterns is None:
            self._order = _DEFAULT_ORDER
        else:
            self._order = tuple(self._patterns.keys())

    def mask_text(self, text: str) -> str:
        """Заменяет все matches PII-паттернов в строке на ``replacement``.

        Args:
            text: Произвольная строка. Если ``text`` пустой — возвращается
                как есть.

        Returns:
            Строка с заменёнными PII-фрагментами.
        """
        if not text:
            return text
        result = text
        for name in self._order:
            pattern = self._patterns.get(name)
            if pattern is None:
                continue
            result = pattern.sub(self.replacement, result)
        return result

    def mask_dict(
        self, data: dict[str, Any], fields: list[str] | None = None
    ) -> dict[str, Any]:
        """Рекурсивно маскирует строковые значения в dict.

        Args:
            data: Исходный словарь (не мутируется — возвращается копия).
            fields: Список ключей, в которых маскировать значения. Если
                ``None`` — маскируются все строковые значения на любом
                уровне вложенности. Сравнение по имени ключа, не по
                JSON-pointer.

        Returns:
            Новый словарь с маскированными значениями.
        """
        return self._mask_any(data, fields)

    def _mask_any(self, value: Any, fields: list[str] | None) -> Any:
        """Рекурсивный обход произвольной структуры данных.

        Поддерживает dict / list / tuple / str. Числа, bool, None и прочие
        неизменяемые типы возвращаются как есть.
        """
        match value:
            case str() as s:
                return self.mask_text(s) if fields is None else s
            case dict() as d:
                return {k: self._mask_dict_value(k, v, fields) for k, v in d.items()}
            case list() as lst:
                return [self._mask_any(item, fields) for item in lst]
            case tuple() as tup:
                return tuple(self._mask_any(item, fields) for item in tup)
            case _:
                return value

    def _mask_dict_value(self, key: str, value: Any, fields: list[str] | None) -> Any:
        """Маскирует одно значение в dict с учётом ``fields`` whitelist.

        Если ``fields`` не задан — рекурсивный обход с маскировкой всех
        строк. Если ``fields`` задан — маскируется только если ``key`` в
        нём; в остальном случае рекурсивно ищем вложенные dict/list для
        возможных совпадений по ключу.
        """
        if fields is None:
            return self._mask_any(value, None)
        if key in fields:
            return self._mask_any(value, None) if isinstance(value, str) else value
        # Ключ не в whitelist — но внутри value может быть вложенный dict
        # с подходящим ключом, проверим рекурсивно.
        if isinstance(value, (dict, list, tuple)):
            return self._mask_any(value, fields)
        return value


_DEFAULT_MASKER: PIIMasker | None = None


def default_masker() -> PIIMasker:
    """Возвращает module-level singleton :class:`PIIMasker` с дефолтами.

    Lazy-инициализация — масштабируется без cost на import. Используется
    в DSL processor ``mask_pii`` и audit-PII-masking без аргументов.

    Returns:
        Singleton с дефолтным набором patterns и replacement ``"***"``.
    """
    global _DEFAULT_MASKER
    if _DEFAULT_MASKER is None:
        _DEFAULT_MASKER = PIIMasker()
    return _DEFAULT_MASKER
