# P1 split plan: core/di/providers.py (Q4=D, split by domain)

**Plan date:** 2026-06-03 | **v9 P1:** God-объекты | **Status:** plan (no execution yet)

## Audit recap

- File: `core/di/providers.py` — **1234 LOC**
- 60 `get_X_provider()` functions (lazy-cached singletons)
- 54 `set_X_provider()` functions (DI override)
- 5 `_resolve_X` / `_noop` private helpers
- **62 external usages** в `src/backend/services/*`
- Module-level functions (no class) — singleton pattern via module-level dict

## Variant: D (split by domain)

### Целевая структура (6 domain files + re-export facade)

```
core/di/providers/__init__.py            # re-exports ВСЕ 60 get_* + 54 set_* (backward compat)
core/di/providers/_base.py               # shared singleton-cache dict (~30 LOC)

core/di/providers/cache.py               # ~220 LOC: 12 get/set pairs
                                        # cache_invalidator, slo_tracker, health_aggregator,
                                        # healthcheck_session, admin_cache_storage,
                                        # response_cache, signature_builder,
                                        # rag_cache, redis_kv, redis_stream, mongo (не-DB)

core/di/providers/db.py                  # ~150 LOC: 7 get/set pairs
                                        # clickhouse, mongo, file_repo,
                                        # connector_registry, connector_registry_errors,
                                        # connector_config_store, api_key_manager

core/di/providers/http.py                # ~180 LOC: 9 get/set pairs
                                        # http_client, smtp, express, browser,
                                        # external_session_manager, import_gateway,
                                        # ai_sanitizer, llm_judge_metrics,
                                        # workflow_event_store (http-style)

core/di/providers/ai.py                  # ~280 LOC: 14 get/set pairs
                                        # ai_sanitizer, pii_tokenizer, pii_registry,
                                        # llm_judge_metrics, rag_cache, langfuse,
                                        # pii_recognizer, semantic_cache,
                                        # gateway_adapter, presidio_analyzer,
                                        # retrieval_masker, agent_memory,
                                        # ai_agent, rag_ingest_service

core/di/providers/auth.py                # ~150 LOC: 7 get/set pairs
                                        # api_key_manager, signature_builder,
                                        # connector_config_store, oauth_session,
                                        # saml_handler, jwt_blacklist,
                                        # jwks_cache

core/di/providers/messaging.py           # ~150 LOC: 7 get/set pairs
                                        # action_bus, scheduler_manager,
                                        # workflow_event_store, outbox_worker,
                                        # reactive_dispatcher, saga_history,
                                        # hitl_service
```

**Total: ~1230 LOC распределённых по 7 файлам** (включая __init__.py re-export).

### Backward compat strategy

**Critical:** 62 файла импортируют `from src.backend.core.di.providers import get_X`.

`core/di/providers/__init__.py`:
```python
from src.backend.core.di.providers.cache import (
    get_cache_invalidator_provider, set_cache_invalidator_provider, ...
)
from src.backend.core.di.providers.db import (
    get_clickhouse_client_provider, set_clickhouse_client_provider, ...
)
# ... 60 imports total

__all__ = (
    "get_cache_invalidator_provider", "set_cache_invalidator_provider",
    "get_clickhouse_client_provider", ...
)
```

External imports: `from src.backend.core.di.providers import get_X` → **работает без изменений**.

## Risk assessment

### R1: Package/module conflict (MEDIUM risk)

`core/di/providers.py` (file) → `core/di/providers/` (package). Тот же конфликт что T1.3.1 features.py.

**Mitigation:**
- Step 1: create `core/di/providers/` directory (new, no conflict)
- Step 2: move all code to `core/di/providers/_impl.py` (private module)
- Step 3: replace `core/di/providers.py` with package init: `from ._impl import *`
- Step 4: split `_impl.py` into 6 domain files inside package
- Step 5: `__init__.py` re-exports

### R2: 62 import sites to verify (MEDIUM risk)

Каждый из 62 usages импортирует 1-N функций. После split — все imports продолжают работать через `__init__.py` re-exports.

**Mitigation:**
- Step 0: enumerate все 62 imports (grep)
- Final step: запустить ВСЕ tests в `tests/unit/services/` — если pass → backward compat 100%
- `pytest tests/unit/ --co` — verify 5388 tests still collectable

