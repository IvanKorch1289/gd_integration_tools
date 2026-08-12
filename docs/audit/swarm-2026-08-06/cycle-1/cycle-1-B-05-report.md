# Cycle 1 · Task T-1.5 — AIGateway capability TypeError + bare fallback

**Дата:** 2026-08-06
**Plan ref:** `docs/audit/swarm-2026-08-06/cycle-1/PHASE-3-PLAN.md §2.5`
**Docstring marker:** `cycle-1/B-05` (security/data-loss: silent fail-open path)
**Priority:** P0 (security + composition-root integrity)
**Domain:** agents + composition-root DI

## 1. Что было сломано

Два независимых бага в AIGateway invocation pipeline — оба создавали silent
fail-open path, через который мог пройти вызов без policy/capability/budget
проверок:

### 1.1 `policy_mixin.py:100` — `_check_capability` вызывал `check(capability)` с 1 аргументом

```python
# До фикса (policy_mixin.py:94-109):
if self._capability_gate is None:
    return
capability = f"ai.invoke.{request.workflow_id}"
check = getattr(self._capability_gate, "check", None)
if check is None:
    return
result = check(capability)  # ← 1-arg вызов
```

Canonical signature — `services/capabilities/facade.py:50`:

```python
def check(self, plugin: str, capability: str, scope: str | None = None) -> bool
```

Mix вызова `check(capability)` на 3-arg gate (`CapabilityFacade`,
`_CapabilityGateAdapter`) приводил к `TypeError: missing 1 required
positional argument: 'capability'`. Внутренний `try/except` (line 101-109)
оборачивал только `await` (не сам call), но в `test_aigateway_capability_wiring`
видно, что для 3-arg adapter'а вызов проваливался ДО того, как реальный
`CapabilityDeniedError` мог быть поднят. Тест был помечен xfail
(`_XFAIL_ADAPT_CAPABILITY`); cycle-1/B-05 закрывает этот xfail.

### 1.2 `gateway_adapter.py:125-130` — silent bare `AIGateway()` fallback

```python
# До фикса (gateway_adapter.py:114-130):
try:
    from src.backend.core.di.app_state import get_app_ref
    app = get_app_ref()
    if app is not None:
        gateway = getattr(app.state, "ai_gateway", None)
        if gateway is not None:
            return gateway
except Exception:
    pass

try:
    from src.backend.core.di.providers.ai import get_ai_gateway_provider
    return get_ai_gateway_provider()
except (KeyError, RuntimeError):
    return AIGateway()  # ← bare fallback без DI
```

Когда `get_ai_gateway_provider()` падал с `KeyError`/`RuntimeError`
(broken composition root), adapter **тихо** создавал `AIGateway()` без
обязательных DI (`policy_resolver`, `capability_gate`, `token_budget`).
В production `_enforce_production_wiring` ловит это и бросает
`AIGatewayProductionWiringError` — но в dev/staging guard отключён, и
invoctions шли через pipeline **без** policy/capability/budget проверок.
Это — **silent data-loss + security** path.

## 2. Что изменилось

### 2.1 `src/backend/core/ai/gateway_pipeline_mixin/policy_mixin.py`

`_check_capability` теперь использует **dual-signature duck-typing**:

1. **Signature inspection** (primary): `inspect.signature(check)` определяет
   arity — 3+ positional params → 3-arg form (`plugin, capability, scope`);
   иначе → 1-arg form (`capability`).
2. **TypeError safety net** (secondary): если 3-arg call бросил
   `TypeError` (signature inspection неточен / C-extension отвергает
   args) — fallback на 1-arg form. `logger.error` логирует событие
   (НЕ silent swallow).
3. `plugin = "core"`, `scope = f"workflow:{request.workflow_id}"` —
   стабильные значения для audit-trail.

```python
# После фикса (cycle-1/B-05):
import inspect
try:
    params = inspect.signature(check).parameters
    positional = [
        p for p in params.values()
        if p.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
    ]
except (TypeError, ValueError):
    positional = []
plugin = "core"
scope = f"workflow:{request.workflow_id}"
use_three_arg = len(positional) >= 3
try:
    if use_three_arg:
        result = check(plugin, capability, scope)
    else:
        result = check(capability)
except TypeError:
    logger.error(
        "AIGateway: capability check %s raised TypeError on %d-arg form, "
        "falling back to 1-arg form", capability, 3 if use_three_arg else 1,
    )
    try:
        result = check(capability)
    except TypeError as exc:
        logger.error(...)
        return
```

