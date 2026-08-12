# Phase 5 · cycle-1 · Architect Review

**Дата:** 2026-08-06
**Reviewer:** phase-5-02 (architect, independent)
**Scope:** Same Phase 4 artifacts (T-1.4, T-1.5, T-3.1)
**Source of truth:** code (diff + tests), not developer reports

## TL;DR

**VERDICT: PASS** — все 5 обязательных пунктов выполнены; новых нарушений нет;
изоляция тестов подтверждена; pre-existing merge-conflict в `cache_mixin.py`
не имеет отношения к Phase 4 и блокирует только file-level pytest прогон
`test_gateway_pipeline_mixin.py` (4 логических ветки `PolicyMixin._check_capability`
проверены изолированным Python-сценарием — все 4 path'а ведут себя согласно
доктрине dual-signature duck-typing).

## 1. Артефакты проверки (read-only)

| Артефакт | Источник |
|---|---|
| `src/backend/dsl/engine/processors/eip/routing/multicast.py` (T-1.4) | `git diff` |
| `src/backend/dsl/engine/processors/eip/reliability/redelivery_policy.py` (T-1.4) | `git diff` |
| `src/backend/core/ai/gateway_pipeline_mixin/policy_mixin.py` (T-1.5) | `git diff` + `Read` |
| `src/backend/services/ai/gateway_adapter.py` (T-1.5) | `git diff` + `Read` |
| `src/backend/infrastructure/cache/rag/embedding_cache.py` (T-3.1) | `git diff` + `Read` |
| `src/backend/dsl/engine/execution_engine.py` (T-1.4 caller) | `Read` (init signature) |
| `pyproject.toml` line 104 (T-3.1 dep) | `grep` |
| `uv.lock` line 899/902 (T-3.1 lockfile) | `grep` |

## 2. Gates (cycle-1 §0 + task-specific)

### 2.1. Layer checker (обязательный gate)

| Команда | Результат |
|---|---|
| `python tools/check_layers.py --root src` | exit 0; `0 новых`; `175 legacy`; 2273 файлов |

**Evidence:**
- Run stdout: `Нарушений: 0 новых  (файлов: 2273; baseline: 175 legacy)`
- Tool: `tools/check_layers.py` (legacy allowlist `tools/check_layers_allowlist.txt` = 180 lines)

**Verdict: PASS** — точно соответствует baseline (`175 legacy / 0 new`).
Новых layer violations не появилось.

### 2.2. Security allowlist (обязательный gate)

| Команда | Результат |
|---|---|
| `grep -cE "^CVE-\|^GHSA-\|^PYSEC-" .security/pip-audit-allowlist.txt` | `35` |
| `git diff --numstat .security/pip-audit-allowlist.txt` | empty (no growth) |

**Verdict: PASS** — baseline 35 сохранён, файл не тронут.

### 2.3. Docstring gate (обязательный gate)

| Команда | Результат |
|---|---|
| `make check-docstrings MAX_ALLOWED=0` | exit 0; `Total: 0 missing docstrings in 0 files`; `Files scanned: 838` |

**Verdict: PASS** — все docstrings на месте, русские docstrings не переведены
(проверено выборочно в `policy_mixin.py`, `redelivery_policy.py`,
`embedding_cache.py`).

### 2.4. s3.py + uv.lock (обязательный gate)

| Команда | Результат |
|---|---|
| `git diff --numstat src/backend/infrastructure/storage/s3.py` | empty (untouched) |
| `git diff --numstat uv.lock` | `0	15	uv.lock` (15 deletions, svcs pre-existing) |
| `git diff uv.lock \| wc -l` | 40 (context+headers, 0 added lines) |

**Verdict: PASS** — s3.py не тронут; uv.lock churn только pre-existing
(`svcs` package удалён, не относится к Phase 4).

### 2.5. extensions/ untouched (clean architecture gate)

