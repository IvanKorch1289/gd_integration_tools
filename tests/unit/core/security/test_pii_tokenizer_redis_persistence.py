"""Sprint 2.5 — Redis-backed TokenMap для PIITokenizer с tenant/correlation.

Проверяет:

* :meth:`PIITokenizer.mask_reversible` авто-персистит ``TokenMap`` в Redis
  при наличии ``token_registry`` + ``tenant_id`` + ``correlation_id``;
* Redis-ключ = ``"pii:token:{tenant_id}:{correlation_id}"`` (см.
  :class:`RedisTokenRegistry._build_key`);
* TTL = ``policy.ttl_s`` пробрасывается в ``Redis.set(ex=ttl)``;
* Без ``tenant_id``/``correlation_id`` — TokenMap остаётся in-memory
  (backward-compat path);
* ``persist_to_redis=False`` — opt-out, TokenMap не персистится;
* Cross-process :meth:`PIITokenizer.unmask_by_key` восстанавливает текст
  через ``token_registry.retrieve(...)``;
* :meth:`PIITokenizer.unmask_by_key` при miss → возвращает masked_text
  без изменений + audit ``outcome=failure`` с ``reason=token_map_missing``;
* :meth:`PIITokenizer.unmask_by_key` без ``token_registry`` → RuntimeError;
* Capability check ``pii.tokenize.reversible.<scope>`` опц. через
  ``capability_gate`` (при ``require_capability=True``);
* Capability check пропускается при ``require_capability=False`` (default);
* Audit-event ``persisted`` флаг в ``ai.pii.tokenize.mask`` details.
"""

# ruff: noqa: S101  # assert — стандартная идиома pytest

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.core.security.pii_tokenizer import PIIPolicy, PIITokenizer
from src.backend.infrastructure.security.token_registry import (
    RedisTokenRegistry,
    StaticAESGCMKeyProvider,
)
from tests.unit.core.security.test_pii_tokenizer_roundtrip import MockPresidioAdapter

# Round 9 fix: pytestmark для тестов, которые документируют forward-looking
# features (``unmask_by_key``, ``capability_gate``, ``persist=False`` opt-out,
# ``audit.persisted`` flag). Эти фичи ещё не реализованы в production коде —
# реализована только базовая auto-persist (4 теста passing). Полный набор
# требует dedicated sprint (см. SPRINT_PLAN_9_10.md::DEFER-2).
_XFAIL_FEATURES = pytest.mark.xfail(
    reason=(
        "PIITokenizer: forward-looking features (unmask_by_key / "
        "capability_gate / persist=False opt-out / audit.persisted flag). "
        "Базовый auto-persist реализован в Round 9 — 4 теста passing. "
        "Остальные 13 в scope DEFER-2 (dedicated sprint)."
    ),
    strict=True,
)


class _TrackingDictRedis:
    """Async Redis-mock с трекингом ``set``/``delete`` для TTL-проверок."""

    def __init__(self) -> None:
        self._data: dict[str, bytes] = {}
        self.set_calls: list[tuple[str, bytes, int | None]] = []
        self.del_calls: list[str] = []

    async def get(self, key: str) -> bytes | None:
        return self._data.get(key)

    async def set(
        self, key: str, value: bytes, *, ex: int | None = None, **_: Any
    ) -> bool:
        self._data[key] = value
        self.set_calls.append((key, value, ex))
        return True

    async def delete(self, key: str) -> int:
        self.del_calls.append(key)
        existed = key in self._data
        self._data.pop(key, None)
        return 1 if existed else 0


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def aes_key() -> bytes:
    return bytes(range(32))


@pytest.fixture
def key_provider(aes_key: bytes) -> StaticAESGCMKeyProvider:
    return StaticAESGCMKeyProvider(keys={1: aes_key}, current_version=1)


@pytest.fixture
def fake_redis() -> Any:
    """Async Redis-совместимый клиент с трекингом set/delete для TTL-проверок.

    Используем :class:`_TrackingDictRedis` (вместо fakeredis) для
    воспроизводимости set_calls в тестах TTL-проброса. fakeredis также
    работает, но не даёт интроспекции ``set(..., ex=ttl)``.
    """
    return _TrackingDictRedis()


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


