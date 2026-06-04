"""Round-trip тесты :class:`PIITokenizer` на gold-set 500 ru-банковских docs.

Sprint 25 W4 / ADR-NEW-21 / ADR-0068.

Тестируется:

* ``mask_reversible`` → ``unmask`` round-trip: 500/500 exact-match;
* ``mask_irreversible``: generic placeholders ``<PERSON>``, ``<INN>``;
* audit-emit для ``ai.pii.tokenize.{mask,unmask}``;
* capability check — optional (W4 не выполняет gate; интеграция с
  ``CapabilityGate`` — carry-over в S25 closure);
* cleanup_expired delegate в ``token_registry``.

Mock Presidio
-------------
:class:`MockPresidioAdapter` — regex-based детектор PII (без spaCy/Presidio
runtime). Покрывает 5 типов ``(PERSON, INN, SNILS, PHONE_NUMBER, CONTRACT)``,
которые есть во всех docs gold-set'а. Использует тот же placeholder-формат
``[TYPE_N]``, что и реальный :class:`PresidioSanitizerAdapter`.
"""

# ruff: noqa: S101  # assert — стандартная идиома pytest

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.core.interfaces.sanitization import SanitizationResult
from src.backend.core.security.pii_tokenizer import (
    EncryptedValue,
    PIIPolicy,
    PIITokenizer,
    TokenMap,
)
from src.backend.infrastructure.security.token_registry import (
    RedisTokenRegistry,
    StaticAESGCMKeyProvider,
)
from tests.fixtures.pii_gold_set.builder import GoldSetDoc, build_reversible_gold_set

# ── Mock Presidio ──────────────────────────────────────────────────────────


class MockPresidioAdapter:
    """Regex-based PII detector — drop-in для ``PresidioSanitizerAdapter``.

    Эмулирует :meth:`sanitize_async` API. Placeholders формата ``[TYPE_N]``
    (порядок idx — по позиции в тексте; не пересекающиеся spans).
    """

    _PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
        # Порядок важен: CONTRACT/PHONE сначала, чтобы их цифры не схватил INN.
        ("CONTRACT", re.compile(r"\d{4,5}/[A-Z]{2}-\d{3}")),
        ("PHONE_NUMBER", re.compile(r"\+7-\d{3}-\d{3}-\d{2}-\d{2}")),
        ("SNILS", re.compile(r"\d{3}-\d{3}-\d{3} \d{2}")),
        ("INN", re.compile(r"\b\d{10}\b|\b\d{12}\b")),
        ("PERSON", re.compile(r"[А-Я][а-я]+ [А-Я]\.[А-Я]\.")),
    )

    async def sanitize_async(
        self, text: str, *, language: str | None = None
    ) -> SanitizationResult:
        del language
        spans: list[tuple[int, int, str, str]] = []
        for entity_type, pattern in self._PATTERNS:
            for m in pattern.finditer(text):
                start, end = m.start(), m.end()
                # Skip overlap with уже найденными spans (приоритет — порядок _PATTERNS).
                if any(not (end <= s or start >= e) for s, e, _, _ in spans):
                    continue
                spans.append((start, end, entity_type, m.group()))

        # idx — по позиции в тексте (ascending start).
        spans.sort(key=lambda x: x[0])
        placeholders: list[tuple[int, int, str, str]] = [
            (start, end, f"[{etype}_{idx}]", original)
            for idx, (start, end, etype, original) in enumerate(spans, start=1)
        ]

        # Replace from end to start, чтобы не сдвинуть индексы.
        replacements: dict[str, str] = {}
        result = text
        for start, end, placeholder, original in sorted(
            placeholders, key=lambda x: -x[0]
        ):
            result = result[:start] + placeholder + result[end:]
            replacements[placeholder] = original

        return SanitizationResult(sanitized_text=result, replacements=replacements)


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def aes_key() -> bytes:
    return bytes(range(32))


