# Phase 5 · Critic Review — cycle-1/B-04, B-05, P3-01

**Дата:** 2026-08-06
**Reviewer:** phase-5-01-critic (independent, read-only)
**Scope:** `cycle-1-B-04-report.md`, `cycle-1-B-05-report.md`, `cycle-1-P3-01-report.md` + diffs vs HEAD + tests + actual source code.
**Output:** `docs/audit/swarm-2026-08-06/cycle-1/phase-5-01-critic.md`
**Method:** Не доверяю developer-отчётам — проверяю артефакты (diff+тесты) против реального кода в `.venv/bin/python -m pytest` / `git diff HEAD` / `grep`.

---

## TL;DR — Verdict

**VERDICT: PASS with one documented FAIL on constraint (e)**

| Constraint | Статус |
|---|---|
| (a) no hidden TODO/FIXME/pass/NotImplemented introduced | **PASS** |
| (b) tests cover the actual fix rather than mocking the path | **PASS** |
| (c) fallback branches removed or explicitly justified | **PASS** (с pre-existing justification) |
| (d) docstring marker `cycle-1/B-04`, `cycle-1/B-05`, `cycle-1/P3-01` в русских docstrings без translation | **PASS** |
| (e) no `except Exception: pass` left | **FAIL** — pre-existing `except Exception: pass` в `gateway_adapter.py:128-129` НЕ удалён |

**Все 3 dev-отчёта (B-04, B-05, P3-01) grounded в реальном коде**, кроме одного конкретного пункта: pre-existing `except Exception: pass` оставлен в `gateway_adapter.py:128-129` (dev явно justified в §6 B-05, но constraint (e) строже).

---

## Методология проверки

1. Прочитал все 3 dev-отчёта (`cycle-1-B-04-report.md`, `cycle-1-B-05-report.md`, `cycle-1-P3-01-report.md`).
2. Прочитал реальные исходные файлы (modified по dev-отчётам) целиком.
3. Прочитал реальные test-файлы целиком.
4. Сравнил `git diff HEAD` против заявленных изменений.
5. Прогнал pytest с `.venv/bin/python` (Python 3.14.0) на каждом из 3 task-scope'ов.
6. Прогнал `make check-docstrings MAX_ALLOWED=0` — gate PASS.
7. Прогнал `ruff check` на всех модифицированных source/test файлах — PASS.
8. Grep по `TODO/FIXME/HACK/NotImplemented/pass` и `except Exception: pass` во всех модифицированных файлах.

---

## B-04 — DSL Multicast TypeError + Python-2 syntax

### Что проверил

**Источник бага:**
- `multicast.py:172` — `ExecutionEngine(route_registry=route_registry)` → TypeError.
- `redelivery_policy.py:145` — Python-2 `except TypeError, ValueError:` → SyntaxError.

**Реальный код после фикса (verified):**

`src/backend/dsl/engine/processors/eip/routing/multicast.py:172-176`:
```python
# cycle-1/B-04: ExecutionEngine.__init__ принимает только
# (middleware, validate_before_execute, pool); ``route_registry`` —
# module-level lookup, не kwarg. Конструктор без аргументов
# использует default MiddlewareChain + ProcessorPool.
engine = ExecutionEngine()
```

`src/backend/dsl/engine/processors/eip/reliability/redelivery_policy.py:143-148`:
```python
try:
    attempt = int(attempt_raw) + 1
# cycle-1/B-04: Python-3 syntax; Py2 ``except TypeError, ValueError``
# — SyntaxError на 3.14 (фикс переоткрытия парсинга `attempt_raw`).
except (TypeError, ValueError):
    attempt = 1
```

**Verification commands + exit codes:**
```
.venv/bin/python -m pytest tests/unit/dsl/engine/processors/eip/routing/test_multicast.py \
                    tests/unit/dsl/engine/processors/eip/reliability/test_redelivery_policy.py -v
============================== 15 passed in 3.28s ==============================
exit: 0
```

```
.venv/bin/python -c "import ast; ast.parse(open('src/backend/dsl/engine/processors/eip/reliability/redelivery_policy.py').read())"
exit: 0
```

```
.venv/bin/python -c "import src.backend.dsl.engine.processors.eip.routing.multicast"
exit: 0
```

### Constraint checks

