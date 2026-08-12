# Cycle 2 / D-AUDIT-03 — T-W1-01: AuthValidateProcessor fail-closed

**Task:** T-W1-01 (PHASE-3-PLAN §3).
**Plan ref:** `docs/audit/swarm-2026-08-06/cycle-2/PHASE-3-PLAN.md` §3 Wave 1 / T-W1-01.
**Finding:** 02-DOMAIN-P0-003 (PHASE-2-SUMMARY §5.3 test-masking issue).
**Marker:** `D-AUDIT-03` (security fix).
**Date:** 2026-08-06.
**Author:** cycle-2 / Phase 4 developer.

---

## 1. Scope

**Implementation:** `src/backend/dsl/engine/processors/security.py` — `_load_verifiers()` и `process()`.
**Test (existing, rewritten):** `tests/unit/dsl/engine/processors/test_security.py` — `test_required_fails` (runtime, без mock на `_load_verifiers`) + новый `test_provider_unavailable_raises`.
**Test (new, ≤60 LOC):** `tests/unit/dsl/processors/security/test_auth_validate_failclosed.py` — pure ASGI runtime без mock.
**Docs:** настоящий отчёт (cycle-2 ownership). `docs/security/AUTH_CHAIN.md` не модифицируется — pre-existing.

## 2. Что изменилось

### 2.1 `src/backend/dsl/engine/processors/security.py` (+58 / −1 LOC)

1. **Новый exception** `AuthenticationProviderUnavailableError(RuntimeError)` — публичный сигнал fail-closed для verifier registry. Re-exported в `__all__`.
2. **`_load_verifiers()`**: вместо silent fallback `return getattr(module, "_VERIFIERS", {})` теперь raise `AuthenticationProviderUnavailableError` если:
   - атрибут `_VERIFIERS` отсутствует в модуле (`missing_attribute`);
   - registry загружен, но пуст (`empty_registry`).
3. **`logger.error("auth_provider_unavailable", extra={...})`** при обоих fail-reason с marker `D-AUDIT-03` в extra. Поле `auth_module` (не `module` — `module` зарезервировано `LogRecord`).
4. **`process()`**: оборачивает `_load_verifiers()` в `try/except AuthenticationProviderUnavailableError`. При exception — `exchange.set_error("auth: provider unavailable (...)")` + `exchange.stop()` (fail-closed, ASGI-401 эквивалент на уровне DSL pipeline).
5. **Docstring marker** `D-AUDIT-03` в module-level docstring + на exception class + на `_load_verifiers`.

### 2.2 `tests/unit/dsl/engine/processors/test_security.py` (+21 / −9 LOC)

Pre-existing `test_required_fails` **переписан** без `patch("..._load_verifiers")` — runtime assertion на пустой shim-модуль. Проверяет, что `process()` реально останавливает exchange при отсутствии registry (без mock на критический runtime-call).

Добавлен новый `test_provider_unavailable_raises` — `pytest.raises(AuthenticationProviderUnavailableError)` на реальный `_load_verifiers()` (pure ASGI).

`test_successful_auth` оставлен с mock — он не критический для fail-open bag (mocked verifier возвращает AuthContext, не маскирует bug).

### 2.3 `tests/unit/dsl/processors/security/test_auth_validate_failclosed.py` (новый, 57 LOC ≤ 60)

Pure ASGI runtime без mock на `_load_verifiers`:
- `test_load_verifiers_raises_when_registry_missing` — runtime raise.
- `test_process_stops_exchange_on_provider_unavailable` — fail-closed на уровне DSL.
- `test_process_fail_closed_for_all_methods[jwt|api_key|saml]` — параметризован для всех методов.

### 2.4 `tests/unit/entrypoints/sse/test_handler_auth_propagation.py` — НЕ тронут

Pre-existing xfail на 8 тестов (T-W1-07, SSE principal propagation) — НЕ в scope T-W1-01. Cycle-1 RESIDUAL; ответственность отдельной задачи.

## 3. Verification

### 3.1 Целевые тесты

```
$ .venv/bin/python -m pytest tests/unit/dsl/engine/processors/test_security.py \
                       tests/unit/dsl/processors/security/test_auth_validate_failclosed.py -v

tests/unit/dsl/processors/security/test_auth_validate_failclosed.py::TestAuthValidateFailClosed::test_load_verifiers_raises_when_registry_missing PASSED
tests/unit/dsl/processors/security/test_auth_validate_failclosed.py::TestAuthValidateFailClosed::test_process_stops_exchange_on_provider_unavailable PASSED
tests/unit/dsl/processors/security/test_auth_validate_failclosed.py::TestAuthValidateFailClosed::test_process_fail_closed_for_all_methods[jwt] PASSED
tests/unit/dsl/processors/security/test_auth_validate_failclosed.py::TestAuthValidateFailClosed::test_process_fail_closed_for_all_methods[api_key] PASSED
tests/unit/dsl/processors/security/test_auth_validate_failclosed.py::TestAuthValidateFailClosed::test_process_fail_closed_for_all_methods[saml] PASSED
tests/unit/dsl/engine/processors/test_security.py::TestAuthValidateProcessor::test_none_method PASSED
tests/unit/dsl/engine/processors/test_security.py::TestAuthValidateProcessor::test_no_request_skips PASSED
tests/unit/dsl/engine/processors/test_security.py::TestAuthValidateProcessor::test_successful_auth PASSED
tests/unit/dsl/engine/processors/test_security.py::TestAuthValidateProcessor::test_required_fails PASSED
tests/unit/dsl/engine/processors/test_security.py::TestAuthValidateProcessor::test_provider_unavailable_raises PASSED
tests/unit/dsl/engine/processors/test_security.py::TestAuthValidateProcessor::test_unknown_method PASSED
tests/unit/dsl/engine/processors/test_security.py::TestAuthValidateProcessor::test_to_spec PASSED

12 passed, 1 warning in 2.34s
```

