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

Redis-backed TokenMap (Sprint 2.5)
----------------------------------
При наличии :class:`RedisTokenRegistry` + ``tenant_id``/``correlation_id``
в вызове :meth:`mask_reversible` TokenMap автоматически персистится в Redis
с ключом ``"pii:token:{tenant_id}:{correlation_id}"`` (TTL = ``policy.ttl_s``).
Извлечение — :meth:`unmask_by_key(tenant_id, correlation_id, masked_text)`.
Backward-compat: при отсутствии ``tenant_id``/``correlation_id`` TokenMap
возвращается в памяти (testkit / single-process use-cases).

Capability
----------
``pii.tokenize.reversible.<scope>`` — обязательна для workflow'''ов, использующих
``unmask`` round-trip. ``<scope>`` = доменная область (``banking``, ``hr``,
``medical``). Опц. проверка через :class:`CapabilityGate` при
``require_capability=True`` (backward-compat: по умолчанию ``False``).

Audit-event
-----------
Каждое ``mask_reversible`` / ``unmask`` / ``unmask_by_key`` эмитит
``ai.pii.tokenize.{mask,unmask}`` через :class:`AuditService` (S17/K3) с
``entity_types`` (без значений). Redis-операции (``store`` / ``retrieve``)
эмитятся внутри :class:`RedisTokenRegistry` (``ai.pii.tokenize.store`` /
``.retrieve``).

См. также
---------
* docs/adr/0068-pii-tokenizer-reversible.md;
* :class:`infrastructure.security.token_registry.RedisTokenRegistry`
  (Redis-backed storage);
* :class:`services.ai.pii.presidio_analyzer` (S24 W1 — engine backend);
* :class:`core.security.capabilities.gate.CapabilityGate` (опц. reversibility check).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from src.backend.core.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ("EncryptedValue", "PIIPolicy", "PIITokenizer", "TokenMap")

_logger = get_logger("core.security.pii_tokenizer")

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
        capability_gate: Any | None = None,
    ) -> None:
        """Инициализация.

        Args:
            token_registry: :class:`RedisTokenRegistry` (Redis + AES-GCM);
                при ``None`` — TokenMap живёт только в-памяти (testkit) с
                синтетическим :class:`EncryptedValue` (``key_version=0`` —
                sentinel). При заданном registry + ``tenant_id``/
                ``correlation_id`` в :meth:`mask_reversible` TokenMap
                автоматически персистится в Redis (TTL = ``policy.ttl_s``).
            audit: :class:`AuditService` для эмиссии
                ``ai.pii.tokenize.{mask,unmask}`` (S17/K3); при ``None`` — no-op.
            presidio_analyzer: :class:`PresidioSanitizerAdapter` (S24 W1).
                Обязателен для ``mask_*`` методов; при ``None`` они поднимают
                ``RuntimeError``.
            capability_gate: Опц. :class:`CapabilityGate` для проверки
                ``pii.tokenize.reversible.<scope>`` при ``require_capability=True``
                в :meth:`mask_reversible`/``unmask_by_key``. При ``None`` —
                capability check пропускается (backward-compat для testkit
                и существующих call-сайтов, которые уже делают gate-check
                на уровне DSL/AIGateway).
        """
        self._token_registry = token_registry
        self._audit = audit
        self._presidio = presidio_analyzer
        self._capability_gate = capability_gate

    # ─── mask / unmask ────────────────────────────────────────────────────

    async def mask_reversible(
        self,
        text: str,
        policy: PIIPolicy,
        *,
        tenant_id: str | None = None,
        correlation_id: str | None = None,
        persist_to_redis: bool = True,
        require_capability: bool = False,
    ) -> tuple[str, TokenMap]:
        """Reversible PII tokenization с опц. Redis-персистенцией TokenMap.

        Алгоритм:
            1. Опц. capability check ``pii.tokenize.reversible.<scope>``
               (при ``require_capability=True`` + ``capability_gate`` заданы).
            2. Presidio детектирует PII → ``SanitizationResult`` с placeholders
               формата ``[PERSON_1]`` и mapping ``placeholder → original``.
            3. Для каждой entity: генерируем UUIDv7-short suffix →
               формируем ``<{TYPE}_{suffix}>`` (стабильно уникальный токен).
            4. Шифруем ``original`` через ``token_registry.encrypt_value`` →
               :class:`EncryptedValue`.
            5. Перезаписываем ``[PERSON_1]`` → ``<PERSON_a8f3>`` в тексте.
            6. При наличии ``token_registry`` + ``tenant_id`` + ``correlation_id``
               + ``persist_to_redis=True`` — вызываем
               ``token_registry.store(key, token_map, ttl_s=policy.ttl_s)``
               с ``key = f"{tenant_id}:{correlation_id}"`` (Redis key:
               ``"pii:token:{tenant_id}:{correlation_id}"``).
            7. Возвращаем ``(masked_text, TokenMap)``.

        Args:
            text: Исходный текст для tokenization.
            policy: :class:`PIIPolicy` (язык, entity types, scope).
            tenant_id: Tenant ID для Redis-ключа (``pii:token:{tenant_id}:...``).
                При ``None`` — TokenMap остаётся только в памяти.
            correlation_id: Correlation ID для Redis-ключа.
                При ``None`` — TokenMap остаётся только в памяти.
            persist_to_redis: Если ``True`` + ``token_registry`` задан +
                ``tenant_id``/``correlation_id`` непустые → сохранить TokenMap
                в Redis (TTL = ``policy.ttl_s``). По умолчанию ``True``,
                backward-compat с in-memory use-cases через явный
                ``persist_to_redis=False``.
            require_capability: Если ``True`` + ``capability_gate`` задан →
                проверка ``pii.tokenize.reversible.<scope>``. По умолчанию
                ``False`` (call-site решает, где делать gate-check — DSL/AIGateway).

        Returns:
            Tuple ``(masked_text, token_map)``.

        Raises:
            RuntimeError: при отсутствии ``presidio_analyzer`` в DI.
            CapabilityDeniedError: при ``require_capability=True`` и
                ``capability_gate`` отказал в scope.
        """
        if require_capability and self._capability_gate is not None:
            self._capability_check(policy.scope)
        if not text:
            empty_token_map = TokenMap(
                tokens={},
                policy_name=policy.name,
                created_at=datetime.now(UTC),
                ttl_s=policy.ttl_s,
            )
            await self._maybe_persist_token_map(
                empty_token_map,
                tenant_id=tenant_id,
                correlation_id=correlation_id,
                persist_to_redis=persist_to_redis,
                policy_ttl_s=policy.ttl_s,
            )
            return text, empty_token_map
        if self._presidio is None:
            raise RuntimeError(
                "PIITokenizer.mask_reversible requires presidio_analyzer "
                "(install gd_integration_tools[ai-safety])",
            )

        result = await self._presidio.sanitize_async(text, language=policy.language)
        masked_text = result.sanitized_text
        new_tokens: dict[str, EncryptedValue] = {}
        entity_types_set: set[str] = set()

        for presidio_placeholder, original in result.replacements.items():
            match = _PRESIDIO_PLACEHOLDER_RE.fullmatch(presidio_placeholder)
            if not match:
                _logger.debug(
                    "skipping unrecognized placeholder format: %r", presidio_placeholder,
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
        await self._maybe_persist_token_map(
            token_map,
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            persist_to_redis=persist_to_redis,
            policy_ttl_s=policy.ttl_s,
        )
        await self._audit_safe_emit(
            event="ai.pii.tokenize.mask",
            action="mask",
            outcome="success",
            details={
                "policy_name": policy.name,
                "scope": policy.scope,
                "reversible": True,
                "entity_types": sorted(entity_types_set),
                "token_count": len(new_tokens),
                "persisted": bool(
                    persist_to_redis
                    and self._token_registry is not None
                    and tenant_id
                    and correlation_id
                ),
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
                "(install gd_integration_tools[ai-safety])",
            )

        result = await self._presidio.sanitize_async(text, language=policy.language)
        masked_text = _PRESIDIO_PLACEHOLDER_RE.sub(
            lambda m: f"<{m.group(1)}>", result.sanitized_text,
        )
        await self._audit_safe_emit(
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

        await self._audit_safe_emit(
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

    async def unmask_by_key(
        self,
        masked_text: str,
        *,
        tenant_id: str,
        correlation_id: str,
        require_capability: bool = False,
        fallback_scope: str = "default",
    ) -> str:
        """Восстановление исходного текста из Redis-персистентного TokenMap.

        Извлекает :class:`TokenMap` через
        ``token_registry.retrieve(f"{tenant_id}:{correlation_id}")`` и делегирует
        :meth:`unmask`. При miss/expired возвращает входной текст без изменений
        + эмитит ``ai.pii.tokenize.unmask`` с ``outcome="failure"`` и
        ``reason="token_map_missing"``.

        Args:
            masked_text: Текст с placeholders из :meth:`mask_reversible`.
            tenant_id: Tenant ID (компонент Redis-ключа).
            correlation_id: Correlation ID (компонент Redis-ключа).
            require_capability: Если ``True`` + ``capability_gate`` задан →
                проверка ``pii.tokenize.reversible.<fallback_scope>``.
            fallback_scope: Scope для capability check, если в TokenMap не
                зафиксирован policy-scope (по умолчанию ``"default"``).

        Returns:
            Восстановленный исходный текст. При отсутствии TokenMap в Redis
            возвращается ``masked_text`` без изменений.

        Raises:
            RuntimeError: при отсутствии ``token_registry`` в DI (нужен
                Redis-источник для retrieve).
        """
        if self._token_registry is None:
            raise RuntimeError(
                "PIITokenizer.unmask_by_key requires token_registry "
                "(Redis-backed persistence is mandatory for cross-process unmask)"
            )
        if require_capability and self._capability_gate is not None:
            self._capability_check(fallback_scope)
        redis_key = self._build_redis_key(tenant_id, correlation_id)
        token_map = await self._token_registry.retrieve(redis_key)
        if token_map is None:
            _logger.warning(
                "unmask_by_key: TokenMap missing for %s (expired or evicted)",
                redis_key,
            )
            await self._audit_safe_emit(
                event="ai.pii.tokenize.unmask",
                action="unmask",
                outcome="failure",
                details={
                    "reason": "token_map_missing",
                    "redis_key": redis_key,
                    "policy_name": "unknown",
                    "tokens_restored": 0,
                    "tokens_failed": 0,
                },
            )
            return masked_text
        return await self.unmask(masked_text, token_map)

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

    async def _audit_safe_emit(
        self, *, event: str, action: str, outcome: str, details: dict[str, Any],
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
        except Exception as exc:
            _logger.debug("audit emit failed for %s: %r", event, exc)

    async def _maybe_persist_token_map(
        self,
        token_map: TokenMap,
        *,
        tenant_id: str | None,
        correlation_id: str | None,
        persist_to_redis: bool,
        policy_ttl_s: int,
    ) -> None:
        """Persist ``token_map`` в Redis при наличии registry + tenant/correlation.

        No-op при:

        * ``persist_to_redis=False`` (явный opt-out для in-memory use-case);
        * ``token_registry is None`` (testkit / no crypto-stack);
        * ``tenant_id`` или ``correlation_id`` отсутствуют (нет изоляции).

        При ошибке Redis — логируем warning, но НЕ ломаем основной flow
        (caller всё ещё имеет TokenMap в памяти для локального ``unmask``).
        """
        if not persist_to_redis:
            return
        if self._token_registry is None:
            return
        if not tenant_id or not correlation_id:
            return
        redis_key = self._build_redis_key(tenant_id, correlation_id)
        try:
            await self._token_registry.store(redis_key, token_map, ttl_s=policy_ttl_s)
        except Exception as exc:
            _logger.warning(
                "TokenMap persistence to Redis failed (key=%s): %r — "
                "in-memory TokenMap остаётся доступным для локального unmask",
                redis_key,
                exc,
            )

    @staticmethod
    def _build_redis_key(tenant_id: str, correlation_id: str) -> str:
        """Собрать логический ключ для :meth:`RedisTokenRegistry.store`.

        Redis-ключ формируется внутри :meth:`RedisTokenRegistry._build_key`
        как ``f"{key_prefix}:{key}"`` (``"pii:token:..."`` по умолчанию).
        """
        return f"{tenant_id}:{correlation_id}"

    def _capability_check(self, scope: str) -> None:
        """Проверка ``pii.tokenize.reversible.<scope>`` через :class:`CapabilityGate`.

        Использует plugin-name ``"core.pii_tokenizer"`` (call-site решает,
        какой plugin-scope реальный). При ``capability_gate is None`` —
        no-op (вызывающий код гарантирует gate-check на своём уровне).
        """
        if self._capability_gate is None:
            return
        capability = f"pii.tokenize.reversible.{scope}"
        check = getattr(self._capability_gate, "check", None)
        if check is None:
            _logger.debug(
                "CapabilityGate %r не имеет метода check() — capability "
                "check skipped for %s",
                self._capability_gate,
                capability,
            )
            return
        check(plugin="core.pii_tokenizer", capability=capability, requested_scope=scope)

    def _supported_entity_types(self, language: str) -> Sequence[str]:
        """Список поддерживаемых entity types для языка.

        Args:
            language: ISO-код языка.

        Returns:
            Sequence названий PII entity (PERSON, PHONE_NUMBER, ...).

        """
        ru_specific = ("INN", "SNILS", "PASSPORT_RF", "CONTRACT")
        common = ("PERSON", "PHONE_NUMBER", "EMAIL_ADDRESS", "IP_ADDRESS")
        return common + ru_specific if language == "ru" else common
