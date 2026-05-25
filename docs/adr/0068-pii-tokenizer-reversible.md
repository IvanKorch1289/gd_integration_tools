# ADR-0068 — PIITokenizer — reversible PII tokenization layer

* Статус: **Accepted** (Sprint 25 W4, 2026-05-25)
* Закрыт: [wave:s25/w4-token-registry] + [wave:s25/w4-pii-tokenizer-impl] + [wave:s25/w4-roundtrip-gold-set] + [wave:s25/w4-di-composition] + [wave:s25/w4-closure]
* Связано с: `gap-analysis/AI-GAP-ANALYSIS-gd_integration_tools-2026-05-22.md` Зона 4 (PII reversible), PLAN.md V22.4 §S25, ADR-NEW-21.
* Память: [[feedback_wave_k1_security]], [[feedback_s1_security]].

## Контекст

Текущие PII-маскировщики:

1. `src/backend/core/security/pii_masker.py` — 8 regex-паттернов; **non-reversible** (заменяет на `***`).
2. `src/backend/dsl/engine/processors/mask_pii.py` — DSL-процессор использует `PIIMasker.mask()` (non-reversible).
3. `src/backend/services/ai/pii/retrieval_masker.py` — RAG retrieval masker (non-reversible, OFF default).
4. S24 W1 (планируется): Presidio + ru_core_news_lg + 4 custom recognizers.

**Не покрытый use-case**:
- Банковский сценарий: «LLM генерирует ответ клиенту Иванову И. И. по его договору № 12345» → требуется маскировка перед отправкой в SaaS LLM (OpenRouter/Anthropic), затем размаскировка ответа клиенту.
- Customer Service: «У клиента вопрос по карте 1234-5678-XXXX-XXXX → LLM формулирует ответ → размаскировка для отправки в чат».

Текущий `PIIMasker.mask()` не позволяет вернуться к оригиналу: `Иванов` → `***` (irreversible loss).

## Решение (Draft)

**`PIITokenizer`** — reversible PII-токенизатор поверх Presidio (из S24 W1).

### API

```python
class PIITokenizer:
    """Reversible PII tokenization.
    
    mask_reversible(text, policy) → (masked_text, token_map):
      "Иванов И.И., тел. +7-999-123-45-67, договор № 12345/CR-001"
      → ("<PERSON_a8f3>, тел. <PHONE_4b2c>, договор № <CONTRACT_d7e1>", token_map)
    
    unmask(masked_text, token_map) → original_text.
    
    mask_irreversible(text, policy) → masked_text:  # для audit/Langfuse traces
      → "<PERSON>, тел. <PHONE>, договор № <CONTRACT>"
    """
    async def mask_reversible(
        self, text: str, policy: PIIPolicy,
    ) -> tuple[str, TokenMap]: ...
    async def unmask(self, text: str, token_map: TokenMap) -> str: ...
    async def mask_irreversible(self, text: str, policy: PIIPolicy) -> str: ...

@dataclass(frozen=True, slots=True)
class TokenMap:
    """Mapping placeholder → original. AES-GCM encrypted at rest."""
    tokens: dict[str, EncryptedValue]   # "<PERSON_a8f3>" → AES-GCM(b"Иванов И.И.")
    policy_name: str
    created_at: datetime
    ttl_s: int
```

### TokenRegistry (Redis-backed)

```python
class TokenRegistry:
    """Persists TokenMap for unmask after LLM round-trip.
    
    Key:   "pii:token:{tenant_id}:{correlation_id}"
    Value: msgpack(TokenMap), AES-GCM-encrypted via core/secrets/.
    TTL:   policy.ttl_s (default 3600s).
    """
    async def store(self, correlation_id: str, token_map: TokenMap) -> None: ...
    async def fetch(self, correlation_id: str) -> TokenMap | None: ...
    async def delete(self, correlation_id: str) -> None: ...
```

### Capability

- `pii.tokenize.reversible.<scope>` — обязательна для workflow, которые делают unmask. `<scope>` = домен (banking, hr, medical).
- `pii.tokenize.irreversible.*` — разрешена по умолчанию (для audit-логов).

### DSL-интеграция (S27 W2)

