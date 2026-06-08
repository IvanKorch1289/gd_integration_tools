# ADR-0092: Vault zero-downtime rotation (formalize K1 S19 W1)

**Date:** 2026-06-08
**Status:** Accepted (S68 W2 — formalize decision, S65 W2 backlog)
**Sprint:** S68
**Deciders:** core/security team
**Supersedes:** — (formalizes existing K1 S19 W1 implementation)
**Related:** ADR-0051, vault_*.py, secret_rotation.py

## Context

Backlog S65-W2: "Vault rotation zero-downtime" (от роевого анализа V22).
Подразумевалось что Vault rotation отсутствует или не zero-downtime.

Audit проведён 2026-06-08 — **Vault zero-downtime rotation ALREADY
PRODUCTION-READY** (1302 LOC, 4 модуля + 1 feature-flag).

**Components (verified wc -l):**
```
src/backend/infrastructure/secrets/vault_client.py        445 LOC  (K1 S19 W1)
src/backend/infrastructure/secrets/vault_rotator.py      352 LOC
src/backend/infrastructure/application/vault_refresher.py 226 LOC (on_rotation callback)
src/backend/core/security/secret_rotation.py             279 LOC  (S16 K1 W3)
Total:                                                    1302 LOC
```

**Feature flag:** `vault_zero_downtime_rotation` (Sprint 19).

## Decision

Признать Vault zero-downtime rotation PRODUCTION-READY. Реализация
K1 S19 W1 (vault_client.py) + S16 K1 W3 (secret_rotation.py) закрыта.

**Rotation features (verified в vault_client.py):**
* **Graceful reconnect** — exponential backoff при connection failures
* **Drift-toleration window** — старый secret хранится N минут до
  активации нового (grace period для rolling restart)
* **Validate-before-activate** — новые credentials проверяются
  ДО активации (fail-safe pattern)
* **Background task** — `start_rotation(interval_seconds=300)` —
  APScheduler/TaskRegistry integration, graceful shutdown
* **Per-path callbacks** — `register(path, on_change_callback, validator)` —
  каждая DB-connection / API-key имеет свой callback
* **Prometheus metrics** — `vault_validation_failed_total{path}` counter
* **Per-secret validators** — `validator=lambda data: test_connection(data)`
  (проверка что новые credentials работают)

**Usage pattern:**
```python
client = VaultClient.from_env()
client.register(
    "secret/data/db/credentials",
    lambda data: db_pool.reload(data),     # callback on rotation
    validator=lambda data: test_connection(data),  # validate-before-activate
)
await client.start_rotation(interval_seconds=300)  # poll every 5 min
# Shutdown:
await client.stop_rotation()
```

**Public API** (vault_refresher.py + di/providers/ai.py):
* `get_vault_refresher_provider()` — DI injection
* `set_vault_refresher_provider(refresher)` — для тестов
* `VaultSecretRefresher.on_rotation(path, callback)` — per-path callback

## Consequences

### Positive

* Zero-downtime: rolling restart не требует manual secret rotation
* Fail-safe: новые credentials проверяются ДО активации
* Observable: Prometheus counter для failed validations
* Per-path: каждая subsystem может зарегистрировать свой callback
  (DB pool reload, API key refresh, MQ credentials, etc.)
* Feature-flag: `vault_zero_downtime_rotation` default-OFF,
  rollout через config (per AGENTS.md security policy)

### Negative

* Validation callback в каждом subsystem нужно регистрировать
  (нет auto-discovery)
* Background task добавляет operational complexity (lifecycle management)
* Vault backend dependency (требует `hvac` lib в `secrets` extra)

### Neutral

* 1302 LOC distributed across 4 модуля — clear separation
* `secret_rotation.py` (S16 K1 W3) — protocol-level API
* `vault_rotator.py` (K1 S19 W1) — implementation
* `vault_refresher.py` (S??) — on_rotation callback registry

## Implementation Status

| Component | Status | Location |
|-----------|--------|----------|
| `VaultClient` (zero-downtime) | DONE | infrastructure/secrets/vault_client.py |
| `VaultSecretRotator` (background polling) | DONE | infrastructure/secrets/vault_rotator.py |
| `VaultSecretRefresher` (callback registry) | DONE | infrastructure/application/vault_refresher.py |
| `SecretRotation` (protocol) | DONE | core/security/secret_rotation.py |
| `vault_zero_downtime_rotation` feature-flag | DONE | core/config/features/__init__.py:271 |
| `vault_validation_failed_total{path}` metric | DONE | vault_client.py:40+ |
| `register(path, callback, validator)` API | DONE | vault_client.py |
| `start_rotation(interval_seconds)` | DONE | vault_client.py |
| `stop_rotation()` (graceful) | DONE | vault_client.py |
| DI provider (`get_vault_refresher_provider`) | DONE | core/di/providers/ai.py:157+ |
| Tests (validator, rotation, fail-safe) | DONE | tests/unit/infrastructure/secrets/ (verified by sibling) |
| Admin endpoint для manual rotation trigger | TODO | out of scope |
| Auto-discovery subsystem callbacks | TODO | out of scope |
| Rotation history audit log | TODO | out of scope |

## References

* `src/backend/infrastructure/secrets/vault_client.py` (445 LOC)
* `src/backend/infrastructure/secrets/vault_rotator.py` (352 LOC)
* `src/backend/infrastructure/application/vault_refresher.py` (226 LOC)
* `src/backend/core/security/secret_rotation.py` (279 LOC)
* `src/backend/core/config/features/__init__.py:271` (`vault_zero_downtime_rotation` flag)
* K1 S19 W1: original implementation sprint
* S16 K1 W3: rotation protocol (DoD-8)
* `src/backend/core/di/providers/ai.py:157+` (DI integration)
* ADR-0051 (parent: in-house security primitives)
