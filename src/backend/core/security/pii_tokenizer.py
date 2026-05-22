"""PIITokenizer — reversible PII tokenization layer (ADR-NEW-21, Sprint 25 W4).

Назначение
----------
Reversible PII токенизация поверх Presidio (S24 W1 ADR-NEW-16) для
банковского use-case'а:

    Иванов И.И., тел. +7-999-123-45-67, договор № 12345/CR-001
    ↓ mask_reversible (Presidio detect + UUIDv7 token + AES-GCM encrypt)
    <PERSON_a8f3>, тел. <PHONE_4b2c>, договор № <CONTRACT_d7e1>
    ↓ AIGateway.invoke(...)
    Уважаемый <PERSON_a8f3>, по договору <CONTRACT_d7e1> принято решение...
    ↓ unmask (AES-GCM decrypt + token replace)
    Уважаемый Иванов И.И., по договору 12345/CR-001 принято решение...

В отличие от legacy :class:`PIIMasker` (8 regex, irreversible) — поддерживает
round-trip "mask → LLM → unmask" с криптографической защитой :class:`TokenMap`
at-rest в Redis (TTL = ``policy.ttl_s``, ключ через :mod:`infrastructure.secrets`).

Capability
----------
``pii.tokenize.reversible.<scope>`` — обязательна для workflow'ов, использующих
``unmask`` round-trip. ``<scope>`` = доменная область (``banking``, ``hr``,
``medical``).

Audit-event
-----------
Каждое ``mask_reversible`` / ``unmask`` эмитит ``ai.pii.tokenize.{mask,unmask}``
через :class:`AuditService` (S17/K3) с ``entity_types`` (без значений).

См. также
---------
* docs/adr/0068-pii-tokenizer-reversible.md;
* :class:`infrastructure.security.token_registry.TokenRegistry`
  (Redis-backed storage);
* :class:`services.ai.pii.presidio_analyzer` (S24 W1 — engine backend).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = (
    "EncryptedValue",
    "PIIPolicy",
    "PIITokenizer",
    "TokenMap",
)


@dataclass(frozen=True, slots=True)
class EncryptedValue:
    """AES-GCM зашифрованное значение PII-сущности.

    Attributes:
        ciphertext: Зашифрованный исходный текст (bytes).
        nonce: AES-GCM nonce (12 bytes).
        tag: AES-GCM authentication tag (16 bytes).
        key_version: Версия ключа из Vault (для rotation).
    """

    ciphertext: bytes
    nonce: bytes
    tag: bytes
    key_version: int


@dataclass(frozen=True, slots=True)
class TokenMap:
    """Mapping placeholder → AES-GCM encrypted original.

    Хранится в Redis с TTL = ``policy.ttl_s``. Ключ Redis:
    ``"pii:token:{tenant_id}:{correlation_id}"``.

    Attributes:
        tokens: Словарь ``placeholder → EncryptedValue``.
            Пример: ``{"<PERSON_a8f3>": EncryptedValue(...)}``.
        policy_name: Имя :class:`PIIPolicy`, использованной при ``mask``.
        created_at: UTC timestamp создания.
        ttl_s: TTL в секундах.
    """

    tokens: dict[str, EncryptedValue]
    policy_name: str
    created_at: datetime
    ttl_s: int


@dataclass(frozen=True, slots=True)
class PIIPolicy:
    """Политика PII tokenization (config для PIITokenizer).

    Attributes:
        name: Уникальное имя политики (``"ru_strict_reversible"``,
            ``"en_default"``).
        language: ISO-код языка (``"ru"``, ``"en"``).
        entity_types: Tuple типов PII для детектирования
            (``("PERSON", "PHONE", "INN", "SNILS", "PASSPORT_RF", "CONTRACT")``).
        reversible: Если ``True`` — placeholders уникальны
            (``"<PERSON_a8f3>"``) + AES-GCM ``TokenMap``; если ``False`` —
            placeholders generic (``"<PERSON>"``) для audit-only.
        ttl_s: TTL TokenMap в Redis (только при ``reversible=True``).
        scope: Capability scope (``"banking"``, ``"hr"``).
    """

    name: str
    language: Literal["ru", "en"] = "ru"
    entity_types: tuple[str, ...] = (
        "PERSON",
        "PHONE_NUMBER",
        "EMAIL_ADDRESS",
        "IP_ADDRESS",
        "INN",
        "SNILS",
        "PASSPORT_RF",
        "CONTRACT",
    )
    reversible: bool = True
    ttl_s: int = 3600
    scope: str = "default"


class PIITokenizer:
    """Reversible PII tokenization через Presidio + AES-GCM TokenRegistry.

    Scaffold S25 W4 (ADR-NEW-21). Lazy-import Presidio (приходит из S24 W1
    при ``presidio_pii_enabled=True``).

    Use-cases:

    * **mask_reversible** → ``unmask`` round-trip для banking-сценариев;
    * **mask_irreversible** для audit-логов (Langfuse traces),
      где un-masking запрещён.

    Пример::

        tokenizer = PIITokenizer(token_registry=registry, audit=audit_service)
        masked, token_map = await tokenizer.mask_reversible(
            "Иванов И.И., договор № 12345",
            policy=PIIPolicy(name="ru_strict_reversible"),
        )
        completion = await ai_gateway.invoke(...)  # LLM работает с masked
        unmasked = await tokenizer.unmask(completion, token_map)

    Notes:
        Scaffold-методы поднимают ``NotImplementedError`` до подключения
        ``presidio-analyzer`` через S24 W1 ADR-NEW-16.
    """

    def __init__(
        self,
        *,
        token_registry: object | None = None,
        audit: object | None = None,
        presidio_analyzer: object | None = None,
    ) -> None:
        """Инициализация.

        Args:
            token_registry: :class:`TokenRegistry` (Redis + AES-GCM);
                при ``None`` — TokenMap живёт только в-памяти (testkit).
            audit: Unified ``AuditService`` для эмиссии
                ``ai.pii.tokenize.{mask,unmask}`` (S17/K3).
            presidio_analyzer: Presidio ``AnalyzerEngine`` (S24 W1);
                при ``None`` — fallback на legacy regex-маскер из
                :mod:`core.security.pii_masker`.
        """
        self._token_registry = token_registry
        self._audit = audit
        self._presidio = presidio_analyzer

    async def mask_reversible(
        self, text: str, policy: PIIPolicy
    ) -> tuple[str, TokenMap]:
        """Reversible PII tokenization.

        Args:
            text: Исходный текст для tokenization.
            policy: :class:`PIIPolicy` (язык, entity types, scope).

        Returns:
            Tuple ``(masked_text, token_map)``:

            * ``masked_text`` — текст с placeholders
              (``"Уважаемый <PERSON_a8f3>"``);
            * ``token_map`` — :class:`TokenMap` для :meth:`unmask`.

        Raises:
            CapabilityDeniedError: При отсутствии
                ``pii.tokenize.reversible.<scope>`` в plugin.toml.
            NotImplementedError: Полная реализация — S25 W4
                (Presidio integration).
        """
        del text, policy
        raise NotImplementedError("S25 W4: Presidio + AES-GCM integration")

    async def mask_irreversible(self, text: str, policy: PIIPolicy) -> str:
        """Irreversible PII masking (для audit / Langfuse traces).

        Использует generic placeholders (``"<PERSON>"``, ``"<PHONE>"``)
        без uniqueness — нельзя восстановить.

        Args:
            text: Исходный текст для маскировки.
            policy: :class:`PIIPolicy`.

        Returns:
            Masked text (без TokenMap).

        Raises:
            NotImplementedError: S25 W4 (Presidio integration).
        """
        del text, policy
        raise NotImplementedError("S25 W4: irreversible mask via Presidio")

    async def unmask(self, masked_text: str, token_map: TokenMap) -> str:
        """Восстановление исходного текста из masked + TokenMap.

        Args:
            masked_text: Текст с placeholders из :meth:`mask_reversible`.
            token_map: :class:`TokenMap` из той же mask-операции.

        Returns:
            Восстановленный исходный текст.

        Raises:
            CapabilityDeniedError: При отсутствии
                ``pii.tokenize.reversible.<scope>`` в plugin.toml.
            TokenMapExpiredError: TTL TokenMap истёк (Redis cleanup).
            NotImplementedError: S25 W4 (AES-GCM decrypt).
        """
        del masked_text, token_map
        raise NotImplementedError("S25 W4: AES-GCM decrypt + placeholder replace")

    async def cleanup_expired(self, ttl_s: int) -> int:
        """Удалить expired :class:`TokenMap` из Redis (TTL > ``ttl_s``).

        Запускается из :class:`TaskRegistry` (фоновый cleanup-loop).

        Args:
            ttl_s: TTL (сек), TokenMap старше — удаляются.

        Returns:
            Число удалённых TokenMap.

        Raises:
            NotImplementedError: S25 W4 (TokenRegistry cleanup hook).
        """
        del ttl_s
        raise NotImplementedError("S25 W4: TokenRegistry cleanup")

    def _supported_entity_types(self, language: str) -> "Sequence[str]":
        """Список поддерживаемых entity types для языка.

        Args:
            language: ISO-код языка.

        Returns:
            Tuple названий PII entity (PERSON, PHONE_NUMBER, ...).
        """
        ru_specific = ("INN", "SNILS", "PASSPORT_RF", "CONTRACT")
        common = ("PERSON", "PHONE_NUMBER", "EMAIL_ADDRESS", "IP_ADDRESS")
        return common + ru_specific if language == "ru" else common