| (a) TODO/FIXME/HACK/NotImplemented introduced | PASS — `grep -nE "TODO|FIXME|XXX|HACK|NotImplemented" multicast.py redelivery_policy.py` → 0 hits. |
|---|---|
| (b) tests cover actual fix, not mock the path | **PASS** — тесты `test_multicast.py` собирают **реальный** `RouteRegistry` + **реальные** `Pipeline` (line 61-74 `_build_registry_with_routes`), патчат только module-level `route_registry` lookup (line 118 `patch("src.backend.dsl.commands.registry.route_registry", registry)`); `ExecutionEngine()` создаётся без mock (line 98). Тесты `test_redelivery_policy.py` напрямую инстанцируют `RedeliveryPolicyProcessor` (line 46, 75, 91, 101) и проверяют реальное поведение через `process()`. |
| (c) fallback branches removed/justified | **PASS** — никаких new fallback branches не введено. |
| (d) docstring marker `cycle-1/B-04` в русских docstrings без translation | **PASS** — markers at `multicast.py:172` (comment в коде), `redelivery_policy.py:145` (comment в коде); тестовые файлы `test_multicast.py:1,16,80` и `test_redelivery_policy.py:1,15,71,87` содержат маркер в русских docstrings. Все docstrings остались на русском. |
| (e) no `except Exception: pass` | **PASS** — `multicast.py:62,193` и `redelivery_policy.py` — нет bare `except Exception: pass` ни introduced, ни pre-existing в scope B-04. |

### Verdict B-04: PASS

All 5 constraints satisfied. Source diff (10 LOC: 5 ins + 1 del в `multicast.py`, 3 ins + 1 del в `redelivery_policy.py`) совпадает с реальным кодом. Tests (15: 6+9) реально покрывают фикс.

---

## B-05 — AIGateway capability TypeError + bare fallback

### Что проверил

**Источник бага:**
- `policy_mixin.py:100` — `check(capability)` 1-arg вызов, canonical signature `check(plugin, capability, scope)`.
- `gateway_adapter.py:125-130` — silent bare `AIGateway()` fallback при broken composition-root DI.

**Реальный код после фикса (verified):**

`src/backend/core/ai/gateway_pipeline_mixin/policy_mixin.py:84-150` (excerpt):
```python
async def _check_capability(self, request: AIRequest) -> None:
    """Шаг 2: CapabilityGate intercept.
    
    cycle-1/B-05: dual-signature duck-typing — canonical
    :meth:`CapabilityFacade.check` (3-arg: ``plugin, capability, scope``)
    ...
    """
    if self._capability_gate is None:
        return
    capability = f"ai.invoke.{request.workflow_id}"
    check = getattr(self._capability_gate, "check", None)
    if check is None:
        return
    # cycle-1/B-05: duck-type signature; canonical 3-arg form is
    # ``check(plugin, capability, scope)`` (per CapabilityFacade).
    import inspect
    try:
        params = inspect.signature(check).parameters
        ...
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
        # cycle-1/B-05: signature lied or C-extension rejects 3-arg;
        # fallback на legacy 1-arg form.
        logger.error(...)
        try:
            result = check(capability)
        except TypeError as exc:
            logger.error(...)
            return
    try:
        if inspect.isawaitable(result):
            await result
    except Exception as exc:                          # PRE-EXISTING
        logger.debug(...)                              # — has concrete handling
```

`src/backend/services/ai/gateway_adapter.py:131-142`:
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

### Verification commands + exit codes

```
.venv/bin/python -m pytest tests/unit/core/ai/test_gateway_pipeline_mixin.py -k check_capability -v
======================= 7 passed, 46 deselected in 0.24s ======================
exit: 0
```

```
.venv/bin/python -m pytest tests/unit/services/ai/test_gateway_adapter.py -v
============================== 9 passed in 0.33s ==============================
exit: 0
```

```
.venv/bin/python -m pytest tests/unit/dsl/engine/processors/eip/routing/test_multicast.py \
                    tests/unit/dsl/engine/processors/eip/reliability/test_redelivery_policy.py \
                    tests/unit/services/ai/test_gateway_adapter.py \
                    tests/unit/infrastructure/cache/rag/test_embedding_cache.py --tb=no -q
================================== 34 passed in 2.00s ==============================
exit: 0
```

```
grep -nE "return\s+AIGateway\(\)" src/backend/services/ai/gateway_adapter.py
exit: 1   (no hits — bare AIGateway() fallback УДАЛЁН, как заявлено)
```

### Pre-existing failures verification