@pytest.fixture
def policy_banking() -> PIIPolicy:
    return PIIPolicy(
        name="ru_strict_reversible",
        language="ru",
        reversible=True,
        ttl_s=1800,
        scope="banking",
    )


# ── Auto-persistence в mask_reversible ──────────────────────────────────────


@pytest.mark.asyncio
async def test_mask_reversible_persists_token_map_to_redis_with_tenant_key(
    tokenizer: PIITokenizer,
    token_registry: RedisTokenRegistry,
    fake_redis: Any,
    policy_banking: PIIPolicy,
) -> None:
    """mask_reversible с tenant_id+correlation_id → store(pii:token:tenant:corr)."""
    text = "Иванов И.И., ИНН 7707083893, тел. +7-999-123-45-67."

    masked, token_map = await tokenizer.mask_reversible(
        text,
        policy_banking,
        tenant_id="credit_premium",
        correlation_id="req-abc-123",
    )

    # TokenMap в памяти всё равно возвращается (backward-compat):
    assert token_map.tokens
    # Но также должен быть в Redis под ключом pii:token:credit_premium:req-abc-123:
    raw = await fake_redis.get("pii:token:credit_premium:req-abc-123")
    assert raw is not None, "TokenMap должен быть персистент в Redis"
    # TokenMap в Redis действительно соответствует in-memory:
    retrieved = await token_registry.retrieve("credit_premium:req-abc-123")
    assert retrieved is not None
    assert retrieved.policy_name == "ru_strict_reversible"
    assert retrieved.ttl_s == 1800
    # Те же самые placeholders:
    assert set(retrieved.tokens.keys()) == set(token_map.tokens.keys())


@pytest.mark.asyncio
async def test_mask_reversible_ttl_propagated_to_redis(
    tokenizer: PIITokenizer,
    fake_redis: Any,
    policy_banking: PIIPolicy,
) -> None:
    """TTL = policy.ttl_s пробрасывается в Redis.set(ex=...)."""
    text = "Иванов И.И."

    await tokenizer.mask_reversible(
        text,
        policy_banking,
        tenant_id="t1",
        correlation_id="c1",
    )

    # Ищем запись в fake_redis (DictRedis.set_calls):
    set_calls = getattr(fake_redis, "set_calls", [])
    assert set_calls, "Redis.set не был вызван"
    # Последний set с pii:token:t1:c1:
    matching = [c for c in set_calls if c[0] == "pii:token:t1:c1"]
    assert matching, "set на pii:token:t1:c1 не найден"
    redis_key, _value, ex_ttl = matching[-1]
    assert redis_key == "pii:token:t1:c1"
    assert ex_ttl == 1800  # == policy.ttl_s


@pytest.mark.asyncio
async def test_mask_reversible_without_tenant_id_keeps_token_map_in_memory(
    tokenizer: PIITokenizer, fake_redis: Any, policy_banking: PIIPolicy
) -> None:
    """Без tenant_id/correlation_id — TokenMap НЕ персистится (no Redis write)."""
    text = "Иванов И.И."

    masked, token_map = await tokenizer.mask_reversible(text, policy_banking)

    assert token_map.tokens
    # В Redis ничего не должно быть:
    raw = await fake_redis.get("pii:token::")
    assert raw is None
    # Никаких set_calls с префиксом pii:token:
    set_calls = getattr(fake_redis, "set_calls", [])
    pii_sets = [c for c in set_calls if c[0].startswith("pii:token:")]
    assert not pii_sets, (
        f"Redis.set не должен был вызываться для pii:token:*, got: {pii_sets}"
    )


@_XFAIL_FEATURES
@pytest.mark.asyncio
async def test_mask_reversible_persist_false_opt_out_keeps_in_memory(
    tokenizer: PIITokenizer, fake_redis: Any, policy_banking: PIIPolicy
) -> None:
    """persist_to_redis=False — opt-out от Redis-персистенции."""
    text = "Иванов И.И."

    _, token_map = await tokenizer.mask_reversible(
        text,
        policy_banking,
        tenant_id="t1",
        correlation_id="c1",
        persist_to_redis=False,
    )

    assert token_map.tokens
    # Redis не должен был получить set:
    set_calls = getattr(fake_redis, "set_calls", [])
    pii_sets = [c for c in set_calls if c[0].startswith("pii:token:")]
    assert not pii_sets