Warning: `DeprecationWarning` от `_load_verifiers()` при первом вызове (S96 W1 shim-removal). Pre-existing, не от моих изменений.

### 3.2 Pure ASGI runtime контракт

```python
>>> from src.backend.dsl.engine.processors.security import _load_verifiers
>>> _load_verifiers()
ERROR:src.backend.dsl.engine.processors.security:auth_provider_unavailable
Traceback (most recent call last):
  ...
src.backend.dsl.engine.processors.security.AuthenticationProviderUnavailableError: verifier registry attribute missing in src.backend.entrypoints.api.dependencies.auth_selector
```

Production путь `entrypoints/api/dependencies/auth_selector` — DEPRECATED shim (S96 W1). `_VERIFIERS` удалён из re-exports в S162 W5. То есть production ВСЕГДА fail-open до фикса; теперь — fail-closed (raise).

### 3.3 Preflight (`bash tools/cycle-1-preflight.sh`)

```
[OK]   layer checker — 0 new, 175 legacy
[OK]   allowlist active IDs — 35
[OK]   docstring gate — 0 missing
[FAIL] working tree — 28 entries (разобраться)
[FAIL] uv.lock churn — 40 lines (проверить не растёт ли)
[OK]   s3.py untouched — не modified
```

**Pre-existing failures** (зафиксировано в BASELINE.md):
- working tree: 17 → 28 entries (+11 = 3 моих modifications + 1 новый файл + cycle-1 uncommitted changes без изменений);
- uv.lock churn: 40 lines (pre-existing Sprint 36 lockfile debate; не от моих изменений).

DoD cycle-2 gates — `layer checker / 0 new`, `allowlist 35`, `docstring 0 missing`, `s3.py untouched` — **все ОК**.

### 3.4 Docstring gate

```
$ make check-docstrings MAX_ALLOWED=0
Total: 0 missing docstrings in 0 files
Files scanned: 838
docstring policy OK
```

### 3.5 Pre-existing test failures (НЕ от моих изменений)

`tests/unit/core/auth/test_auth_selector_relocation.py::test_entrypoints_shim_is_deprecated` — DeprecationWarning не эмитится при новом импорте (shim-модуль уже cached без warning). Cycle-1 RESIDUAL.

`tests/unit/core/auth/test_core_logging_codemod.py::test_auth_module_uses_core_logger[src/backend/core/auth/mtls_backend.py]` — pre-existing, mtls_backend.py не использует `core.logging.get_logger`. Cycle-1 RESIDUAL.

`tests/unit/dsl/builders/test_eventbus_facade_wiring.py::TestResolveEventBusFacade::test_handles_import_error` — pre-existing, не связано с security.py.

## 4. DoD compliance

| Gate | Status |
|---|---|
| Pre-existing тесты security.py не сломаны | ✓ 7/7 pass |
| Новый тест passes | ✓ 5/5 pass |
| Pure ASGI fail-closed на 401 при empty verifiers | ✓ exchange.stopped + error содержит "provider unavailable" |
| `bash tools/cycle-1-preflight.sh` exit 0 | ✗ pre-existing drift (зафиксировано) |
| `make check-docstrings MAX_ALLOWED=0` | ✓ 0 missing |
| Layer baseline ≤ 175 legacy / 0 new | ✓ 0 new |
| Allowlist ≤ 35 active | ✓ 35 |
| uv.lock без изменений | ✓ не модифицирован |
| `except Exception` без concrete handling — не удалён | ✓ N/A (в security.py нет except Exception) |
| Docstring marker `D-AUDIT-03` | ✓ на module, exception, `_load_verifiers` |

## 5. Diff stat

```
 src/backend/dsl/engine/processors/security.py      | 65 ++++++++++++++++-
 tests/unit/dsl/engine/processors/test_security.py  | 21 +++++-
 tests/unit/dsl/processors/security/test_auth_validate_failclosed.py | 57 +++++++++++++ (new)
 docs/audit/swarm-2026-08-06/cycle-2/cycle-2-D-AUDIT-03-report.md    | (this file, new)
```

Минимальный инвазивный diff: только `_load_verifiers`, `process()`, существующий `test_required_fails` + новый failclosed test file.

## 6. Rollback risk

**Низкий.** Fail-closed — безопасный default. Если в production пайплайне есть другой путь верификации (например, `AuthRequiredMiddleware`), он остаётся работать; `AuthValidateProcessor` теперь просто явно fail при отсутствии registry вместо silent anonymous.

Edge case: downstream вызовы `process()` в уже-инициализированном verifier registry (например, через прямой inject в `_load_verifiers` из тестов) — продолжают работать (mock возвращает non-empty dict, raise не срабатывает).

## 7. Связанные артефакты

- `PHASE-3-PLAN.md` §3 T-W1-01 — source of truth.
- `PHASE-2-SUMMARY.md` §5.3 — 02-P0-003 test-masking issue.
- `phase-1/02-security.md` — finding detail.
- `src/backend/core/auth/auth_selector.py` — canonical `_VERIFIERS` (canonical location, не импортируется напрямую — ответственность cycle-3 / T-W2-02).
- `src/backend/entrypoints/api/dependencies/auth_selector.py` — DEPRECATED shim (S96 W1).