5 failures в `test_gateway_pipeline_mixin.py` при full test run:
- `test_resolve_policy_none_in_soft_mode_returns_none` — `ai_policy_enforce=True` в test env (verified).
- `test_input_sanitizers_no_sanitizer_returns_prompt` — spacy model `ru_core_news_lg` не установлен (verified на clean HEAD через `git stash`: same failure).
- `test_render_prompt_over_limit_truncates_with_tiktoken` — same spacy issue.
- `test_render_prompt_over_limit_fallback_no_tiktoken` — same spacy issue.
- `test_output_sanitizers_no_sanitizer_passthrough` — same spacy issue.

**Confirmed pre-existing**, NOT introduced B-05. Совпадает с заявлением в §7 B-05 отчёта.

### Constraint checks

| (a) TODO/FIXME/HACK/NotImplemented introduced | **PASS** — 0 hits в `policy_mixin.py` и `gateway_adapter.py`. |
|---|---|
| (b) tests cover actual fix | **PASS** — новые tests используют **реальные** классы `_Real3ArgGate` (test_gateway_pipeline_mixin.py:296), `_Real1ArgGate` (line 320), `_VariadicGate` (line 350), не MagicMock для новых 3-arg/1-arg fallback tests. Для adapter — `monkeypatch.setattr` подменяет `get_app_ref` и `get_ai_gateway_provider` (test_gateway_adapter.py:214,220), вызывает реальный `get_ai_gateway()` (line 225). |
| (c) fallback branches removed/justified | **PASS** — bare `return AIGateway()` УДАЛЁН (verified: 0 hits в grep). Pre-existing `except Exception: pass` для `app.state` lookup явно justified в B-05 §6 ("оставлен pre-existing (вне scope)"). |
| (d) docstring marker `cycle-1/B-05` в русских docstrings | **PASS** — markers в `policy_mixin.py:87` (docstring `_check_capability`), `policy_mixin.py:108,134` (комментарии в коде), `gateway_adapter.py:103` (docstring `get_ai_gateway` — на русском). Тесты: `test_gateway_pipeline_mixin.py:289,318,342`, `test_gateway_adapter.py:201,232,253` — все в русских docstrings. |
| (e) no `except Exception: pass` left | **FAIL** — см. детали ниже. |

### Constraint (e) — конкретный FAIL

**Location:** `src/backend/services/ai/gateway_adapter.py:128-129`

**Verification:**
```python
grep -nE "except\s+Exception\s*(?:as\s+\w+\s*)?:\s*\n\s*pass" \
     src/backend/services/ai/gateway_adapter.py
src/backend/services/ai/gateway_adapter.py:128:    except Exception:
src/backend/services/ai/gateway_adapter.py:129:        pass
```

**Context (lines 120-129):**
```python
try:
    from src.backend.core.di.app_state import get_app_ref
    app = get_app_ref()
    if app is not None:
        gateway = getattr(app.state, "ai_gateway", None)
        if gateway is not None:
            return gateway
except Exception:                 # ← STILL PASS
    pass
```

**Pre-existing verification (через `git show HEAD:src/backend/services/ai/gateway_adapter.py`):**
- HEAD lines 119-125 (pre-fix): точно такой же `except Exception: pass` блок для `app.state.ai_gateway` lookup.
- **Confirmed pre-existing**, NOT introduced by B-05.

**Dev justification (B-05 §6):**
> "`except Exception: pass` блоки не удалены без concrete handling — в `gateway_adapter.py:114-123` оставлен pre-existing (вне scope)"

**Conflict with constraint (e):**
- Constraint (c) позволяет оставить fallback branch **если explicitly justified** → dev provided justification.
- Constraint (e) формулировка: "no `except Exception: pass` left" — **строгое** (без слова "introduced" как в (a)).
- Литературное чтение: 1 блок `except Exception: pass` всё ещё present в modified file → **FAIL на (e)**.

**Concrete risk:** `app.state.ai_gateway` lookup молча проглатывает **любое исключение** (`ImportError`, `AttributeError`, `RuntimeError`). Это silent fail-open path при broken DI — security concern, особенно учитывая что B-05 fix убирает аналогичный silent path ниже (для `get_ai_gateway_provider`).

**Рекомендация:** заменить `except Exception: pass` на конкретные исключения:
```python
except (ImportError, AttributeError, RuntimeError) as exc:
    _logger.debug("app.state.ai_gateway lookup skipped: %s", exc)
```

### Verdict B-05: FAIL (on constraint e)

Сам по себе fix правильный: dual-signature duck-typing с proper 3-arg form + TypeError safety net + logger.error; bare `AIGateway()` fallback удалён с `logger.error` + `raise AIGatewayProductionWiringError`. Тесты реальные, docstring markers в русских docstrings, no TODO/FIXME introduced.

