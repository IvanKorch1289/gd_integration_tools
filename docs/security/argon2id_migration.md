# API Key Hashing & Argon2id Migration (S172 M2 — ARC-004)

**Status**: SHIPPED 2026-06-30. **Breaking change risk**: Low (backward-compat
через dual-verify).

## TL;DR

API keys теперь хешируются через **Argon2id** с per-key salt (OWASP 2026
baseline: `time_cost=2`, `memory_cost=64MiB`, `parallelism=2`). Старые
**SHA-256** хеши продолжают приниматься для backward-compat через dual-verify
path — пока migration script не прогонится через все stored keys.

## Files

| Path | LOC | Назначение |
|---|---|---|
| `src/backend/core/auth/api_key_backend.py` | 178 | `APIKeyAuth` — Argon2id primary + SHA-256 fallback |
| `src/backend/infrastructure/security/api_key_manager.py` | 240+ | Redis storage, validate/create/rotate, `upgrade_to_argon2()` |
| `tools/migrations/migrate_api_keys_to_argon2.py` | 320 | Standalone migration CLI |
| `tests/unit/core/auth/test_api_key_backend.py` | 20 | Tests for `APIKeyAuth` (Argon2 + SHA dual-verify) |
| `tests/unit/integration/test_api_key_argon2_migration.py` | 10 | WS facade + manager integration tests |
| `tests/unit/tools/test_migrate_api_keys_to_argon2.py` | 14 | Migration CLI / per-key process-one logic tests |
| `tests/unit/tools/test_migrate_api_keys_to_argon2_smoke.py` | 8 | Smoke tests for CLI behavior без live Redis |

## Architecture

```
                    ┌──────────────────────────────────────────┐
                    │ APIKeyAuth.verify(raw, expected_hash)    │
                    ├──────────────────────────────────────────┤
   raw key ───►     │ if is_argon2_hash(expected_hash):        │
                    │     argon2.PasswordHasher.verify()       │  ◄── OWASP 2026 baseline
                    │     → match → return True                 │
                    │     → mismatch → return False             │
                    │     → InvalidHash → log+False             │
                    │ elif allow_legacy_sha256:                  │
                    │     hmac.compare_digest(sha256(raw),      │  ◄── S-7 legacy
                    │                          expected_hash)   │
                    │ else: return False                         │
                    └──────────────────────────────────────────┘
                                       ▲
                                       │ (PHC string)
                                       │
              ┌────────────────────────┴──────────────────────────┐
              │ APIKeyManager                                   │
              │  • create_client_key() → Argon2 hash, store in  │
              │    Redis как {"hash_algo": "argon2id", ...}     │
              │  • validate_key() → через APIKeyAuth.verify     │
              │  • upgrade_to_argon2() → one-shot SHA→Argon2    │
              │  • rotate_client_key() → новый Argon2 + grace   │
              └──────────────────────────────────────────────────┘
                                       ▲
                                       │
                              Redis (apikey:*)
```

## Production rollout

1. **Deploy** Sprint 172 (этот релиз).
   * Новые ключи создаются через Argon2id → stored как PHC string.
   * Старые ключи (до deploy) продолжают работать (dual-verify).
2. **Run dry-run** скрипта — собираем список candidates:

   ```bash
   python tools/migrations/migrate_api_keys_to_argon2.py \
       --redis-url $REDIS_URL \
       --keys-file raw-keys.txt \
       --dry-run \
       --stats-out stats.json
   ```

   Вывод: `{"scanned": N, "upgraded": M, "skipped_already_argon2": K, ...}`.
3. **Собрать `raw-keys.txt`** (формат `client_id:raw_key`, по строке на ключ).
   Источники: secrets manager (Vault), env-файлы сервисов, dev-storage.
4. **Apply** скрипт:

   ```bash
   python tools/migrations/migrate_api_keys_to_argon2.py \
       --redis-url $REDIS_URL \
       --keys-file raw-keys.txt \
       --confirm \
       --max-failures 10 \
       --stats-out stats.json
   ```

   Скрипт идёт через все `apikey:*` ключи в Redis. Для каждого:
   * Если hash уже Argon2 — skip.
   * Если hash SHA-256 + raw key in `raw-keys.txt` → verify → rehash → write.
   * Audit event `upgrade` в `apikey_audit:events` Redis stream.
   * Если verify fail или raw key отсутствует → counter `failed_*`.
5. **Disable legacy fallback** в следующем спринте (после full migration):

   ```python
   auth = APIKeyAuth(allow_legacy_sha256=False)
   ```

## Security properties

### What changed
* **SHA-256 → Argon2id** для всех *new* API keys.
* Per-key salt (16 bytes, embedded в PHC).
* Memory-hard: 64MiB на verify, защита от GPU brute-force.
* Constant-time compare (Argon2 — by design, SHA — `hmac.compare_digest`).

### What stays
* SHA-256 verify path — пока `allow_legacy_sha256=True` (default).
* HMAC over stored hash в Redis (grace period check, no rotation race).

### Limitations
* Argon2 verify — ~50ms на 64MB per attempt (только для stored Argon2 keys).
  Глобальный ключ теперь тоже Argon2 — каждый WS handshake с глобальным
  ключом занимает ~50ms (до S172 это было <1ms). При высоком RPS может
  понадобиться caching layer.
* Скрипт миграции требует raw keys (не hashes). Если secrets manager
  хранит только hashes — запуск скрипта невозможен без force rotation.

## Testing

```bash
# Argon2 + dual-verify unit-тесты.
uv run pytest tests/unit/core/auth/test_api_key_backend.py -q

# WS facade + manager integration tests.
uv run pytest tests/unit/integration/test_api_key_argon2_migration.py -q

# Migration CLI + per-key logic.
uv run pytest tests/unit/tools/test_migrate_api_keys_to_argon2.py -q

# Smoke-тесты (без live Redis).
uv run pytest tests/unit/tools/test_migrate_api_keys_to_argon2_smoke.py -q

# Все ARC-004 тесты разом.
uv run pytest tests/unit/core/auth/test_api_key_backend.py \
                tests/unit/integration/test_api_key_argon2_migration.py \
                tests/unit/tools/test_migrate_api_keys_to_argon2.py \
                tests/unit/tools/test_migrate_api_keys_to_argon2_smoke.py -q
```

Total: **52 passed** at HEAD.

## Rollback plan

Если что-то пошло не так:

1. **Revert deploy** — Redis hashes останутся Argon2 (новые ключи после deploy).
   Старые ключи (до deploy) останутся SHA — backward-compat.
2. **Re-enable legacy SHA** (если по какой-то причине `allow_legacy_sha256=False`
   уже выставлено в production):
   * Через env variable `API_AUTH_ALLOW_LEGACY_SHA256=true` (если
     добавите binding) или напрямую в коде.
3. **Skip migration script** — оставляет SHA-ключи в Redis (dual-verify работает).

## References

* **OWASP Password Storage Cheat Sheet** (2026) — Argon2id рекомендация.
* **RFC 9106** — Argon2 Memory-Hard Function.
* `docs/audit/AUDIT_2026-06-30.md` (ARC-004).
* `docs/audit/DEEP_AUDIT_REPORT.md` (legacy S-7: SHA-256 без соли).
