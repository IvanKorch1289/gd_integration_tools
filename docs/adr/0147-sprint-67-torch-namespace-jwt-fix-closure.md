# ADR-0147 — Sprint 67 closure: torch CVE, namespace markers, JWT consolidation, pre-existing fix (4 commits, 4/4 substantive)

* Статус: Accepted (Autonomous work cycle S67, 2026-06-12)
* Связано с: `a7ff4a89` (W0 torch CVE), `082539dd` (W1 namespace), `0dfd21d7` (W2 JWT), `4f9431c5` (W3 accessors), `d7d15b1c` (W4 encode tests)
* Контекст: S66 quick wins closure → 4 P2 backlog items

## Контекст

S67 = P2 quick wins closure. **4/4 substantive**:
- W0: torch CVE-2025-3000 (Dependabot #183) → dismissed `tolerable_risk`
- W1: 21 namespace markers (continuation S66 W3)
- W2: jwt_backend_joserfc shim deletion (380 LOC) + canonical migration
- W3: pre-existing NameError fix в `accessors.py` (DatabaseInitializer)
- W4: regression tests для canonical `encode()` (9 tests)

**Fact-check corrections** (vs S64/S65 backlog):
- ❌ `plugins/composition/__init__.py:9` — `graphql_router` import **НЕ СУЩЕСТВУЕТ**
  (никто не импортит `graphql_router` из `composition`, файл не имеет
  такого import'а; claim в pre-existing backlog — fact-check error)
- ❌ `infrastructure/caching/decorator.py:16` — `redis_client` **НЕ СУЩЕСТВУЕТ**
  (файл `decorator.py` отсутствует в `caching/`, `caching/` dir пустая)
- ✅ `infrastructure/database/database/accessors.py:24,49` — `DatabaseInitializer`/`ExternalDatabaseRegistry`
  NameError **РЕАЛЬНЫЙ**, fixed W3

## Решения

### W0: torch CVE-2025-3000 dismissal (commit `a7ff4a89`)

**Dependabot alert #183** dismissed `tolerable_risk`:
- PyTorch latest = 2.12.0 = max vulnerable (NO upstream patch)
- Transitive via `sentence-transformers>=3.0.0,<6.0.0` (RAG default)
- Local-only attack vector (CVSS v3 5.3, v4 1.9, EPSS 0.00081%)
- Lazy import only в 3 файлах (ml_predict, nemo_client, model_loader)
- Не установлен в dev_light profile
- **Reopen condition**: автоматически при выходе PyTorch > 2.12.0 с patch

### W1: 21 namespace markers (commit `082539dd`)

Continuation S66 W3. PEP 420 docstring pattern (НЕ `__all__`):
- Top-level: `src/backend/__init__.py`
- 4× `core/`: `core/security`
- 4× `dsl/`: `analysis`, `commands`, `transforms`
- 3× `entrypoints/`: `api/dependencies`, `grpc/protobuf/auto`, `mqtt`
- 7× `infrastructure/`: `audit`, `clients/{external,messaging,storage,transport}`, `monitoring`, `persistence`, `security`, `storage`
- 4× `services/`: `ai/agents_pydantic/examples`, `ai/llm`, `core`, `scheduler`

Verified: 0 empty `__init__.py` осталось (было 24, S66 W3 fixed 5, S67 W1 fixed 21).

### W2: JWT backend consolidation (commit `0dfd21d7`)

**Analysis P2-28 + TD-S66-W4**: `jwt_backend_joserfc.py` (380 LOC) + test
— parallel implementation, НЕ python-jose fallback (ОБА используют
joserfc). Feature-flag `auth_joserfc` — meaningless (default-OFF).

**Critical bug fix**: `auth_login.py:173` использовал `subject=` kwarg,
которого НЕ было в shim's `encode(claims, *, alg, secret, ...)` →
TypeError маскировался `try/except` → **mock token fallback** в проде.

Changes:
- `jwt_backend.py`: добавлены top-level `encode()` и `decode()` функции
  (ранее только в shim); `encode()` использует
  `(subject, claims, *, expires_in)` signature совместимый с login.
- `jwt_backend.py`: удалён feature-flag dispatch в `JwtBackend.decode()`
  (больше не нужен — shim удалён).
- `jwt_backend_joserfc.py`: **DELETED** (380 LOC).
- `test_jwt_joserfc.py`: **DELETED**.
- `auth_login.py`, `auth_introspect.py`, `test_auth_introspect.py`:
  импорты переключены на canonical.

Verified: 7/7 test_auth_introspect + 111/111 jwt tests pass.

### W3: pre-existing NameError fix (commit `4f9431c5`)

**Real bug**: `src/backend/infrastructure/database/database/accessors.py`
ссылался на `DatabaseInitializer` (line 24) и `ExternalDatabaseRegistry`
(line 49) КАК на локальные имена, но НЕ импортировал их.

При первом вызове `get_db_initializer()` / `get_external_db_registry()`
Python бросал `NameError: name 'DatabaseInitializer' is not defined`.

Fix: добавлены imports из same-package `initializer.py` и `registry.py`.

Tests: 6 regression tests в `test_accessors_import_fix.py`:
- import smoke + module symbols
- package re-export resolve (через `from ... import DatabaseInitializer`)
- ключевые fix tests: `get_db_initializer_no_nameerror`,
  `get_external_db_registry_no_nameerror` (mock SQLAlchemy engine)
- `__getattr__` backward-compat hook

### W4: regression tests для canonical encode() (commit `d7d15b1c`)

9 тестов покрывают новую canonical `encode()`:
- tuple return signature `(token_str, expires_in)`
- `iat`/`exp` auto-injection (TTL=expires_in, default 3600)
- custom `expires_in` (60, 7200)
- `issuer` claim
- ValueError при отсутствии secret / неподдерживаемом alg
- round-trip `encode→decode`
- `JwtVerificationError` на bad signature
- **regression test** для call pattern `auth_login.py:173`
  (`encode(subject=, claims=)` — был broken в shim)

## Fact-checks summary (S67)

| Claim | Реальность | Status |
|---|---|---|
| torch CVE fix (pin > 2.12.0) | НЕТ upstream patch (2.12.0 = max) | ✅ dismissed |
| 24 empty `__init__.py` | 5 fixed S66 W3, 21 fixed S67 W1 | ✅ 0 remaining |
| jwt_backend consolidation | REAL (parallel impl, broken shim) | ✅ fixed |
| `auth_login.py:173` TypeError | REAL (masked by try/except) | ✅ fixed |
| `accessors.py` NameError | REAL | ✅ fixed W3 |
| `graphql_router` import bug | **НЕ СУЩЕСТВУЕТ** | ❌ fact-check error |
| `redis_client` decorator bug | **НЕ СУЩЕСТВУЕТ** (file missing) | ❌ fact-check error |

## Quality gates (S67 scope)

- **9/9 NEW jwt tests** pass (test_jwt_backend_encode.py)
- **6/6 NEW accessors tests** pass (test_accessors_import_fix.py)
- **111/111 jwt tests** total pass (no regression)
- **7/7 auth_introspect tests** pass (после import migration)
- **0 empty `__init__.py`** в `src/backend/`
- **Dependabot alerts**: 0 open
- Pre-existing failures (TD-S64-W3 redis_client) — not in W3 scope (file missing)

## Lessons learned

1. **"Pre-existing bug" claim → verify в коде** — 2/3 claim'ов из S64 backlog
   оказались fact-check errors (`graphql_router`, `redis_client`).
   Только `DatabaseInitializer` NameError был real. **Фактчек ДО fix**
   обязателен даже для "очевидных" pre-existing bugs.
2. **Masked bugs хуже явных** — `auth_login.py:173` TypeError маскировался
   `try/except` → mock token fallback. Пользователи получали НЕвалидные
   токены в проде. Consolidation открыл и устранил баг.
3. **Dependabot dismiss workflow** — `tolerable_risk` с детальным
   обоснованием лучше, чем бездумный dismiss. Документирует risk profile
   для аудита.
4. **LSP warnings ≠ runtime errors** — Pyright "Import could not be
   resolved" warnings (от partial view) — это НЕ test failure. Tests
   passed в venv, где joserfc установлен.

## S68+ backlog (новое)

- **TD-S67-bug-fact-checks**: документировать в TECH_DEBT что 2/3
  pre-existing claim'ов были fact-check errors.
- **TD-S67-feature-flag-deprecation**: `feature_flags.auth_joserfc`
  setting остаётся в коде (no-op). Удалить при следующем feature flag
  cleanup (S68+).
- **35 core → other violations** (L): рефакторинг `gateway_pipeline_mixin/*`,
  `di/providers/ai.py`.
- **119 dsl/workflows violations** (L): god-files (`agent_registry.py`,
  `batch_capable.py`, `_action_bridge.py`).
- **TD-S64-W3: redis_client decorator bug**: оригинальный claim —
  файл отсутствует. Если когда-нибудь понадобится caching decorator,
  создать с правильным `redis_client` import.
- **AgentSpec.tools runtime enforcement** (L, P0-4 deferred).
- **Reopen monitoring**: torch CVE — автоматически при PyTorch > 2.12.0.