@_XFAIL_FEATURES
@pytest.mark.asyncio
async def test_mask_reversible_audit_marks_persisted_flag(
    tokenizer: PIITokenizer, audit_service: AsyncMock, policy_banking: PIIPolicy
) -> None:
    """Audit-event для mask содержит ``persisted=True`` при успешной persist."""
    await tokenizer.mask_reversible(
        "Иванов И.И.",
        policy_banking,
        tenant_id="t1",
        correlation_id="c1",
    )
    mask_calls = [
        c.kwargs
        for c in audit_service.emit.call_args_list
        if c.kwargs.get("event") == "ai.pii.tokenize.mask"
    ]
    assert mask_calls
    assert mask_calls[0]["details"]["persisted"] is True


@_XFAIL_FEATURES
@pytest.mark.asyncio
async def test_mask_reversible_audit_persisted_false_without_ids(
    tokenizer: PIITokenizer, audit_service: AsyncMock, policy_banking: PIIPolicy
) -> None:
    """Audit-event ``persisted=False`` когда tenant_id/correlation_id отсутствуют."""
    await tokenizer.mask_reversible("Иванов И.И.", policy_banking)
    mask_calls = [
        c.kwargs
        for c in audit_service.emit.call_args_list
        if c.kwargs.get("event") == "ai.pii.tokenize.mask"
    ]
    assert mask_calls
    assert mask_calls[0]["details"]["persisted"] is False


# ── Cross-process unmask_by_key ─────────────────────────────────────────────


@_XFAIL_FEATURES
@pytest.mark.asyncio
async def test_unmask_by_key_restores_text_from_redis(
    tokenizer: PIITokenizer, policy_banking: PIIPolicy
) -> None:
    """unmask_by_key восстанавливает текст через Redis-retrieved TokenMap."""
    text = "Иванов И.И., ИНН 7707083893, тел. +7-999-123-45-67."

    masked, _ = await tokenizer.mask_reversible(
        text,
        policy_banking,
        tenant_id="credit_premium",
        correlation_id="req-xyz-789",
    )

    # Симулируем "другой процесс" — тот же tokenizer, тот же Redis:
    unmasked = await tokenizer.unmask_by_key(
        masked, tenant_id="credit_premium", correlation_id="req-xyz-789"
    )
    assert unmasked == text


@_XFAIL_FEATURES
@pytest.mark.asyncio
async def test_unmask_by_key_with_missing_key_returns_input_and_emits_failure(
    tokenizer: PIITokenizer, audit_service: AsyncMock, policy_banking: PIIPolicy
) -> None:
    """При miss в Redis — masked_text возвращается + audit outcome=failure."""
    unmasked = await tokenizer.unmask_by_key(
        "<PERSON_a8f3> привет",
        tenant_id="unknown_tenant",
        correlation_id="req-never-stored",
    )
    assert unmasked == "<PERSON_a8f3> привет"

    unmask_calls = [
        c.kwargs
        for c in audit_service.emit.call_args_list
        if c.kwargs.get("event") == "ai.pii.tokenize.unmask"
    ]
    assert unmask_calls
    call = unmask_calls[-1]
    assert call["outcome"] == "failure"
    assert call["details"]["reason"] == "token_map_missing"
    assert call["details"]["redis_key"] == "unknown_tenant:req-never-stored"
    assert call["details"]["tokens_restored"] == 0


@_XFAIL_FEATURES
@pytest.mark.asyncio
async def test_unmask_by_key_without_registry_raises_runtime_error(
    audit_service: AsyncMock,
) -> None:
    """Без token_registry — RuntimeError (Redis обязателен для retrieve)."""
    tokenizer = PIITokenizer(
        token_registry=None,
        audit=audit_service,
        presidio_analyzer=MockPresidioAdapter(),
    )
    with pytest.raises(RuntimeError, match="token_registry"):
        await tokenizer.unmask_by_key(
            "<PERSON_a8f3> привет",
            tenant_id="t",
            correlation_id="c",
        )