| Команда | Результат |
|---|---|
| `git diff extensions/` | empty |
| `grep -rn "extensions/.*infrastructure" extensions/` | 0 hits |

**Verdict: PASS** — extensions/ не модифицированы, нет новых
extension→infrastructure direct imports.

## 3. Task-specific verification

### 3.1. T-1.5 — AIGateway bare fallback (security/data-loss path)

**Что проверял:** голый `return AIGateway()` fallback удалён или gated
dev-only feature flag'ом — НЕ silent fail-open.

| Команда | Результат |
|---|---|
| `grep -nE "return AIGateway\(\)" src/backend/services/ai/gateway_adapter.py` | 0 hits |
| `grep -nE "AIGatewayProductionWiringError\|raise AIGatewayProductionWiringError" src/backend/services/ai/gateway_adapter.py` | 3 hits: line 107 (docstring), 118 (Raises), 142 (raise site) |
| `grep -nE "return AIGateway\(\)" src/backend/` (entire src) | 0 hits |

**Фактический код (gateway_adapter.py:131-142):**
```python
try:
    from src.backend.core.di.providers.ai import get_ai_gateway_provider
    return get_ai_gateway_provider()
except Exception as exc:
    from src.backend.core.ai.errors import AIGatewayProductionWiringError
    _logger.error(
        "AIGateway composition-root DI lookup failed: %s", exc,
        extra={"component": "gateway_adapter", "lookup": "get_ai_gateway_provider"},
    )
    raise AIGatewayProductionWiringError(missing=("ai_gateway",)) from exc
```

**Verdict: PASS** — fallback удалён полностью (не gated, не dev-only);
composition-root DI lookup теперь fail-closed: `logger.error` +
`raise AIGatewayProductionWiringError`. Это **stronger** чем "dev-only
feature flag" — silent fail-open устранён в любом окружении.

**Tests:** `tests/unit/services/ai/test_gateway_adapter.py` — 9 passed in 0.39s
(включая 3 новых: `test_get_ai_gateway_raises_on_di_lookup_failure`,
`test_get_ai_gateway_uses_provider_when_no_app_state`,
`test_get_ai_gateway_prefers_app_state_when_present`).

### 3.2. T-3.1 — cachetools в core deps (no lockfile churn)

**Что проверял:** `cachetools` уже в core deps, не требует новых lockfile-изменений.

| Команда | Результат |
|---|---|
| `grep -nE "cachetools" pyproject.toml` | line 104: `"cachetools>=5.3.0,<8.0.0",` |
| `grep -nE "^\[" pyproject.toml` (sections) | line 10: `[project]`, line 147: `[project.optional-dependencies]` |
| `awk '/^dependencies =/,/^\]/' pyproject.toml` | содержит cachetools |
| `grep -n "cachetools" uv.lock` | line 899, 902, 904, 2177, 2850, 3152, 5533, 5564, 7388 — version `7.1.7` (locked) |

**Verdict: PASS** — `cachetools>=5.3.0,<8.0.0` в `[project].dependencies`
(core deps), version `7.1.7` уже locked в `uv.lock`. Использование
`from cachetools import TTLCache` не требует lockfile-изменений.

**Tests:** `tests/unit/infrastructure/cache/rag/test_embedding_cache.py` —
10 passed in 0.93s. Regression: `pytest tests/unit/infrastructure/cache/` —
60 passed (no regression).

### 3.3. T-1.4 — ExecutionEngine signature change (no caller breakage)

