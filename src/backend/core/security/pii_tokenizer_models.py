"""PIITokenizer models — data classes + helpers (S57 M2-#2 split).

Извлечено из :mod:`pii_tokenizer` (649 LOC → sub-package split).
Содержит pure-data models + low-level helpers (no I/O, no async, no Redis):

- :class:`EncryptedValue` — AES-GCM encrypted PII value
- :class:`TokenMap` — placeholder → EncryptedValue mapping
- :class:`PIIPolicy` — config dataclass
- :func:`_uuid_short` — 8-hex-char unique placeholder suffix
- :data:`_PRESIDIO_PLACEHOLDER_RE` — regex для Presidio placeholders

Re-exported из :mod:`pii_tokenizer` для backward-compat public API.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal


__all__ = ("EncryptedValue", "PIIPolicy", "TokenMap")


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