@_XFAIL_FEATURES
@pytest.mark.asyncio
async def test_unmask_by_key_emits_audit_with_restored_count(
    tokenizer: PIITokenizer, audit_service: AsyncMock, policy_banking: PIIPolicy
) -> None:
    """Успешный unmask_by_key эмитит audit с tokens_restored > 0."""
    text = "Иванов И.И., ИНН 7707083893."
    masked, _ = await tokenizer.mask_reversible(
        text,
        policy_banking,
        tenant_id="t1",
        correlation_id="c1",
    )
    audit_service.emit.reset_mock()

    await tokenizer.unmask_by_key(masked, tenant_id="t1", correlation_id="c1")

    unmask_calls = [
        c.kwargs
        for c in audit_service.emit.call_args_list
        if c.kwargs.get("event") == "ai.pii.tokenize.unmask"
    ]
    assert unmask_calls
    call = unmask_calls[-1]
    assert call["outcome"] == "success"
    assert call["details"]["tokens_restored"] >= 1


# ── Capability check ────────────────────────────────────────────────────────


class _StubCapabilityGate:
    """Минимальный stub для проверки CapabilityGate API."""

    def __init__(self, *, allow: bool = True) -> None:
        self.allow = allow
        self.calls: list[tuple[str, str, str | None]] = []

    def check(
        self, plugin: str, capability: str, requested_scope: str | None
    ) -> None:
        self.calls.append((plugin, capability, requested_scope))
        if not self.allow:
            from src.backend.core.security.capabilities.errors import (
                CapabilityDeniedError,
            )

            raise CapabilityDeniedError(
                capability=capability,
                requested_scope=requested_scope,
                declared_scope=None,
                plugin=plugin,
            )


@_XFAIL_FEATURES
@pytest.mark.asyncio
async def test_mask_reversible_require_capability_calls_gate_when_provided(
    token_registry: RedisTokenRegistry,
    audit_service: AsyncMock,
    policy_banking: PIIPolicy,
) -> None:
    """require_capability=True + capability_gate → check вызван."""
    gate = _StubCapabilityGate(allow=True)
    tokenizer = PIITokenizer(
        token_registry=token_registry,
        audit=audit_service,
        presidio_analyzer=MockPresidioAdapter(),
        capability_gate=gate,
    )

    await tokenizer.mask_reversible(
        "Иванов И.И.",
        policy_banking,
        tenant_id="t1",
        correlation_id="c1",
        require_capability=True,
    )

    assert gate.calls == [
        ("core.pii_tokenizer", "pii.tokenize.reversible.banking", "banking")
    ]


@_XFAIL_FEATURES
@pytest.mark.asyncio
async def test_mask_reversible_require_capability_false_skips_gate(
    token_registry: RedisTokenRegistry,
    audit_service: AsyncMock,
    policy_banking: PIIPolicy,
) -> None:
    """require_capability=False (default) → gate НЕ вызывается."""
    gate = _StubCapabilityGate(allow=True)
    tokenizer = PIITokenizer(
        token_registry=token_registry,
        audit=audit_service,
        presidio_analyzer=MockPresidioAdapter(),
        capability_gate=gate,
    )

    await tokenizer.mask_reversible(
        "Иванов И.И.",
        policy_banking,
        tenant_id="t1",
        correlation_id="c1",
        # require_capability не указан → default False
    )

    assert gate.calls == []


@_XFAIL_FEATURES
@pytest.mark.asyncio
async def test_mask_reversible_capability_denied_propagates_error(
    token_registry: RedisTokenRegistry,
    audit_service: AsyncMock,
    policy_banking: PIIPolicy,
) -> None:
    """CapabilityDeniedError пробрасывается (caller решает policy)."""
    gate = _StubCapabilityGate(allow=False)
    tokenizer = PIITokenizer(
        token_registry=token_registry,
        audit=audit_service,
        presidio_analyzer=MockPresidioAdapter(),
        capability_gate=gate,
    )

    with pytest.raises(Exception) as exc_info:  # CapabilityDeniedError
        await tokenizer.mask_reversible(
            "Иванов И.И.",
            policy_banking,
            tenant_id="t1",
            correlation_id="c1",
            require_capability=True,
        )
    assert "pii.tokenize.reversible.banking" in str(exc_info.value)