@pytest.fixture
def key_provider(aes_key: bytes) -> StaticAESGCMKeyProvider:
    return StaticAESGCMKeyProvider(keys={1: aes_key}, current_version=1)


@pytest.fixture
def fake_redis() -> Any:
    try:
        import fakeredis.aioredis as far  # noqa: PLC0415

        return far.FakeRedis()
    except ImportError:
        return _DictRedis()


class _DictRedis:
    def __init__(self) -> None:
        self._data: dict[str, bytes] = {}

    async def get(self, key: str) -> bytes | None:
        return self._data.get(key)

    async def set(
        self, key: str, value: bytes, *, ex: int | None = None, **_: Any
    ) -> bool:
        del ex
        self._data[key] = value
        return True

    async def delete(self, key: str) -> int:
        existed = key in self._data
        self._data.pop(key, None)
        return 1 if existed else 0


@pytest.fixture
def token_registry(
    fake_redis: Any, key_provider: StaticAESGCMKeyProvider
) -> RedisTokenRegistry:
    return RedisTokenRegistry(redis_client=fake_redis, key_provider=key_provider)


@pytest.fixture
def audit_service() -> AsyncMock:
    mock = AsyncMock()
    mock.emit = AsyncMock(return_value=None)
    return mock


@pytest.fixture
def tokenizer(
    token_registry: RedisTokenRegistry, audit_service: AsyncMock
) -> PIITokenizer:
    return PIITokenizer(
        token_registry=token_registry,
        audit=audit_service,
        presidio_analyzer=MockPresidioAdapter(),
    )


@pytest.fixture(scope="session")
def gold_set() -> list[GoldSetDoc]:
    docs = build_reversible_gold_set(n=500)
    assert len(docs) == 500, f"gold-set должен содержать 500 docs, got {len(docs)}"
    return docs


@pytest.fixture
def policy_ru_strict() -> PIIPolicy:
    return PIIPolicy(
        name="ru_strict_reversible",
        language="ru",
        reversible=True,
        ttl_s=3600,
        scope="banking",
    )


# ── Round-trip: 500/500 exact-match ───────────────────────────────────────


@pytest.mark.asyncio
async def test_roundtrip_500_docs_exact_match(
    tokenizer: PIITokenizer, gold_set: list[GoldSetDoc], policy_ru_strict: PIIPolicy
) -> None:
    """mask_reversible → unmask = original (500/500 docs)."""
    fail_ids: list[str] = []
    for doc in gold_set:
        masked, token_map = await tokenizer.mask_reversible(
            doc["text"], policy_ru_strict
        )
        assert masked != doc["text"], (
            f"{doc['id']}: masked == original (PII не детектирован)"
        )
        assert token_map.tokens, f"{doc['id']}: TokenMap пуст"

        unmasked = await tokenizer.unmask(masked, token_map)
        if unmasked != doc["text"]:
            fail_ids.append(doc["id"])

    assert not fail_ids, (
        f"Round-trip exact-match failed for {len(fail_ids)} docs: {fail_ids[:5]}..."
    )


@pytest.mark.asyncio
async def test_roundtrip_detects_all_expected_entities(
    tokenizer: PIITokenizer, gold_set: list[GoldSetDoc], policy_ru_strict: PIIPolicy
) -> None:
    """Все expected_entities из gold-set присутствуют в TokenMap."""
    fail_ids: list[str] = []
    for doc in gold_set:
        _, token_map = await tokenizer.mask_reversible(doc["text"], policy_ru_strict)
        # Извлекаем entity types из placeholders <TYPE_uuid>:
        detected = {
            placeholder.strip("<>").rsplit("_", 1)[0]
            for placeholder in token_map.tokens
        }
        expected = set(doc["expected_entities"])
        if not expected.issubset(detected):
            fail_ids.append(f"{doc['id']} missing={expected - detected}")
    assert not fail_ids, f"Missing entities in {len(fail_ids)} docs: {fail_ids[:5]}"


