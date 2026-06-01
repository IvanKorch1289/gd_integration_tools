"""PIITokenizer — reversible PII tokenization layer (ADR-NEW-21, Sprint 25 W4).

Назначение
----------
Reversible PII токенизация поверх Presidio (S24 W1 ADR-NEW-16) для
банковского use-case'''а:

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
``pii.tokenize.reversible.<scope>`` — обязательна для workflow'''ов, использующих
``unmask`` round-trip. ``<scope>`` = доменная область (``banking``, ``hr``,
``medical``).

Audit-event
-----------
Каждое ``mask_reversible`` / ``unmask`` эмитит ``ai.pii.tokenize.{mask,unmask}``
через :class:`AuditService` (S17/K3) с ``entity_types`` (без значений).

См. также
---------
* docs/adr/0068-pii-tokenizer-reversible.md;
* :class:`infrastructure.security.token_registry.RedisTokenRegistry`
  (Redis-backed storage);
* :class:`services.ai.pii.presidio_analyzer` (S24 W1 — engine backend).
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ("EncryptedValue", "PIIPolicy", "PIITokenizer", "TokenMap")

_logger = logging.getLogger("core.security.pii_tokenizer")

# Presidio выдаёт placeholders формата ``[PERSON_1]`` / ``[INN_3]``;
# extract TYPE для перезаписи в UUIDv7-token ``<PERSON_a8f3>``.
_PRESIDIO_PLACEHOLDER_RE = re.compile(r"\[([A-Z_]+)_\d+\]")


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


def _uuid_short() -> str:
    """8-hex-char уникальный suffix для placeholder.

    Берём random tail (последние 8 hex chars) :func:`uuid.uuid7` — это часть
    ``random_b`` (62 bits случайности), а не timestamp-prefix (первые 12 hex
    одинаковы в рамках одной мс и дают коллизии). Fallback :func:`uuid.uuid4`
    при отсутствии ``uuid7`` (Python <3.14).
    """
    uuid7 = getattr(uuid, "uuid7", None)
    if uuid7 is not None:
        return uuid7().hex[-8:]
    return uuid.uuid4().hex[:8]


class PIITokenizer:
    """Reversible PII tokenization через Presidio + AES-GCM TokenRegistry.

    Sprint 25 W4 (ADR-NEW-21). Lazy-зависимости:

    * :class:`PresidioSanitizerAdapter` (приходит из S24 W1) — детектор PII;
    * :class:`RedisTokenRegistry` (S25 W4) — AES-GCM шифрование значений;
    * :class:`AuditService` (S17 K3) — emit ``ai.pii.tokenize.*``.

    Use-cases:

    * **mask_reversible** → ``unmask`` round-trip для banking-сценариев;
    * **mask_irreversible** для audit-логов (Langfuse traces),
      где un-masking запрещён.

    Пример::

        tokenizer = PIITokenizer(
            token_registry=registry,
            audit=audit_service,
            presidio_analyzer=presidio_adapter,
        )
        masked, token_map = await tokenizer.mask_reversible(
            "Иванов И.И., договор № 12345",
            policy=PIIPolicy(name="ru_strict_reversible"),
        )
        completion = await ai_gateway.invoke(...)  # LLM работает с masked
        unmasked = await tokenizer.unmask(completion, token_map)
    """

    def __init__(
        self,
        *,
        token_registry: Any | None = None,
        audit: Any | None = None,
        presidio_analyzer: Any | None = None,
    ) -> None:
        """Инициализация.

        Args:
            token_registry: :class:`RedisTokenRegistry` (Redis + AES-GCM);
                при ``None`` — TokenMap живёт только в-памяти (testkit) с
                синтетическим ``EncryptedValue`` (``key_version=0`` — sentinel).
            audit: :class:`AuditService` для эмиссии
                ``ai.pii.tokenize.{mask,unmask}`` (S17/K3); при ``None`` — no-op.
            presidio_analyzer: :class:`PresidioSanitizerAdapter` (S24 W1).
                Обязателен для ``mask_*`` методов; при ``None`` они поднимают
                ``RuntimeError``.
        """
        self._token_registry = token_registry
        self._audit = audit
        self._presidio = presidio_analyzer

    # ─── mask / unmask ────────────────────────────────────────────────────

    async def mask_reversible(
        self, text: str, policy: PIIPolicy
    ) -> tuple[str, TokenMap]:
        """Reversible PII tokenization.

        Алгоритм:
            1. Presidio детектирует PII → ``SanitizationResult`` с placeholders
               формата ``[PERSON_1]`` и mapping ``placeholder → original``.
            2. Для каждой entity: генерируем UUIDv7-short suffix →
               формируем ``<{TYPE}_{suffix}>`` (стабильно уникальный токен).
            3. Шифруем ``original`` через ``token_registry.encrypt_value`` →
               :class:`EncryptedValue`.
            4. Перезаписываем ``[PERSON_1]`` → ``<PERSON_a8f3>`` в тексте.
            5. Возвращаем ``(masked_text, TokenMap)``.

        Args:
            text: Исходный текст для tokenization.
            policy: :class:`PIIPolicy` (язык, entity types, scope).

        Returns:
            Tuple ``(masked_text, token_map)``.

        Raises:
            RuntimeError: при отсутствии ``presidio_analyzer`` в DI.
        """
        if not text:
            return text, TokenMap(
                tokens={},
                policy_name=policy.name,
                created_at=datetime.now(UTC),
                ttl_s=policy.ttl_s,
            )
        if self._presidio is None:
            raise RuntimeError(
                "PIITokenizer.mask_reversible requires presidio_analyzer "
                "(install gd_integration_tools[security-pii])"
            )

        result = await self._presidio.sanitize_async(text, language=policy.language)
        masked_text = result.sanitized_text
        new_tokens: dict[str, EncryptedValue] = {}
        entity_types_set: set[str] = set()

        for presidio_placeholder, original in result.replacements.items():
            match = _PRESIDIO_PLACEHOLDER_RE.fullmatch(presidio_placeholder)
            if not match:
                _logger.debug(
                    "skipping unrecognized placeholder format: %r", presidio_placeholder
                )
                continue
            entity_type = match.group(1)
            entity_types_set.add(entity_type)
            new_placeholder = f"<{entity_type}_{_uuid_short()}>"
            encrypted = self._encrypt(original)
            new_tokens[new_placeholder] = encrypted
            masked_text = masked_text.replace(presidio_placeholder, new_placeholder, 1)

        token_map = TokenMap(
            tokens=new_tokens,
            policy_name=policy.name,
            created_at=datetime.now(UTC),
            ttl_s=policy.ttl_s,
        )
        await self._emit_audit_safe(
            event="ai.pii.tokenize.mask",
            action="mask",
            outcome="success",
            details={
                "policy_name": policy.name,
                "scope": policy.scope,
                "reversible": True,
                "entity_types": sorted(entity_types_set),
                "token_count": len(new_tokens),
            },
        )
        return masked_text, token_map

    async def mask_irreversible(self, text: str, policy: PIIPolicy) -> str:
        """Irreversible PII masking (для audit / Langfuse traces).

        Использует generic placeholders (``"<PERSON>"``, ``"<PHONE_NUMBER>"``)
        без uniqueness — нельзя восстановить.

        Args:
            text: Исходный текст для маскировки.
            policy: :class:`PIIPolicy` (используется ``language`` и ``scope``).

        Returns:
            Masked text (без TokenMap).

        Raises:
            RuntimeError: при отсутствии ``presidio_analyzer`` в DI.
        """
        if not text:
            return text
        if self._presidio is None:
            raise RuntimeError(
                "PIITokenizer.mask_irreversible requires presidio_analyzer "
                "(install gd_integration_tools[security-pii])"
            )

        result = await self._presidio.sanitize_async(text, language=policy.language)
        masked_text = _PRESIDIO_PLACEHOLDER_RE.sub(
            lambda m: f"<{m.group(1)}>", result.sanitized_text
        )
        await self._emit_audit_safe(
            event="ai.pii.tokenize.mask",
            action="mask",
            outcome="success",
            details={
                "policy_name": policy.name,
                "scope": policy.scope,
                "reversible": False,
                "token_count": len(result.replacements),
            },
        )
        return masked_text

    async def unmask(self, masked_text: str, token_map: TokenMap) -> str:
        """Восстановление исходного текста из ``masked_text`` + ``token_map``.

        Для каждого ``placeholder ∈ token_map.tokens`` извлекает
        :class:`EncryptedValue` и подменяет в тексте на decrypted plaintext.
        При ``decrypt_value() = None`` (key rotation gap / tag mismatch) —
        placeholder остаётся в выводе и эмитится ``decrypt_failed``.

        Args:
            masked_text: Текст с placeholders из :meth:`mask_reversible`.
            token_map: :class:`TokenMap` из той же mask-операции.

        Returns:
            Восстановленный исходный текст. Placeholders, для которых
            decrypt не удался, остаются на месте.
        """
        if not token_map.tokens:
            return masked_text

        result_text = masked_text
        restored = 0
        failed = 0
        for placeholder, encrypted in token_map.tokens.items():
            original = self._decrypt(encrypted)
            if original is None:
                failed += 1
                continue
            if placeholder in result_text:
                result_text = result_text.replace(placeholder, original)
                restored += 1

        await self._emit_audit_safe(
            event="ai.pii.tokenize.unmask",
            action="unmask",
            outcome="success" if failed == 0 else "failure",
            details={
                "policy_name": token_map.policy_name,
                "tokens_restored": restored,
                "tokens_failed": failed,
            },
        )
        return result_text

    async def cleanup_expired(self, ttl_s: int) -> int:
        """Триггер cleanup просроченных TokenMap в Redis (delegated to registry).

        Redis сам удаляет expired через TTL; этот метод возвращает число
        живых записей под prefix (observability для cleanup-loop).

        Args:
            ttl_s: Зарезервированный параметр (TTL уже задан при ``store``).

        Returns:
            Число живых записей под prefix (0 если registry не задан).
        """
        del ttl_s
        if self._token_registry is None:
            return 0
        return await self._token_registry.cleanup_expired()

    # ─── internal helpers ─────────────────────────────────────────────────

    def _encrypt(self, plaintext: str) -> EncryptedValue:
        """Шифрует ``plaintext`` через TokenRegistry (или sentinel при testkit).

        Если ``token_registry`` не задан (testkit / unit-тест без crypto-stack) —
        возвращает sentinel :class:`EncryptedValue` с ``key_version=0`` и
        ``ciphertext`` = utf-8 bytes (decrypt в :meth:`_decrypt` симметричен).
        """
        if self._token_registry is None:
            return EncryptedValue(
                ciphertext=plaintext.encode("utf-8"),
                nonce=b"\x00" * 12,
                tag=b"\x00" * 16,
                key_version=0,
            )
        return self._token_registry.encrypt_value(plaintext)

    def _decrypt(self, value: EncryptedValue) -> str | None:
        """Дешифрует ``value`` через TokenRegistry (или sentinel при testkit)."""
        if self._token_registry is None:
            if value.key_version != 0:
                return None
            try:
                return value.ciphertext.decode("utf-8")
            except UnicodeDecodeError:
                return None
        return self._token_registry.decrypt_value(value)

    async def _emit_audit_safe(
        self, *, event: str, action: str, outcome: str, details: dict[str, Any]
    ) -> None:
        """Безопасный emit — никогда не ломает основной flow."""
        if self._audit is None:
            return
        try:
            await self._audit.emit(
                event=event,
                action=action,
                outcome=outcome,
                resource="pii_tokenizer",
                details=details,
            )
        except Exception as exc:  # noqa: BLE001 — audit не должен ломать pipeline
            _logger.debug("audit emit failed for %s: %r", event, exc)

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