```yaml
- pii_mask:
    fields: ["body.message"]
    policy: "ru_strict_reversible"
    store_tokens_in: body._pii_tokens   # token_map → correlation_id_redis_key

- ai_invoke: { prompt_ref: "credit_advisor.v2", input_var: body.message }

- pii_unmask:
    fields: ["body.completion"]
    tokens_from: body._pii_tokens
```

### Audit-event

Каждое `mask`/`unmask` эмитит:

```json
{
  "event_type": "ai.pii.tokenize.mask",
  "correlation_id": "abc-123",
  "tenant_id": "credit_premium",
  "policy_name": "ru_strict_reversible",
  "entities_detected": ["PERSON", "PHONE", "CONTRACT"],
  "tokens_created": 3
}
```

## Альтернативы (отвергнуто на этом этапе)

* **Format-preserving encryption** (FPE) — overkill для большинства случаев; добавляет тяжёлую зависимость (`pycryptodome` FPE-mode не нативен).
* **Differential privacy** — для статистики, не для inline-маскировки.
* **Hash-based** (SHA256 token → memoization) — не AES-GCM не закрывает компрометацию at-rest.
* **Полный отказ от reversible** — закрывает banking use-case ¬ user request.

## Открытые вопросы (решаются в wave S25 W4)

* **Encryption key rotation** — `infrastructure/secrets/vault.py` уже поддерживает rotation (S1.2). PIITokenizer использует static key или rotating?
* **TokenMap size** — long-context разговор с десятками PII токенов → Redis value размер? msgpack vs orjson?
* **Cross-session unmask** — token_map TTL = 1h по умолчанию. Что если LLM-ответ приходит через 2 часа (async batch)?
* **Tenant isolation** — encryption key per-tenant или global? per-tenant требует ключевого хранилища с rotation.
* **Memoization** — два одинаковых PII в одном запросе → одинаковый token? Это leak (correlate `<PERSON_a8f3>` появлений)?

## Зависимости

* `presidio-analyzer`, `presidio-anonymizer`, `spacy[ru_core_news_lg]` — приходят из S24 W1 ADR-NEW-16.
* `cryptography` (AES-GCM) — уже в стеке через `infrastructure/secrets/`.
* `msgpack` (или `orjson`) для TokenMap serialization — уже в стеке.
* Redis client — уже в стеке (`infrastructure/cache/redis_client.py`).
* `core/utils/task_registry.py` — для async cleanup expired token_maps.

## DoD-критерии Accepted (2026-05-25)

* [x] `core/security/pii_tokenizer.py::PIITokenizer` с lazy Presidio import — `[wave:s25/w4-pii-tokenizer-impl]`.
* [x] `infrastructure/security/token_registry.py::RedisTokenRegistry` Redis-backed (AES-256-GCM envelope, base64 orjson) — `[wave:s25/w4-token-registry]`.
* [x] `PIIPolicy` — `@dataclass(frozen, slots)` (Pydantic v2 не нужен — frozen dataclass без I/O; ADR-update reconcile).
* [x] Capability `pii.tokenize.reversible.<scope>` зарегистрирована в `capabilities/vocabulary.py` (S25 W4 backbone).
* [x] `tests/unit/core/security/test_pii_tokenizer_roundtrip.py` — 13 тестов, 500/500 mask→unmask exact-match — `[wave:s25/w4-roundtrip-gold-set]`.
* [x] AES-GCM at-rest verified: тест `test_encryption_at_rest_raw_bytes_differ_from_plaintext` (advisor recommendation) — встроен в `test_token_registry.py`.
* [x] `test_mask_irreversible_*` для audit/Langfuse — встроены в `test_pii_tokenizer_roundtrip.py`.
* [x] Audit-event `ai.pii.tokenize.{mask,unmask,store,retrieve,delete,decrypt_failed}` через `AuditService` (S17/K3).
* [x] DI provider `get_pii_tokenizer_provider` + lifespan cleanup loop — `[wave:s25/w4-di-composition]`.
* [ ] **Carry-over в S25 closure**: 3 PoC policies YAML (`ru_strict_reversible`, `ru_lite_irreversible`, `en_default`); Sphinx-страница "PII tokenization architecture"; per-tenant AES-GCM key через Vault rotation.

## Decisions (S25 W4, advisor 2026-05-25)