**Что проверял:** изменение signature `ExecutionEngine.__init__` (удаление
`route_registry` kwarg'а) не ломает другие callers.

**Init signature (execution_engine.py:67-72):**
```python
def __init__(
    self,
    middleware: MiddlewareChain | None = None,
    validate_before_execute: bool = True,
    pool: ProcessorPool | None = None,
) -> None:
```

**Production callers (8 callsites, все совместимы):**

| Файл:line | Вызов | Совместимость |
|---|---|---|
| `src/backend/services/dsl_portal/builder_facade.py:181` | `ExecutionEngine()` | OK (no args) |
| `src/backend/dsl/engine/processors/base.py:180` | `ExecutionEngine()` | OK (no args) |
| `src/backend/dsl/engine/processors/eip/routing/multicast.py:176` | `ExecutionEngine()` | OK (T-1.4 fix) |
| `src/backend/dsl/service/facade.py:21` | `engine or ExecutionEngine()` | OK (no args) |
| `src/backend/entrypoints/api/v1/endpoints/dsl_console.py:196` | `ExecutionEngine()` | OK (no args) |
| `src/backend/entrypoints/api/v1/endpoints/dsl_console.py:243` | `ExecutionEngine()` | OK (no args) |
| `src/backend/entrypoints/api/v1/endpoints/imports.py:320` | `ExecutionEngine()` | OK (no args) |
| `src/backend/entrypoints/mcp/mcp_server/tools_route.py:76` | `ExecutionEngine()` | OK (no args) |

**Test callers (8+ callsites, все совместимы):**

| Файл | Pattern | Совместимость |
|---|---|---|
| `tests/unit/dsl/engine/test_execution_engine_parallel_timeout.py` (5 callsites) | `ExecutionEngine(validate_before_execute=False)` | OK (kwarg in signature) |
| `tests/unit/dsl/engine/test_execution_engine_validation_cache.py` (6 callsites) | `ExecutionEngine(validate_before_execute=True)` | OK (kwarg in signature) |
| `tests/unit/dsl/engine/test_tenant_aware_execution.py` (6 callsites) | `ExecutionEngine(validate_before_execute=False)` | OK (kwarg in signature) |
| `tests/unit/dsl/builders/test_middleware_mixin.py` (3 callsites) | `ExecutionEngine(middleware=..., validate_before_execute=False)` | OK (both kwargs in signature) |
| `tests/unit/dsl/engine/processors/eip/routing/test_multicast.py:98` | `ExecutionEngine()` | OK (no args; new test) |
| `tests/integration/dsl/test_collection_blueprint.py` (3 callsites) | `ExecutionEngine()` | OK (no args) |

**Остаточные `route_registry=` references (NOT ExecutionEngine):**

| Файл | Контекст | Связь с ExecutionEngine? |
|---|---|---|
| `src/backend/plugins/composition/lifecycle/watchers.py:42` | `route_registry=route_registry` kwarg в watcher callback | НЕТ (это yaml_watcher API) |
| `tests/unit/dsl/yaml_watcher/test_*.py` | `route_registry=` для `RouteFileWatcher` | НЕТ |
| `tests/unit/dsl/eip/test_multicast_routes.py:71` | comment only: "Имитирует конструктор ExecutionEngine(route_registry=...)" | НЕТ (комментарий-регрессия) |

**Verdict: PASS** — все 16 callsites совместимы с новой signature; не
существует ни одного callsite, передающего `route_registry=` в
`ExecutionEngine.__init__`. `route_registry` в `multicast.py` корректно
используется через module-level lookup (`from src.backend.dsl.commands.registry
import route_registry`).

**Tests:** 17 existing `ExecutionEngine` tests pass (parallel_timeout +
validation_cache + tenant_aware) + 6 new multicast tests + 9 new
redelivery_policy tests = 32 passed. No regression.

### 3.4. Clean architecture (layer/dependency hygiene)

**Что проверял:** новые dependency imports не вводят layer violations;
нет extension→infrastructure direct imports; нет facade-bypassing imports.

**Новые импорты (из diff'ов Phase 4):**

| Файл | Новый import | Категория |
|---|---|---|
| `src/backend/services/ai/gateway_adapter.py:46` | `from src.backend.core.logging import get_logger` | core (allowed) |
| `src/backend/core/ai/gateway_pipeline_mixin/policy_mixin.py:110` | `import inspect` | stdlib |
| `src/backend/infrastructure/cache/rag/embedding_cache.py:14` | `from cachetools import TTLCache` | core dep (in pyproject.toml) |
| `src/backend/services/ai/gateway_adapter.py:136` | `from src.backend.core.ai.errors import AIGatewayProductionWiringError` | core (allowed; lazy import в except) |
| `src/backend/services/ai/gateway_adapter.py:121` | `from src.backend.core.di.app_state import get_app_ref` | core (pre-existing) |
| `src/backend/services/ai/gateway_adapter.py:132` | `from src.backend.core.di.providers.ai import get_ai_gateway_provider` | core (pre-existing) |

**Verdict: PASS** — все импорты направлены в `core.*` или stdlib/third-party;
нет импортов из `extensions/*` в core/services/infrastructure;
нет новых импортов, нарушающих capability-checked facade pattern.

Layer checker подтверждает: `0 новых / 175 legacy` (§2.1).

## 4. Pre-existing issues NOT introduced by Phase 4

### 4.1. Merge conflict в `cache_mixin.py`

| Что | Где |
|---|---|
| `<<<<<<< Updated upstream` | `src/backend/core/security/capabilities/gate/cache_mixin.py:81, 110` |
| `=======` | `src/backend/core/security/capabilities/gate/cache_mixin.py:85, 114` |
| `>>>>>>> Stashed changes` | `src/backend/core/security/capabilities/gate/cache_mixin.py:87, 116` |

**Статус git:** "both modified" (uncommitted, unmerged).

**Эффект:** блокирует file-level pytest run
`tests/unit/core/ai/test_gateway_pipeline_mixin.py` через import chain
(`PipelineStepsMixin` → `core/ai/gateway/__init__.py` → `core/security/capabilities/gate/__init__.py`
→ `core/security/capabilities/gate/cache_mixin.py` → IndentationError).

**Что НЕ затронуто:** 4 файла Phase 4 с их собственными tests
(`test_embedding_cache.py`, `test_gateway_adapter.py`,
`test_multicast.py`, `test_redelivery_policy.py`) собираются и
прогоняются чисто (34 passed). Этот merge conflict — pre-existing
working-tree state (зафиксирован в PREFLIGHT-REPORT §1 как
"working tree 14 entries" — `cache_mixin.py` среди uncommitted
modifications).

**Mitigation:** `PolicyMixin._check_capability` (T-1.5 target) верифицирован
через изолированный Python-сценарий — все 4 logic paths
(`no_gate`, `3-arg gate`, `1-arg gate`, `MagicMock/variadic`) дают
ожидаемое поведение:

```text
PolicyMixin imports OK
Test 1 (no_gate_is_noop) PASS
Test 2 (3-arg real gate) PASS  — calls == [('core', 'ai.invoke.wf1', 'workflow:wf1')]
Test 3 (1-arg real gate) PASS  — calls == ['ai.invoke.wf2']
Test 4 (MagicMock/variadic) PASS — check called via 1-arg path
```

**Scope attribution:** этот merge conflict НЕ introduced ни одним из
T-1.4 / T-1.5 / T-3.1 — file не входит в diff'ы Phase 4.

### 4.2. Pre-existing failures в B-05 §7

B-05 report §7 явно указывает 5 pre-existing failures в
`tests/unit/core/ai/test_gateway_pipeline_mixin.py` (env state:
spacy download failure, `ai_policy_enforce=True` в test env).
Эти failures также блокируются merge conflict §4.1 и не связаны с
T-1.5 changes.

## 5. Definition of Done — verification matrix

| Критерий | Команда / Evidence | Результат |
|---|---|---|
| `python tools/check_layers.py --root src` exit 0 | stdout | exit 0 |
| 175 legacy / 0 new | stdout | `0 новых (файлов: 2273; baseline: 175 legacy)` |
| T-1.5: bare `AIGateway()` fallback удалён | `grep -nE "return AIGateway\(\)" src/backend/services/ai/gateway_adapter.py` | 0 hits |
| T-1.5: fail-closed path при broken DI | `grep -nE "AIGatewayProductionWiringError\|raise AIGatewayProductionWiringError" src/backend/services/ai/gateway_adapter.py` | 3 hits (line 107 docstring, 118 Raises, 142 raise) |
| T-3.1: cachetools в core deps | `grep -n "cachetools" pyproject.toml` | line 104: `cachetools>=5.3.0,<8.0.0` в `[project].dependencies` |
| T-3.1: нет нового lockfile churn | `git diff --numstat uv.lock` | `0	15	uv.lock` (15 deletions pre-existing, нет cachetools изменений) |
| T-1.4: ExecutionEngine signature совместима со всеми callers | `grep -rn "ExecutionEngine(" src/backend/ tests/` | 16 callsites, все совместимы (см. §3.3) |
| T-1.4: нет remaining `route_registry=` в `ExecutionEngine` callers | `grep -rn "route_registry=" src/backend/dsl/engine/` | 0 hits в engine/ |
| Clean architecture: extensions/ не тронуты | `git diff extensions/` | empty |
| Clean architecture: нет extension→infrastructure imports | `grep -rn "extensions/.*infrastructure" extensions/` | 0 hits |
| Clean architecture: нет facade-bypassing imports | layer checker §2.1 | `0 новых` |
| Тесты проходят (Phase 4 files) | pytest §3.1-§3.3 | 34 passed (test_embedding_cache + test_gateway_adapter + test_multicast + test_redelivery_policy) |
| Docstring gate | `make check-docstrings MAX_ALLOWED=0` | exit 0; `0 missing` (838 files) |
| Security allowlist не вырос | `grep -cE "^CVE-\|^GHSA-\|^PYSEC-" .security/pip-audit-allowlist.txt` | `35` (= baseline) |
| s3.py не тронут | `git diff --numstat src/backend/infrastructure/storage/s3.py` | empty |

## 6. Unclosed items / follow-up

**Никаких пунктов, блокирующих PASS.** Cycle 1 Phase 4 (T-1.4, T-1.5, T-3.1)
закрыты согласно плану.

**Follow-up (вне scope Phase 4 — рекомендации, не блокеры):**

1. **Merge conflict в `cache_mixin.py`** — pre-existing; рекомендую
   resolve перед любым merge в master (отдельная задача, не входит в
   T-1.4/T-1.5/T-3.1). Файл: `src/backend/core/security/capabilities/gate/cache_mixin.py:81-87, 110-116`.

2. **XPASS на `test_aigateway_pipeline_propagates_capability_denied`** —
   B-05 §3.3 flag'ует: xfail-маркер `_XFAIL_ADAPT_CAPABILITY` теперь
   не нужен (тест pass'ит). Рекомендую снять маркер в follow-up commit'е
   (`tests/unit/services/ai/test_aigateway_capability_wiring.py:26-40`).
   Это test-maintenance concern, вне scope T-1.5.

3. **5 pre-existing failures в `test_gateway_pipeline_mixin.py`** —
   B-05 §7 фиксирует: spacy download + `ai_policy_enforce` env state.
   Рекомендую либо skip-if-no-spacy decorator, либо mock spacy —
   отдельная задача.

## 7. Commands run (audit trail)

```bash
# Layer checker
python tools/check_layers.py --root src

# T-1.5: AIGateway fallback verification
grep -nE "return AIGateway\(\)|AIGatewayProductionWiringError|raise AIGatewayProductionWiringError" \
    src/backend/services/ai/gateway_adapter.py

# T-3.1: cachetools in pyproject + uv.lock
grep -nE "cachetools|cachetools.TTLCache" pyproject.toml
grep -rn "cachetools" pyproject.toml uv.lock
git diff --numstat uv.lock
git diff uv.lock | wc -l

# T-1.4: ExecutionEngine callers + signature
sed -n '60,90p' src/backend/dsl/engine/execution_engine.py
grep -rn "ExecutionEngine(" src/backend/ tests/
grep -rn "route_registry=" src/backend/

# Phase 4 imports hygiene
grep -nE "import|from" src/backend/core/ai/gateway_pipeline_mixin/policy_mixin.py
grep -nE "import|from" src/backend/services/ai/gateway_adapter.py
grep -nE "import|from" src/backend/dsl/engine/processors/eip/routing/multicast.py \
    src/backend/dsl/engine/processors/eip/reliability/redelivery_policy.py \
    src/backend/infrastructure/cache/rag/embedding_cache.py
git diff extensions/

# Tests
.venv/bin/python -m pytest tests/unit/infrastructure/cache/rag/test_embedding_cache.py -v
.venv/bin/python -m pytest tests/unit/services/ai/test_gateway_adapter.py -v
.venv/bin/python -m pytest tests/unit/dsl/engine/processors/eip/routing/test_multicast.py \
    tests/unit/dsl/engine/processors/eip/reliability/test_redelivery_policy.py -v
.venv/bin/python -m pytest tests/unit/dsl/engine/test_execution_engine_parallel_timeout.py \
    tests/unit/dsl/engine/test_execution_engine_validation_cache.py \
    tests/unit/dsl/engine/test_tenant_aware_execution.py --tb=short -q
.venv/bin/python -m pytest tests/unit/infrastructure/cache/ --tb=no -q

# Isolated PolicyMixin._check_capability logic verification
.venv/bin/python -c "..." # 4 paths PASS

# Docstring gate
make check-docstrings MAX_ALLOWED=0

# Pre-existing merge conflict detection
grep -nE "<<<<<<< Updated upstream|=======|>>>>>>> Stashed changes" \
    src/backend/core/security/capabilities/gate/cache_mixin.py
git log --oneline -5 -- src/backend/core/security/capabilities/gate/cache_mixin.py
git status src/backend/core/security/capabilities/gate/cache_mixin.py
```

## 8. Verdict

**PASS** для Phase 4 артефактов (T-1.4, T-1.5, T-3.1):

- Layer checker: 175 legacy / 0 new (точно baseline).
- T-1.5: bare `AIGateway()` fallback полностью удалён; fail-closed path
  (`raise AIGatewayProductionWiringError`) — не silent fail-open, не
  gated dev-only feature flag'ом (stronger than required).
- T-3.1: `cachetools` в core deps (`pyproject.toml:104`); uv.lock
  churn pre-existing (`svcs` deletion, 15 lines), cachetools без
  изменений.
- T-1.4: `ExecutionEngine.__init__` signature `(middleware,
  validate_before_execute, pool)` совместима со всеми 16 callsites
  в src/backend + tests; нет remaining `route_registry=` usage в
  engine/.
- Clean architecture: extensions/ не тронуты; нет facade-bypassing
  imports; layer checker 0 новых.
- Tests: 34 passed (Phase 4 файлы) + 17 existing ExecutionEngine tests
  passed + 60 cache tests regression-clean.
- Docstring gate: 0 missing (838 files).
- s3.py / uv.lock / allowlist: не тронуты / pre-existing churn / не
  вырос.

**Unclosed (NOT blocking):** merge conflict в `cache_mixin.py`
(pre-existing, не Phase 4 scope); 5 pre-existing failures в
`test_gateway_pipeline_mixin.py` (env state, не Phase 4 scope); XPASS
на `test_aigateway_pipeline_propagates_capability_denied` (test
maintenance, рекомендую follow-up).

---

*phase-5-02 architect. Independent verification: code + tests + diffs +
layer checker. READ-only на source/lockfile/allowlist/s3.py. Изменения
только в этот отчёт.*