### R3: Singleton cache state (LOW risk)

`get_X_provider` кеширует instance в module-level dict. После split по 6 файлам — каждый файл имеет свой dict. **Behavior не меняется** (singleton-per-domain), но state изолирован.

**Mitigation:**
- Сохранить cache-dict в каждом domain-файле
- НЕ создавать shared cache (это сломает behavior)
- Tests: `get_X_provider()` должен возвращать **тот же объект** на повторные вызовы в рамках одного домена

### R4: Cross-domain references (LOW risk)

`_resolve_unified_audit_service` (db?) может ссылаться на `get_X_provider` из другого domain. При split — circular import risk.

**Mitigation:**
- Cross-domain refs: import ВНУТРИ function (lazy import) — already production pattern
- Audit existing code: `_resolve_pii_token_registry` imports `get_pii_tokenizer_provider` (same domain) — OK
- Если circular: используем `TYPE_CHECKING` import + late binding

## Execution plan (multi-step)

### T-P1.2a: enumerate imports (15 мин)
1. `grep -rln "from src.backend.core.di.providers" src/backend --include='*.py' | wc -l` → 62 (verify)
2. `grep -rhE "from src.backend.core.di.providers import [a-zA-Z_, ]+" src/backend --include='*.py' | sort -u > /tmp/providers_imports.txt`
3. Manual: классифицировать 60 функций по 6 доменам (auth, cache, db, http, ai, messaging)
4. Update this plan с конкретным mapping `function → domain file`

### T-P1.2b: create providers/ package (30 мин)
1. `git mv src/backend/core/di/providers.py src/backend/core/di/providers.py.bak` (safety)
2. `mkdir src/backend/core/di/providers/`
3. Copy content из .bak в `src/backend/core/di/providers/_impl.py` (всё как было)
4. Create `src/backend/core/di/providers/__init__.py`:
   ```python
   from src.backend.core.di.providers._impl import *  # noqa
   ```
5. `rm src/backend/core/di/providers.py.bak`
6. Verify: pytest all 62 imports still work + all 5388 tests collect
7. `make lint` exit 0
8. Commit `[verified] refactor(P1.2b): providers.py → providers/ package (no behavior change)`
9. Review: git diff, import check, full test suite

### T-P1.2c: split _impl.py → 6 domain files (2-3 часа)
1. Create 6 files: `cache.py`, `db.py`, `http.py`, `ai.py`, `auth.py`, `messaging.py`
2. Move `_impl.py` content per domain classification
3. Each file: imports + functions + module-level dict for singletons
4. Update `__init__.py` to import from each domain file
5. Verify: pytest all tests pass
6. `make lint` exit 0
7. Commit `[verified] refactor(P1.2c): providers/ split into 6 domain files (1234→~200/file)`
8. Review: diff + tests + external imports unchanged

### T-P1.2d: final smoke test + cleanup
1. Delete `_impl.py` (если остался)
2. Add `__all__` per domain file (явные exports)
3. Update TECH_DEBT если были `pragma: no cover`
4. Commit `[verified] refactor(P1.2d): providers/ cleanup + __all__ explicit`

## Estimated timeline

| Step | Effort | Risk | Cumulative LOC reduction |
|------|-------:|:----:|:------------------------:|
| T-P1.2a | 15 мин | NONE | — |
| T-P1.2b | 30 мин | MEDIUM | 0 (preparation) |
| T-P1.2c | 2-3 часа | MEDIUM | -1100 (split) |
| T-P1.2d | 30 мин | LOW | cleanup |
| **Total** | **3-4 часа** | — | **1234→~200/file** ✅ P1 DoD |

## Open questions

- Q1: Domain classification — какие функции в каком домене? (Нужен manual audit T-P1.2a)
- Q2: 62 imports — все ли через `from ... import X`? Если `import providers.X` (qualified) — потребуется ещё facade
- Q3: Provider state isolation — подтвердить что split не ломает cross-provider state
- Q4: Alternative: extract class-based `ProviderRegistry` (single source of truth) вместо 6 доменов? Рекомендую **нет** — больше refactor, чем minimal scope