# ── Mask reversible — точечные проверки ───────────────────────────────────


@pytest.mark.asyncio
async def test_mask_reversible_returns_unique_placeholders(
    tokenizer: PIITokenizer, policy_ru_strict: PIIPolicy
) -> None:
    """Каждый placeholder уникален (UUIDv7-short suffix)."""
    text = (
        "Иванов И.И., ИНН 7707083893, тел. +7-999-123-45-67, договор № 12345/CR-001. "
        "Сидоров В.К., ИНН 5260270518, тел. +7-495-987-65-43, договор № 67890/DV-002."
    )
    _, token_map = await tokenizer.mask_reversible(text, policy_ru_strict)
    placeholders = list(token_map.tokens.keys())
    assert len(placeholders) == len(set(placeholders)), (
        "placeholders должны быть unique"
    )
    # 2 PERSON + 2 INN + 2 PHONE + 2 CONTRACT = 8 entities:
    assert len(placeholders) == 8


@pytest.mark.asyncio
async def test_mask_reversible_placeholders_use_angle_brackets(
    tokenizer: PIITokenizer, policy_ru_strict: PIIPolicy
) -> None:
    """Final placeholders формата ``<TYPE_uuid>`` (не Presidio ``[TYPE_N]``)."""
    text = "Иванов И.И., ИНН 7707083893."
    masked, token_map = await tokenizer.mask_reversible(text, policy_ru_strict)
    assert "[PERSON_" not in masked, "Presidio placeholder не должен утечь в masked"
    assert "[INN_" not in masked
    assert all(p.startswith("<") and p.endswith(">") for p in token_map.tokens)


@pytest.mark.asyncio
async def test_mask_reversible_emits_audit_with_entity_types(
    tokenizer: PIITokenizer, audit_service: AsyncMock, policy_ru_strict: PIIPolicy
) -> None:
    """audit.emit для mask содержит entity_types + token_count + scope."""
    text = "Иванов И.И., ИНН 7707083893, тел. +7-999-123-45-67."
    await tokenizer.mask_reversible(text, policy_ru_strict)
    mask_calls = [
        c.kwargs
        for c in audit_service.emit.call_args_list
        if c.kwargs.get("event") == "ai.pii.tokenize.mask"
    ]
    assert mask_calls
    call = mask_calls[0]
    assert call["outcome"] == "success"
    assert call["details"]["scope"] == "banking"
    assert call["details"]["policy_name"] == "ru_strict_reversible"
    assert call["details"]["reversible"] is True
    assert "PERSON" in call["details"]["entity_types"]
    assert "INN" in call["details"]["entity_types"]
    assert call["details"]["token_count"] == 3


@pytest.mark.asyncio
async def test_mask_reversible_empty_text_short_circuits(
    tokenizer: PIITokenizer, policy_ru_strict: PIIPolicy
) -> None:
    """Пустой текст → возврат как есть + пустой TokenMap."""
    masked, token_map = await tokenizer.mask_reversible("", policy_ru_strict)
    assert masked == ""
    assert not token_map.tokens


# ── Unmask ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unmask_emits_audit_with_tokens_restored(
    tokenizer: PIITokenizer, audit_service: AsyncMock, policy_ru_strict: PIIPolicy
) -> None:
    """audit.emit для unmask содержит tokens_restored."""
    text = "Иванов И.И. подал заявку."
    masked, token_map = await tokenizer.mask_reversible(text, policy_ru_strict)
    await tokenizer.unmask(masked, token_map)
    unmask_calls = [
        c.kwargs
        for c in audit_service.emit.call_args_list
        if c.kwargs.get("event") == "ai.pii.tokenize.unmask"
    ]
    assert unmask_calls
    call = unmask_calls[0]
    assert call["outcome"] == "success"
    assert call["details"]["tokens_restored"] == 1
    assert call["details"]["tokens_failed"] == 0


