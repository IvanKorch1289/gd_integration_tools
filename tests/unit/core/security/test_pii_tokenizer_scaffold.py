"""Smoke-тесты scaffold :class:`PIITokenizer` (Sprint 25 W4, ADR-NEW-21).

Покрывают:

* импорт классов и dataclass'''ов;
* :class:`PIIPolicy` defaults (ru-banking entity types);
* :class:`PIITokenizer` без deps: ``mask_*`` поднимает RuntimeError
  при отсутствии ``presidio_analyzer``; ``unmask`` с пустым TokenMap —
  возвращает входной текст;
* :meth:`PIITokenizer._supported_entity_types` различает ru / en.

Полноценный round-trip с Presidio + AES-GCM — отдельный набор
:mod:`tests.unit.core.security.test_pii_tokenizer_roundtrip` (S25 W4).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.backend.core.security.pii_tokenizer import (
    EncryptedValue,
    PIIPolicy,
    PIITokenizer,
    TokenMap,
)


def test_pii_policy_defaults_for_russian() -> None:
    """PIIPolicy default ru-конфигурация содержит банковские entity types."""
    policy = PIIPolicy(name="ru_strict_reversible")
    assert policy.language == "ru"
    assert policy.reversible is True
    assert policy.ttl_s == 3600
    assert "PERSON" in policy.entity_types
    assert "INN" in policy.entity_types
    assert "SNILS" in policy.entity_types
    assert "PASSPORT_RF" in policy.entity_types
    assert "CONTRACT" in policy.entity_types


def test_pii_policy_irreversible_variant() -> None:
    """PIIPolicy irreversible вариант — для audit-логов."""
    policy = PIIPolicy(name="ru_audit", reversible=False, language="ru")
    assert policy.reversible is False


def test_encrypted_value_dataclass_frozen() -> None:
    """EncryptedValue frozen+slots."""
    ev = EncryptedValue(
        ciphertext=b"\x00\x01\x02", nonce=b"n" * 12, tag=b"t" * 16, key_version=1
    )
    assert ev.key_version == 1
    with pytest.raises(AttributeError):
        ev.key_version = 2  # type: ignore[misc]


def test_token_map_dataclass() -> None:
    """TokenMap хранит словарь placeholders + metadata."""
    now = datetime.now(UTC)
    token_map = TokenMap(
        tokens={
            "<PERSON_a8f3>": EncryptedValue(
                ciphertext=b"\x00", nonce=b"n" * 12, tag=b"t" * 16, key_version=1
            )
        },
        policy_name="ru_strict_reversible",
        created_at=now,
        ttl_s=3600,
    )
    assert "<PERSON_a8f3>" in token_map.tokens
    assert token_map.policy_name == "ru_strict_reversible"
    assert token_map.ttl_s == 3600


def test_pii_tokenizer_construction_without_deps() -> None:
    """PIITokenizer конструируется без backend'''ов (все Optional)."""
    tokenizer = PIITokenizer()
    assert tokenizer is not None


@pytest.mark.asyncio
async def test_mask_reversible_requires_presidio_analyzer() -> None:
    """Без presidio_analyzer mask_reversible поднимает RuntimeError."""
    tokenizer = PIITokenizer()
    with pytest.raises(RuntimeError, match="presidio_analyzer"):
        await tokenizer.mask_reversible(
            "Иванов И.И.", PIIPolicy(name="ru_strict_reversible")
        )


@pytest.mark.asyncio
async def test_unmask_with_empty_token_map_returns_input() -> None:
    """unmask с пустым TokenMap возвращает входной текст без изменений."""
    tokenizer = PIITokenizer()
    now = datetime.now(UTC)
    token_map = TokenMap(
        tokens={}, policy_name="ru_strict_reversible", created_at=now, ttl_s=3600
    )
    result = await tokenizer.unmask("<PERSON_a8f3> подал заявку", token_map)
    assert result == "<PERSON_a8f3> подал заявку"


def test_supported_entity_types_distinguishes_ru_en() -> None:
    """_supported_entity_types для ru включает банковские, en — нет."""
    tokenizer = PIITokenizer()
    ru_types = tokenizer._supported_entity_types("ru")
    en_types = tokenizer._supported_entity_types("en")
    assert "INN" in ru_types
    assert "SNILS" in ru_types
    assert "INN" not in en_types
    assert "PERSON" in ru_types
    assert "PERSON" in en_types