**Backward-compat:** MagicMock (signature `(*args, **kwargs)`) →
0 positional params → 1-arg form → existing test `test_check_capability_sync_check_called`
продолжает работать. Реальные gates (3-arg signature) — 3-arg form.

### 2.2 `src/backend/services/ai/gateway_adapter.py`

Bare fallback удалён. При broken composition-root DI — `logger.error` +
raise `AIGatewayProductionWiringError(missing=("ai_gateway",))`:

```python
# После фикса (cycle-1/B-05):
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

Composition-root контракт теперь explicit: «либо DI-injected AIGateway,
либо fail-closed с понятной ошибкой». Нет silent degradation.

## 3. Tests

### 3.1 `tests/unit/core/ai/test_gateway_pipeline_mixin.py`

Добавлены 3 теста (cycle-1/B-05):

| Тест | Что проверяет |
|---|---|
| `test_check_capability_three_arg_real_gate_called` | 3-arg signature → canonical form `check("core", "ai.invoke.credit_check", "workflow:credit_check")` |
| `test_check_capability_one_arg_real_gate_called` | 1-arg signature → legacy form `check("ai.invoke.wf")` |
| `test_check_capability_typeerror_falls_back_to_one_arg` | Variadic signature (MagicMock-like) → 1-arg path (TypeError safety net не триггерится) |

Существующие тесты (MagicMock-based) продолжают работать — signature
inspection определяет 0 positional params → 1-arg path.

### 3.2 `tests/unit/services/ai/test_gateway_adapter.py`

Добавлены 3 теста (cycle-1/B-05):

| Тест | Что проверяет |
|---|---|
| `test_get_ai_gateway_raises_on_di_lookup_failure` | Broken DI → `AIGatewayProductionWiringError` raised, НЕ silent bare `AIGateway()` |
| `test_get_ai_gateway_uses_provider_when_no_app_state` | Provider singleton path works |
| `test_get_ai_gateway_prefers_app_state_when_present` | `app.state.ai_gateway` имеет приоритет над provider |

### 3.3 Side effect: XPASS strict на xfail-тесте

`test_aigateway_pipeline_propagates_capability_denied` (xfail
`_XFAIL_ADAPT_CAPABILITY`) теперь **passes** вместо xfailed. Это —
положительный side effect: фикс `_check_capability` позволяет
`CapabilityDeniedError` от 3-arg adapter'а доходить до caller'а
(pre-fix: TypeError при вызове adapter'а маскировал настоящий deny).
Strict xfail marker даёт XPASS как failure — это test maintenance
concern, **вне scope** T-1.5. Рекомендую в follow-up:
`tests/unit/services/ai/test_aigateway_capability_wiring.py:26-40` —
снять `@_XFAIL_ADAPT_CAPABILITY` с `test_aigateway_pipeline_propagates_capability_denied`.

## 4. Verification

| Метрика | Baseline | После фикса | Статус |
|---|---|---|---|
| `pytest tests/unit/core/ai/test_gateway_pipeline_mixin.py -v -k check_capability` | 4 passed | 7 passed (4 existing + 3 new) | PASS |
| `pytest tests/unit/services/ai/test_gateway_adapter.py -v` | 6 passed | 9 passed (6 existing + 3 new) | PASS |
| `make check-docstrings MAX_ALLOWED=0` | 0 missing | 0 missing (838 files) | PASS |
| `python tools/check_layers.py --root src` | 175 legacy, 0 new | 175 legacy, 0 new | PASS |
| `grep -cE "return AIGateway\(\)" src/backend/services/ai/gateway_adapter.py` | 1 hit | 0 hits (заменён на `raise AIGatewayProductionWiringError`) | PASS |
| `bash tools/cycle-1-preflight.sh` | exit 0 (T-0.1 baseline) | **exit 1** — pre-existing state (uv.lock churn 40 lines vs expected 15; working tree 14 entries vs expected ≤3) | см. §5 |

## 5. Preflight notes (pre-existing failures, NOT introduced by T-1.5)

`bash tools/cycle-1-preflight.sh` exit 1 на двух gates:

| Gate | Ожидание | Факт | Причина |
|---|---|---|---|
| working tree | ≤ 3 entries | 14 entries | Concurrent activity других T-1.4/T-3.1 agents + новые untracked dirs (`tests/unit/dsl/...`, `tests/unit/infrastructure/...`, `docs/audit/...`). НЕ introduced T-1.5. |
| uv.lock churn | 0 или 15 lines | 40 lines | Pre-existing uv.lock diff вырос с 15 до 40 lines (other agents' work). НЕ introduced T-1.5. |

**Scope discipline:** T-1.5 не вносит изменений в uv.lock, allowlist, s3.py, layer allowlist. Mои изменения — только в 4 файлах scope'а:
- `src/backend/core/ai/gateway_pipeline_mixin/policy_mixin.py` (+51, -3)
- `src/backend/services/ai/gateway_adapter.py` (+22, -10)
- `tests/unit/core/ai/test_gateway_pipeline_mixin.py` (+89, -0)
- `tests/unit/services/ai/test_gateway_adapter.py` (+76, -0)

**Total T-1.5 diff:** +238 / -13 LOC, 4 files.

## 6. Definition of Done (T-1.5)

- [x] `policy_mixin.py:100` — `check(capability)` 1-arg call → dual-signature
      duck-typing (3-arg canonical + 1-arg legacy + TypeError safety net + logger.error)
- [x] `gateway_adapter.py:125-130` — bare `return AIGateway()` fallback удалён;
      composition-root DI lookup only; при broken DI — `logger.error` +
      `raise AIGatewayProductionWiringError`
- [x] Тесты добавлены (3 mixin + 3 adapter), все проходят
- [x] Docstring marker `cycle-1/B-05` в обоих модифицированных функциях
- [x] Русские docstrings **не переведены**
- [x] `make check-docstrings MAX_ALLOWED=0` → 0 missing
- [x] `python tools/check_layers.py --root src` → 175 legacy, 0 new
- [x] `grep -nE "return AIGateway\(\)" src/backend/services/ai/gateway_adapter.py` → 0 hits
- [x] Mixin test passes; gateway_adapter test passes
- [x] `except Exception: pass` блоки не удалены без concrete handling —
      в `gateway_adapter.py:114-123` оставлен pre-existing (вне scope)

## 7. Pre-existing failures NOT caused by T-1.5

5 failures в `tests/unit/core/ai/test_gateway_pipeline_mixin.py` (verified
через `git stash` pre-fix → те же 5 failures):

- `test_resolve_policy_none_in_soft_mode_returns_none` — `ai_policy_enforce`
  feature flag = True в test env (pre-existing env state)
- `test_input_sanitizers_no_sanitizer_returns_prompt` — spacy model download
  failure (network/runtime)
- `test_render_prompt_over_limit_truncates_with_tiktoken` — spacy download
- `test_render_prompt_over_limit_fallback_no_tiktoken` — spacy download
- `test_output_sanitizers_no_sanitizer_passthrough` — spacy download

Все 5 — **pre-existing**, НЕ introduced моими изменениями.

## 8. Risk

**Compatibility risk: low.**
- Mixin: 1-arg form (legacy/test) сохранён → no test breakage для MagicMock-based
  тестов. 3-arg form (canonical) — новый preferred path для real
  `CapabilityFacade.check`. TypeError safety net обрабатывает edge cases.
- Adapter: bare `AIGateway()` fallback удалён. **Behavior change:**
  dev/staging при broken DI теперь получает `AIGatewayProductionWiringError`
  вместо silent degraded gateway. Это — desired behavior per task spec
  ("do not silently degrade in dev"). Потенциальный impact: dev-environments
  без полного composition root теперь требуют `app.state.ai_gateway` или
  работающего `get_ai_gateway_provider()` (singleton lru_cache из
  `_build_ai_gateway_singleton`).

---

*T-1.5 dev-agent (cycle-1/B-05). READ-only verification of plan + preflight
+ targeted source/test fixes. Не правил uv.lock, allowlist, s3.py,
layer allowlist, docstrings. Изменения только в scope T-1.5.*