@pytest.mark.asyncio
async def test_unmask_partial_failure_keeps_placeholder_and_emits_failure(
    tokenizer: PIITokenizer, audit_service: AsyncMock
) -> None:
    """Если decrypt fail для одного placeholder — он остаётся, audit=failure."""
    bad_value = EncryptedValue(
        ciphertext=b"\x00" * 16, nonce=b"\x00" * 12, tag=b"\x00" * 16, key_version=99
    )
    token_map = TokenMap(
        tokens={"<PERSON_xxxx>": bad_value},
        policy_name="ru_strict_reversible",
        created_at=datetime.now(UTC),
        ttl_s=3600,
    )
    result = await tokenizer.unmask("Привет, <PERSON_xxxx>!", token_map)
    assert "<PERSON_xxxx>" in result  # decrypt failed → placeholder остался
    unmask_calls = [
        c.kwargs
        for c in audit_service.emit.call_args_list
        if c.kwargs.get("event") == "ai.pii.tokenize.unmask"
    ]
    assert unmask_calls
    assert unmask_calls[0]["outcome"] == "failure"
    assert unmask_calls[0]["details"]["tokens_failed"] == 1


# ── Mask irreversible ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mask_irreversible_generic_placeholders(
    tokenizer: PIITokenizer, policy_ru_strict: PIIPolicy
) -> None:
    """mask_irreversible использует generic ``<TYPE>`` без uniqueness."""
    text = "Иванов И.И., ИНН 7707083893."
    masked = await tokenizer.mask_irreversible(text, policy_ru_strict)
    assert "Иванов" not in masked
    assert "7707083893" not in masked
    assert "<PERSON>" in masked
    assert "<INN>" in masked
    # Никаких unique-токенов:
    assert "<PERSON_" not in masked
    assert "[PERSON_" not in masked


@pytest.mark.asyncio
async def test_mask_irreversible_emits_audit_with_reversible_false(
    tokenizer: PIITokenizer, audit_service: AsyncMock, policy_ru_strict: PIIPolicy
) -> None:
    """audit.emit для mask_irreversible имеет ``reversible: False``."""
    await tokenizer.mask_irreversible("Иванов И.И.", policy_ru_strict)
    mask_calls = [
        c.kwargs
        for c in audit_service.emit.call_args_list
        if c.kwargs.get("event") == "ai.pii.tokenize.mask"
    ]
    assert mask_calls
    assert mask_calls[0]["details"]["reversible"] is False


# ── cleanup_expired ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cleanup_expired_delegates_to_registry(
    tokenizer: PIITokenizer,
    token_registry: RedisTokenRegistry,
    policy_ru_strict: PIIPolicy,
) -> None:
    """cleanup_expired возвращает число живых ключей в registry."""
    text = "Иванов И.И."
    _, tm = await tokenizer.mask_reversible(text, policy_ru_strict)
    await token_registry.store("corr-1", tm, ttl_s=60)
    await token_registry.store("corr-2", tm, ttl_s=60)

    count = await tokenizer.cleanup_expired(ttl_s=0)
    assert count == 2


@pytest.mark.asyncio
async def test_cleanup_expired_without_registry_returns_zero() -> None:
    """Без token_registry — cleanup возвращает 0 (no-op)."""
    tokenizer = PIITokenizer()
    assert await tokenizer.cleanup_expired(ttl_s=0) == 0


# ── Testkit path (без registry) ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_testkit_path_mask_unmask_without_registry(
    policy_ru_strict: PIIPolicy,
) -> None:
    """Без token_registry — sentinel EncryptedValue, round-trip работает."""
    tokenizer = PIITokenizer(presidio_analyzer=MockPresidioAdapter())
    text = "Иванов И.И., ИНН 7707083893."

    masked, token_map = await tokenizer.mask_reversible(text, policy_ru_strict)
    assert masked != text
    assert all(ev.key_version == 0 for ev in token_map.tokens.values())

    unmasked = await tokenizer.unmask(masked, token_map)
    assert unmasked == text