1. **EncryptedValue layout**: `ciphertext` + `tag` хранятся раздельно (split `AESGCM.encrypt(...)[:-16]`). Упрощает диагностику rotation и не требует concat-логики в callers.
2. **Key format**: `SecretsBackend.get_secret(...) → str (base64) → b64decode → 32 raw bytes`. Production через Vault KV v2; dev/staging через env `PII_AES_KEY_V{version}`.
3. **PIIPolicy форма**: `@dataclass(frozen, slots)` вместо Pydantic v2 — нет I/O-валидации, dataclass даёт frozen+slots без overhead'''а.
4. **retrieve(key) path**: реализован defensive — caller (DSL `pii_unmask` processor) появится в S27 W2; включён в W4 чтобы избежать parallel-PR с тестами.
5. **Placeholder rewrite**: Presidio выдаёт `[PERSON_1]` (sequential idx) → PIITokenizer переписывает на `<PERSON_{uuid7_short}>` через regex `_PRESIDIO_PLACEHOLDER_RE`. Не пытаемся форсить custom-формат через Presidio Anonymizer.
6. **UUIDv7 random tail**: первые 12 hex chars UUIDv7 — timestamp (collisions внутри одной ms); используем `hex[-8:]` (часть `random_b`, 32 bits) — гарантированная уникальность для 1000+ PII в одном тексте.
7. **Testkit sentinel**: при `token_registry=None` (unit-тесты без crypto-stack) PIITokenizer хранит `EncryptedValue(key_version=0, ciphertext=utf-8 bytes)`; `_decrypt` симметрично восстанавливает.

## Verification (post-Accepted gates)

| # | Команда | Результат |
|---|---------|-----------|
| 1 | `pytest tests/unit/infrastructure/security/test_token_registry.py -v` | 19/19 (0.26s) |
| 2 | `pytest tests/unit/core/security/test_pii_tokenizer_roundtrip.py -v` | 13/13, 500/500 exact-match |
| 3 | `pytest tests/unit/core/security/test_pii_tokenizer_scaffold.py -v` | 8/8 (regress) |
| 4 | `ruff check src/backend/core/security/pii_tokenizer.py src/backend/infrastructure/security/token_registry.py` | 0 violations |
| 5 | `mypy <new files>` | 0 issues |
| 6 | `grep -rn "NotImplementedError" src/backend/core/security/pii_tokenizer.py` | 0 matches |
| 7 | DI smoke: `get_pii_tokenizer_provider()` resolves через override-path | OK |
| 8 | setup_ai_2026 регистрирует `pii-tokenizer-cleanup` task под TaskRegistry | OK |

## Migration

* **Production-flip `ai_pii_tokenizer_enabled=True`**: после staging verify (500/500 round-trip + presidio_fallback_total == 0 в течение 24h) — carry-over в `[plan:v22.4/s27-closure]`.
* **Vault key provider**: `EnvAESGCMKeyProvider` → `VaultAESGCMKeyProvider` (через `SecretsBackend.get_secret("pii/aes/v1")`). Backward-compat: оба провайдера реализуют `AESGCMKeyProvider` Protocol.
* **DSL processors `pii_mask`/`pii_unmask` reversible**: S27 W2 переведёт legacy `MaskPiiProcessor` (regex-based) на `PIITokenizer` под тем же feature-flag.
* **AIGateway `_resolve_sanitizer`**: уже умеет switch на `feature_flags.ai_pii_tokenizer_enabled` (S25 W1 backbone) — после flip activates PIITokenizer вместо AIDataSanitizer.

## Связи с другими ADR

* **ADR-NEW-16 Presidio + ru NER** (S24 W1) — engine backend.
* **ADR-NEW-19 AIGateway** — потребитель в `_apply_sanitizers()`.
* **ADR-NEW-20 AIPolicySpec** — `SanitizerRef.name="pii_tokenizer:reversible:ru_strict"`.
* **ADR-NEW-24 AI Audit Unified** (S27 W5) — `ai.pii.*` события.
* **ADR-NEW-S22-followup Langfuse PII callback** (S25 W5) — использует `mask_irreversible()` перед отправкой в Langfuse SaaS.
* **S1 W3 ADR Vault rotation** — encryption key source.