**Однако**: pre-existing `except Exception: pass` (lines 128-129) — это FAIL на constraint (e) "no `except Exception: pass` left". Dev justified в §6 (pre-existing, out of scope), но constraint (e) строже — буквальный запрет.

---

## P3-01 — replace custom TTL+LRU with `cachetools.TTLCache`

### Что проверил

**Источник бага:**
- `embedding_cache.py` — custom dict + manual LRU через `next(iter(self._store))` + `time.monotonic()` TTL.
- 64 LOC → заменено на `cachetools.TTLCache` (уже в core deps).

**Реальный код после фикса (verified) — `src/backend/infrastructure/cache/rag/embedding_cache.py` целиком (54 LOC):**

```python
"""In-process TTL+LRU cache for embedding vectors (Sprint 86, cycle-1/P3-01).
...
"""
from __future__ import annotations
import asyncio
import hashlib
from cachetools import TTLCache
__all__ = ("EmbeddingVectorCache",)

class EmbeddingVectorCache:
    """Async-safe in-process cache for query → embedding vector with TTL+LRU."""

    def __init__(self, ttl_seconds: float = 300.0, maxsize: int = 1024) -> None:
        # ponytail: TTLCache сам делает TTL-eviction (через __getitem__) + LRU.
        self._cache: TTLCache[str, list[float]] = TTLCache(
            maxsize=maxsize, ttl=ttl_seconds
        )
        self._lock = asyncio.Lock()

    @staticmethod
    def _key(query: str) -> str:
        return hashlib.sha256(query.encode("utf-8")).hexdigest()

    async def get(self, query: str) -> list[float] | None:
        key = self._key(query)
        async with self._lock:
            try:
                return list(self._cache[key])
            except KeyError:
                return None

    async def set(self, query: str, vector: list[float]) -> None:
        key = self._key(query)
        async with self._lock:
            self._cache[key] = list(vector)
```

### Verification commands + exit codes

```
.venv/bin/python -m pytest tests/unit/infrastructure/cache/rag/test_embedding_cache.py -v
============================== 10 passed in 0.96s ==============================
exit: 0
```

```
grep -nE "from cachetools import" src/backend/infrastructure/cache/rag/embedding_cache.py
src/backend/infrastructure/cache/rag/embedding_cache.py:14:from cachetools import TTLCache
exit: 0
```

```
git diff --numstat uv.lock
0	15	uv.lock        # 15 deletions — pre-existing (per PREFLIGHT-REPORT.md §1)
```

```
grep -cE "^CVE-|^GHSA-|^PYSEC-" .security/pip-audit-allowlist.txt
35                     # no growth — 35 → 35 (per B-05 report §6 compliance table)
```

```
git status --short src/backend/infrastructure/storage/s3.py
                        # empty — s3.py НЕ modified
```

```
make check-docstrings MAX_ALLOWED=0
Total: 0 missing docstrings in 0 files
Files scanned: 838
docstring policy OK
exit: 0
```

### Constraint checks

| (a) TODO/FIXME/HACK/NotImplemented introduced | **PASS** — 0 hits в `embedding_cache.py`. |
|---|---|
| (b) tests cover actual fix | **PASS** — тесты `test_embedding_cache.py` используют **реальный** `EmbeddingVectorCache` (не мок): 10 tests (TTL expiration line 46, LRU eviction line 56, maxsize overflow line 68, concurrent access line 98). |
| (c) fallback branches removed/justified | **PASS** — `try/except KeyError` в `get()` имеет concrete handling (`return None`); `try/except StopIteration` (в старом коде) удалён вместе с заменой на TTLCache. |
| (d) docstring marker `cycle-1/P3-01` в русских docstrings | **PASS** — marker at `embedding_cache.py:1` (module docstring на русском: "...заменили custom dict + ``time.monotonic()`` + ручной LRU на ``cachetools.TTLCache``..."). Тест файл `test_embedding_cache.py:1` содержит маркер в docstring. |
| (e) no `except Exception: pass` | **PASS** — `grep` показывает 0 hits в `embedding_cache.py`. |

### Verdict P3-01: PASS

Все 5 constraints satisfied. Source diff (50 lines: 20 ins, 30 del) — реальный rewrite на `cachetools.TTLCache`. Tests (10) реальные, не мокают. Docstring marker в русском module docstring. uv.lock НЕ растёт. s3.py untouched. allowlist 35 = 35.

---

## Cross-cutting evidence

### Diff stat (modified files в scope Phase 4):