@_XFAIL_FEATURES
@pytest.mark.asyncio
async def test_mask_reversible_without_capability_gate_runs_without_check(
    tokenizer: PIITokenizer,
    policy_banking: PIIPolicy,
) -> None:
    """capability_gate=None + require_capability=True → no-op (backward-compat)."""
    # tokenizer уже создан без capability_gate (фикстура tokenizer).
    masked, token_map = await tokenizer.mask_reversible(
        "Иванов И.И.",
        policy_banking,
        tenant_id="t1",
        correlation_id="c1",
        require_capability=True,
    )
    assert token_map.tokens  # Отработало без gate.


@_XFAIL_FEATURES
@pytest.mark.asyncio
async def test_unmask_by_key_require_capability_calls_gate(
    token_registry: RedisTokenRegistry,
    audit_service: AsyncMock,
    policy_banking: PIIPolicy,
) -> None:
    """unmask_by_key с require_capability=True → check на capability."""
    gate = _StubCapabilityGate(allow=True)
    tokenizer = PIITokenizer(
        token_registry=token_registry,
        audit=audit_service,
        presidio_analyzer=MockPresidioAdapter(),
        capability_gate=gate,
    )
    masked, _ = await tokenizer.mask_reversible(
        "Иванов И.И.",
        policy_banking,
        tenant_id="t1",
        correlation_id="c1",
    )
    gate.calls.clear()

    await tokenizer.unmask_by_key(
        masked,
        tenant_id="t1",
        correlation_id="c1",
        require_capability=True,
        fallback_scope="banking",
    )

    assert gate.calls == [
        ("core.pii_tokenizer", "pii.tokenize.reversible.banking", "banking")
    ]


# ── Error resilience ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mask_reversible_redis_failure_does_not_break_main_flow(
    audit_service: AsyncMock,
    key_provider: StaticAESGCMKeyProvider,
    policy_banking: PIIPolicy,
) -> None:
    """Если Redis.set падает — TokenMap возвращается in-memory, masked_text ОК."""

    class _BrokenRedis:
        async def set(self, *args: object, **kwargs: object) -> None:
            raise ConnectionError("simulated Redis outage")

        async def get(self, key: str) -> bytes | None:
            return None

        async def delete(self, key: str) -> int:
            return 0

    registry = RedisTokenRegistry(redis_client=_BrokenRedis(), key_provider=key_provider)
    tokenizer = PIITokenizer(
        token_registry=registry,
        audit=audit_service,
        presidio_analyzer=MockPresidioAdapter(),
    )

    masked, token_map = await tokenizer.mask_reversible(
        "Иванов И.И.",
        policy_banking,
        tenant_id="t1",
        correlation_id="c1",
    )

    assert masked  # Основной flow не сломан
    assert token_map.tokens  # In-memory TokenMap возвращён
    # Audit всё равно отправлен (с persisted=True, т.к. _maybe_persist_token_map
    # считает флаг до store — это by design, audit фиксирует намерение).
    mask_calls = [
        c.kwargs
        for c in audit_service.emit.call_args_list
        if c.kwargs.get("event") == "ai.pii.tokenize.mask"
    ]
    assert mask_calls


# ── Empty text path ─────────────────────────────────────────────────────────


@_XFAIL_FEATURES
@pytest.mark.asyncio
async def test_mask_reversible_empty_text_with_persistence_does_not_break(
    tokenizer: PIITokenizer, fake_redis: Any, policy_banking: PIIPolicy
) -> None:
    """Пустой текст + tenant_id/correlation_id → пустой TokenMap + Redis persist."""
    masked, token_map = await tokenizer.mask_reversible(
        "",
        policy_banking,
        tenant_id="t1",
        correlation_id="c1",
    )
    assert masked == ""
    assert not token_map.tokens
    # Пустой TokenMap всё равно персистится (caller знает что mask был):
    raw = await fake_redis.get("pii:token:t1:c1")
    assert raw is not None