```
src/backend/dsl/engine/processors/eip/reliability/redelivery_policy.py | 4 +++-
src/backend/dsl/engine/processors/eip/routing/multicast.py              | 6 +++++-
src/backend/core/ai/gateway_pipeline_mixin/policy_mixin.py              | 54 ++-
src/backend/services/ai/gateway_adapter.py                             | 32 +-
src/backend/infrastructure/cache/rag/embedding_cache.py                 | 50 +-
tests/unit/dsl/engine/processors/eip/routing/test_multicast.py          | (new, 226 lines)
tests/unit/dsl/engine/processors/eip/reliability/test_redelivery_policy.py | (new, 167 lines)
tests/unit/core/ai/test_gateway_pipeline_mixin.py                       | 89 new (3 new tests)
tests/unit/services/ai/test_gateway_adapter.py                          | 76 new (3 new tests)
tests/unit/infrastructure/cache/rag/__init__.py                         | (new, 0 bytes)
tests/unit/infrastructure/cache/rag/test_embedding_cache.py             | (new, 132 lines)
```

### Files NOT in Phase 4 scope (но modified в working tree):

```
tests/unit/tools/test_blue_green_switch.py | 410 +++++++++++++--------
tools/blue_green.sh                         |  29 +-
uv.lock                                    |  15 deletions
```

Эти изменения НЕ относятся к B-04/B-05/P3-01 (это `D-AUDIT-C-W3.6`, Sprint 183 W3 / `D-LESSON-11`). Verified pre-existing modifications, НЕ introduced текущими cycle-1 задачами. **Вне scope моего review.**

### Files НЕ modified (per task constraints):

```
src/backend/infrastructure/storage/s3.py                 — UNTOUCHED ✓
.security/pip-audit-allowlist.txt                        — UNTOUCHED ✓ (35 → 35)
```

---

## Concrete FAIL items list

| # | Item | File | Line(s) | Severity |
|---|---|---|---|---|
| 1 | `except Exception: pass` block остался (constraint (e) violated) | `src/backend/services/ai/gateway_adapter.py` | 128-129 | **MEDIUM** — pre-existing, dev justified в §6, но constraint (e) запрещает literally |

**Note:** Dev explicitly justified this в B-05 §6 ("pre-existing, вне scope"). Если constraint (e) интерпретируется как "no NEW `except Exception: pass` introduced" (parallel с constraint (a) про TODO/FIXME), то FAIL снимается. Если literal — остаётся FAIL.

**Recommendation:** Заменить на конкретные исключения:
```python
except (ImportError, AttributeError, RuntimeError) as exc:
    _logger.debug("app.state.ai_gateway lookup skipped: %s", exc)
```
Это устранит FAIL и закроет silent fail-open path при broken DI (особенно в dev/staging где guard отключён).

---

## Summary verdict для parent agent

**VERDICT: PASS with one documented FAIL on (e).**

3 dev-отчёта (B-04, B-05, P3-01) **grounded в реальном коде**:
- B-04: 15 tests pass, no hidden markers, real Engine/Pipeline used, docstring markers в русских docstrings.
- B-05: 7 check_capability + 9 gateway_adapter tests pass (4 pre-existing failures в test_gateway_pipeline_mixin.py confirmed not introduced), real classes для новых tests, docstring markers в русских docstrings, bare `return AIGateway()` удалён.
- P3-01: 10 tests pass, real `EmbeddingVectorCache` used, cachetools.TTLCache import verified, docstring marker в русском module docstring, uv.lock/allowlist/s3.py untouched.

**Один concrete FAIL**: pre-existing `except Exception: pass` в `gateway_adapter.py:128-129` — нарушает literal interpretation constraint (e). Pre-existing, dev justified, но constraint строже.

**Дополнительные observations (НЕ FAIL):**
- 5 pre-existing test failures в `test_gateway_pipeline_mixin.py` (spacy model missing + feature_flag env state) — НЕ introduced, но блокируют full test run. Dev documented в §7.
- Pre-existing modifications в `tests/unit/tools/test_blue_green_switch.py` + `tools/blue_green.sh` (S183 W3) — вне scope моего review.
- Diff stat mismatch: B-04 report claims "8 source-изменений (4+4)" but actual diff is 4+6=10 changed lines. Cosmetic counting difference, не critical.

**Verdict для downstream reviewers:** B-04 и P3-01 можно считать closed. B-05 — closed после замены `except Exception: pass` на конкретные исключения (5-минутный fix, ~3 LOC).

**Report path:** `/home/user/dev/gd_integration_tools/docs/audit/swarm-2026-08-06/cycle-1/phase-5-01-critic.md`
