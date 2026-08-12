# Phase-5-01-critic — Independent Review of Cycle 6 Phase 4 Artifacts

**Reviewer:** critic (independent)
**Date:** 2026-08-07
**Scope:** Phase-4 cycle-6 artifacts:
- `cycle-6-D-AUDIT-{601..610}-report.md` (10 reports)
- commits `4c0bd0de` + `a360f7a9`

**Method:** Не доверяю developer-отчётам; проверяю артефакты (diff + тесты) против реального
кода через `.venv/bin/python`. Никаких изменений в source, lockfile, allowlist, s3.py,
blue_green, gateway_adapter.py:128-129, cycle 1+2+3+4+5 правок, или коммитов 4c0bd0de/a360f7a9.

---

## TL;DR — VERDICT: **FAIL**

10 из 10 заявленных P0-фиксов корректно реализованы и проходят runtime-тесты.
**Однако** цикл-6 ввёл **критический P0-regression** (`app_factory.py:103`), который:

1. Вызывает **не определённую** функцию `_bootstrap_workflow_registry()` →
   `NameError` при старте приложения (верифицировано runtime).
2. **НЕ упомянут** ни в одном из 10 отчётов (601–610) — нарушение
   integrity контракта отчётности.
3. Содержит лукавый комментарий «B-10 fix (cycle 33)», хотя эта функция
   была удалена в cycle-37 (per `test_replay_registry_cycle33.py` docstring).

Цикл-6 закрывает 10 P0, но **ломает runtime startup** — сделка плохая.

---

## 1. Verification matrix (a–h + tests)

| # | Проверка | Статус | Evidence |
|---|---|---|---|
| (a) | No hidden TODO/FIXME/pass/NotImplemented introduced | ✅ PASS | `grep -rn "TODO\|FIXME\|XXX\|HACK"` → 0 hits in cycle-6 files |
| (a) | NotImplementedError introduced (intentional fail-CLOSED only) | ✅ PASS | 2 случая: `auth_selector.py:183`, `script_runner.py:91` — оба intentional, оба с audit markers |
| (b) | Test-masking vs real runtime | ✅ PASS | 178/178 PASS — все тесты на real runtime (NotImplementedError, ImportError, ValueError, TypeError, 401/403/200, msgpack mock-block, Mongo _FakeMongoClient) |
| (c) | Fallback branches removed (особенно SAML fail-CLOSED) | ✅ PASS | D-AUDIT-601 SAML: `logger.error + raise NotImplementedError` verified `auth_selector.py:177-183`; D-AUDIT-603 pickle: AST scan shows 0 `pickle.{loads,dumps,...}` calls in `data_formats.py` |
| (d) | Docstring markers cycle-6/D-AUDIT-6XX в русских docstrings | ✅ PASS | Все 10 маркеров (601–610) присутствуют в русских docstrings |
| (e) | No new `except Exception: pass` introduced | ✅ PASS | 0 bare `pass` в `except Exception` блоках cycle-6 files; все имеют `logger.warning/error/exception/debug` |
| (f) | Cycle 1+2+3+4+5 правки (15+ atomic commits) НЕ тронуты | ✅ PASS | `git show --name-only 4c0bd0de a360f7a9` показывает только cycle-6 scope files; cycle-1..5 files (agent_sandbox.py, rag_query_stats.py, temporal_worker_runtime.py, backend.py, cache.py, cancel_workflow.py, bluegreen compose, etc.) — не в diff |
| (g) | Forbidden files не тронуты | ⚠️ PARTIAL | s3.py, blue_green.sh, test_blue_green_switch.py — clean; `uv.lock` ТРОНУТ (-16/+1 net, в т.ч. `svcs` removal); `.security/pip-audit-allowlist.txt` — clean (27 active CVE). uv.lock churn reported в D-AUDIT-601 как "pre-existing concurrent work" (consistent с cycle-19 retroactive `0e194233`); но формально в commit a360f7a9 diff — yellow flag |
| (h) | Pre-existing residual gateway_adapter.py:128-129 НЕ тронут | ✅ PASS | `git diff HEAD~2 HEAD -- src/backend/services/ai/gateway_adapter.py` пусто; `except Exception: pass` at 122-123 + AIGatewayProductionWiringError comment at 130 — сохранены |
| Tests | Все 10 target suites | ✅ PASS | 178 PASS, 1 XFAIL (REST endpoint DEFER-2 documented) |

### Тесты (все через `.venv/bin/python`, per task constraint)

| Suite | # | Результат | Команда |
|---|---|---|---|
| D-AUDIT-601 (SAML) | 11 | ✅ 11 PASS | `pytest tests/unit/core/auth/test_auth_selector_saml_fail_closed.py tests/unit/services/auth/` |
| D-AUDIT-602 (ScriptRunner RCE) | 19 | ✅ 19 PASS | `pytest tests/unit/dsl/engine/processors/test_script_runner.py tests/unit/dsl/processors/test_script_runner_rce.py` |
| D-AUDIT-603 (Pickle RCE) | 8 | ✅ 8 PASS | `pytest tests/unit/dsl/engine/processors/test_data_formats_msgpack_rce.py` |
| D-AUDIT-604 (PIIUnmask DI) | 16 | ✅ 16 PASS | `pytest tests/unit/dsl/engine/processors/agent_dsl/test_pii_mask_unmask.py` |
| D-AUDIT-605 (Guardrails DI) | 15 | ✅ 15 PASS | `pytest tests/unit/dsl/engine/processors/agent_dsl/test_guardrails_apply.py` |
| D-AUDIT-606 (AgentMemory tenant) | 7+1 XFAIL | ✅ 7 PASS + 1 XFAIL | `pytest tests/unit/services/ai/agent_memory.py tests/unit/entrypoints/api/v1/endpoints/test_agent_memory_tenant_scope.py` |
| D-AUDIT-607 (HITL permission/tenant) | 3 | ✅ 3 PASS | `pytest tests/unit/entrypoints/api/v1/endpoints/test_hitl.py` |
| D-AUDIT-608 (admin_cron whitelist) | 22 | ✅ 22 PASS | `pytest tests/unit/entrypoints/api/v1/endpoints/test_admin_cron.py` |
| D-AUDIT-609 (SSE principal) | 9 | ✅ 9 PASS | `pytest tests/unit/entrypoints/sse/test_handler_auth_propagation.py` |
| D-AUDIT-610 (outbox+cache) | 78 | ✅ 78 PASS | `pytest tests/unit/infrastructure/messaging/outbox/ tests/unit/infrastructure/cache/rag/test_embedding_cache.py` |
| **TOTAL** | **178+1** | **✅ 178 PASS, 1 XFAIL** | |

1 XFAIL в D-AUDIT-606 — `test_rest_tenant_a_cannot_read_tenant_b_session` —
задокументирован в отчёте 606 как DEFER-2 (REST endpoint facade не извлекает
tenant_id из RequestContext).

---

## 2. Runtime-проверки (не из отчётов, своя верификация)

### 2.1 D-AUDIT-601 (SAML fail-CLOSED) — runtime verified

```python
.venv/bin/python -c "
import asyncio, inspect
from src.backend.core.auth.auth_selector import _verify_saml, verify_request
sig = inspect.signature(_verify_saml)
print('signature:', sig)
# Source: auth_selector.py:177-183 → logger.error + raise NotImplementedError
"
```

✅ Verified:
- `auth_selector.py:147-183` — `logger.error("SAML verification not wired in core auth_selector (cycle-6/D-AUDIT-601 SECURITY-P0-001); ...")` + `raise NotImplementedError("SAML verification not yet wired; use JWT instead")`.
- Cycle-6/D-AUDIT-601 marker присутствует в docstring (lines 156, 167).
- Pre-fix fake cookie/header принимался как валидный principal (CVE-impersonation).
- Post-fix — `NotImplementedError` → `verify_request` ловит в try/except → middleware deny.

### 2.2 D-AUDIT-602 (ScriptRunner RCE) — runtime verified

```bash
$ grep -n "subprocess" src/backend/dsl/engine/processors/script_runner.py
7:  произвольный user-supplied код через ``asyncio.create_subprocess_exec``,
77:        RCE-fix: subprocess-execution удалён. Любой invocation считается
93:            "arbitrary subprocess execution exposes RCE on production routes. "
```

✅ Verified:
- Subprocess execution code REMOVED (only 3 hits — все в docstrings/comments).
- `process()` теперь: `logger.error(...)` + `raise NotImplementedError(...)` (cycle-6/D-AUDIT-602 marker в format string).
- `__init__` и `to_spec` сохранены для backward-compat (builder.py продолжает работать compile-time).

### 2.3 D-AUDIT-603 (Pickle RCE / msgpack) — AST verified

```bash
$ .venv/bin/python -c "
import ast
with open('src/backend/dsl/engine/processors/format_convert/data_formats.py') as f:
    tree = ast.parse(f.read())
for node in ast.walk(tree):
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if isinstance(node.func.value, ast.Name) and node.func.value.id == 'pickle':
            print(f'PICKLE CALL at line {node.lineno}')
"
# → AST scan done (0 hits)
```

✅ Verified:
- 0 вызовов `pickle.{loads,load,dumps,dump}` в `data_formats.py`.
- `_to_msgpack` / `_from_msgpack` используют `try/except ImportError → ImportError("...requires 'msgpack'...")` (тот же паттерн что и `_to_parquet`/`_from_parquet`).
- Cycle-6/D-AUDIT-603 markers в docstring (lines 20, 216, 236).

### 2.4 D-AUDIT-604 (PIIUnmask DI) — runtime verified

```bash
$ .venv/bin/python -c "
from src.backend.core.di.providers.ai import set_pii_tokenizer_provider
from src.backend.dsl.engine.processors.agent_dsl.pii_unmask import PIIUnmaskProcessor

# Reset override
set_pii_tokenizer_provider(None)
print('No provider:', PIIUnmaskProcessor._resolve_tokenizer())  # → None

# With override
class FakeTok:
    async def unmask(self, text, token_map): return text
set_pii_tokenizer_provider(lambda: FakeTok())
print('With provider:', PIIUnmaskProcessor._resolve_tokenizer().__class__.__name__)
"
# → No provider: None
# → With provider: FakeTok
```

✅ Verified:
- `_resolve_tokenizer()` теперь DI resolve, не hardcoded `return None`.
- Cycle-6/D-AUDIT-604 marker в docstring (line 168).
- `except Exception` блок (line 180) имеет `_logger.warning("...resolution failed: %s", exc)` (НЕ silent `pass`).

### 2.5 D-AUDIT-605 (Guardrails DI) — verified

✅ Verified:
- `GuardrailsApplyProcessor._resolve_runtime()` → `get_llm_guard_runtime_provider()` (line 201).
- Provider `get_llm_guard_runtime_provider()` определён в `core/di/providers/ai.py:244-269` с cycle-6/D-AUDIT-605 marker (line 247).
- `__init__.py:42,49` реэкспортирует `get_llm_guard_runtime_provider` / `set_llm_guard_runtime_provider`.
- `except Exception` в provider (line 260) имеет `logging.getLogger(__name__).debug(...)` (НЕ silent).

### 2.6 D-AUDIT-606 (AgentMemory tenant) — runtime verified

```bash
$ .venv/bin/python -c "
import inspect
from src.backend.services.ai.agent_memory import AgentMemoryService
sig = inspect.signature(AgentMemoryService.add_message)
print('add_message:', sig)
print('tenant_id kind:', sig.parameters['tenant_id'].kind)
print('tenant_id default:', sig.parameters['tenant_id'].default)
"
# add_message: (self, session_id: 'str', role: 'str', content: 'str', metadata: 'dict[str, Any] | None' = None, *, tenant_id: 'str') -> 'None'
# tenant_id kind: KEYWORD_ONLY
# tenant_id default: <class 'inspect._empty'>
```

✅ Verified:
- `tenant_id` — `KEYWORD_ONLY` с `default=inspect._empty` (== required, no default).
- `add_message("s", "user", "hi")` → `TypeError: add_message() missing 1 required keyword-only argument: 'tenant_id'`.
- Mongo doc хранит `tenant_id` top-level (line 154); query фильтрует по `(session_id, tenant_id)` (lines 122, 181, 192).
- `_trim_messages` тоже фильтрует по tenant (line 192).
- `memory_gateway.py:113` пробрасывает `tenant_id=tenant_id` в `add_message`.

### 2.7 D-AUDIT-607 (HITL permission/tenant) — verified

✅ Verified:
- `hitl.py:53` — `router = APIRouter(dependencies=[Depends(require_permission("hitl.resolve"))])`.
- `require_permission` (lines 31-50) — 401 при отсутствии auth, 403 при отсутствии permission.
- `_ensure_tenant` (lines 82-90) — cross-tenant access → 403.
- `_request_tenant_id` (lines 67-79) — tenant из auth context, не из query params.
- Cycle-6/D-AUDIT-607 marker в module docstring (line 13).

### 2.8 D-AUDIT-608 (admin_cron whitelist) — runtime verified

✅ Verified:
- `admin_cron.py:89-93` — `ALLOWED_CALLABLE_MODULES = frozenset({"src.backend.infrastructure.scheduler.scheduled_tasks"})`.
- `_resolve_callable` (lines 96-117) — проверка `module_path not in ALLOWED_CALLABLE_MODULES` ДО `importlib.import_module` (line 113). Whitelist-check → `ValueError` (line 109).
- Callable guard (lines 115-116) — non-callable attribute → `ValueError`.
- Cycle-6/D-AUDIT-608 markers в docstring (lines 86, 99).

### 2.9 D-AUDIT-609 (SSE principal/permissions) — verified

✅ Verified:
- `sse/handler.py:179-206` — `_extract_auth_from_request(request)` helper.
- `sse_invoke` (line 241) — `principal, permissions = _extract_auth_from_request(request)`.
- `dispatch_action_or_dsl(...)` (line 247) принимает `principal=principal, permissions=permissions`.
- Default fail-closed: `("", ())` (line 203) при отсутствии auth.
- Cycle-6/D-AUDIT-609 markers в docstring (lines 184, 233).

### 2.10 D-AUDIT-610 (outbox/cache tests) — runtime verified

```bash
$ .venv/bin/python -m pytest tests/unit/infrastructure/messaging/outbox/ tests/unit/infrastructure/cache/rag/test_embedding_cache.py
# → 78 passed, 4 warnings in 5.29s
```

✅ Verified:
- `test_claim_pending.py:30-42` — `_StubSessionManager.transaction(self, _session=None)` matches production `DatabaseSessionManager.transaction(session)` signature.
- `test_claim_pending.py:48-56` — `_stub_sm.get_main_session_manager = lambda *_a, **_kw: ...` factory export.
- `test_per_row_claim_and_sweeper.py:30-53` — те же pattern fixes (per cycle-86 L10).
- `test_embedding_cache.py` уже исправлен в `b3c94fa1` (cycle-5) — файл НЕ тронут cycle-6.

---

## 3. 🚨 CRITICAL FINDING (NOT in cycle-6 reports)

### 3.1 `app_factory.py:103` — undefined function call → `NameError` at startup

**Severity:** P0 (production app cannot start)
**Introduced by:** commit `a360f7a9`
**Reported by:** NONE (silent regression)

#### Diff (от cycle-6 commit a360f7a9)

```diff
diff --git a/src/backend/plugins/composition/app_factory.py b/src/backend/plugins/composition/app_factory.py
@@ -97,6 +97,11 @@ def _configure_application_components(app: FastAPI) -> None:
     if settings.app.monitoring_enabled:
         setup_monitoring(app=app)

+    # B-10 fix (cycle 33): bootstrap Temporal workflow-классов в
+    # WorkflowRegistry — иначе ``TemporalWorkflowBackend.replay()``
+    # не сможет построить ``Replayer`` (Protocol-mismatch str → type).
+    _bootstrap_workflow_registry()
+
```

#### Runtime evidence (CRITICAL FAILURE)

```bash
$ .venv/bin/python -c "
from unittest.mock import MagicMock
from src.backend.plugins.composition.app_factory import _configure_application_components
app = MagicMock(); app.state = MagicMock()
_configure_application_components(app)
"
# Traceback (most recent call last):
#   File "<string>", line 10, in <module>
#     _configure_application_components(app)
#   File "src/backend/plugins/composition/app_factory.py", line 103, in _configure_application_components
#     _bootstrap_workflow_registry()
# NameError: name '_bootstrap_workflow_registry' is not defined
```

```bash
$ grep -rn "_bootstrap_workflow_registry" src/backend/ tests/ | grep -v __pycache__
src/backend/plugins/composition/app_factory.py:103:    _bootstrap_workflow_registry()
tests/unit/infrastructure/workflow/test_replay_registry_cycle33.py:13:B-15 fix (cycle 37): тесты на ``_bootstrap_workflow_registry`` и
```

**Результат:** функция `_bootstrap_workflow_registry` упоминается ТОЛЬКО в
`app_factory.py:103` (call site) и в docstring test'а (удалена в cycle 37).
**В исходниках она не определена НИГДЕ.**

#### Почему это P0

1. **Ломает app startup** — `NameError` raised до того, как FastAPI получает
   жизнеспособное приложение.
2. **НЕ в отчётах 601-610** — нарушение контракта отчётности (все 10 отчётов
   утверждают "all targets PASS", но `app_factory.py:103` НЕ тестируется).
3. **Лукавый комментарий** — "B-10 fix (cycle 33)" — но `_bootstrap_workflow_registry`
   была удалена в `cycle 37` (per `test_replay_registry_cycle33.py:13-16`:
   "тесты на ``_bootstrap_workflow_registry`` и ``_decorator_attr`` удалены
   вместе с самим AST-сканером — ``compile_workflow()`` теперь регистрирует
   класс в ``workflow_registry`` напрямую (см. emitter.py)").

#### Context от cycle-33 B-10 fix (`14e551e2`):

> fix(workflow): replay() Protocol-mismatch → WorkflowRegistry (cycle 33, B-10)

В HEAD `4b5831e4` (cycle-5 final) B-10 fix **уже применён** — `compile_workflow()`
регистрирует в `workflow_registry` напрямую (см. emitter.py per cycle-37 B-15).
Дополнительный `_bootstrap_workflow_registry()` в `app_factory.py` **избыточен**
и **ломает startup**.

#### Что должно быть сделано

**Вариант A (предпочтительный, ponytail):** удалить вызов `_bootstrap_workflow_registry()`
из `app_factory.py:103-106` (5 строк). B-10 fix уже применён через compile_workflow → emitter.

**Вариант B:** если вызов действительно нужен — определить функцию
`_bootstrap_workflow_registry()` (например, через `workflow_registry.bootstrap_from_ast_scanner(...)`),
но **ЗАФИКСИРОВАТЬ в отчёте как D-AUDIT-611**.

**Текущее состояние:** cycle-6 commits `4c0bd0de` + `a360f7a9` содержат
недокументированное изменение, которое ломает production startup. Это
нарушает AGENTS.md: «commit короткий, Russian-first, без эмодзи» + «Атомарные
коммиты (одна логическая правка = один коммит)» — одно изменение размазано
между двумя коммитами без атомарности в отчётности.

---

## 4. Что НЕ проверено (per task scope — НЕ нужно делать)

- Не нужно делать git push
- Не нужно менять source
- Не нужно менять lockfile/allowlist/s3.py/blue_green/gateway_adapter.py:128-129
- Не нужно переписывать cycle 1+2+3+4+5 правки
- Не нужно читать отчёты других ревью-агентов

---

## 5. Что НЕ сделано cycle-6 (residual items, честно)

Per reports 601-610:

| Item | Status | Где задокументировано |
|---|---|---|
| `MemorySaveProcessor.process` (integration.py:96) вызывает `add_message` без `tenant_id` → TypeError | DEFER | D-AUDIT-606 §7 |
| REST endpoint facade `_AgentMemoryFacade` не извлекает tenant_id | DEFER-2 | D-AUDIT-606 §7 |
| `pickle.{loads,load,dumps,dump}` AST regression guard | ADDED | D-AUDIT-603 §5 test #8 |
| `MemorySaveProcessor.process` тесты | NONE | D-AUDIT-606 §7 (out-of-scope) |
| `PIIMaskProcessor._resolve_tokenizer` provider вызывает instance, не factory | Known limitation | D-AUDIT-604 §8.1 |
| SAML SP-side session store полная реализация | DEFER | D-AUDIT-601 §9 |
| `AuthMethod.OIDC` | DEFER (cycle-4 P4-001) | D-AUDIT-601 §9 |

Все residual items явно задокументированы в отчётах — это OK.

---

## 6. Незакрытые пункты (concrete list)

1. **🚨 CRITICAL: `app_factory.py:103` → `NameError: name '_bootstrap_workflow_registry' is not defined`**
   - File: `src/backend/plugins/composition/app_factory.py:103`
   - Fix: удалить 5-строчный блок `B-10 fix (cycle 33): bootstrap ...` (lines 100-106)
   - Альтернатива: добавить `def _bootstrap_workflow_registry()` definition + новый отчёт D-AUDIT-611
2. **`uv.lock` churn `-16/+1` net** — формально в commit a360f7a9 diff, но reports claim "pre-existing concurrent work" (cycle-19 retroactive `0e194233` это сделал). Verified: `uv.lock` имеет 17 line changes в a360f7a9 (включая svcs removal + streamlit version constraint). Reports упоминают это в preflight tables как baseline. Yellow flag — расследовать не blocking, но report-attribution может быть cleanup item для cycle-7.

---

## 7. Summary

| Категория | Count | Notes |
|---|---|---|
| Реализованные P0-фиксы | 10/10 | Все runtime-тесты PASS, все markers в Russian docstrings, no test-masking, no silent `pass` |
| Незакрытый critical regression | 1 | `app_factory.py:103` → `NameError` (NOT in any of 10 reports) |
| Forbidden files touched | 0 | s3.py, blue_green.sh, gateway_adapter.py:128-129 — clean |
| Cycle 1+2+3+4+5 правки тронуты | 0 | agent_sandbox.py, rag_query_stats.py, temporal_worker_runtime.py, etc. — clean |
| Total tests PASS | 178 | +1 XFAIL (documented DEFER-2) |
| Total tests FAIL | 0 | |
| Runtime integrity | ❌ FAIL | `app_factory._configure_application_components(app)` raises `NameError` |

---

## VERDICT: **FAIL**

10 P0-фиксов из reports 601-610 — корректные, протестированы, проходят runtime.
**Однако cycle-6 commits содержат недокументированное изменение** —
`app_factory.py:103` вводит `NameError` при app startup. Это нарушение
integrity контракта отчётности и критический P0 regression.

**Рекомендация:** удалить `_bootstrap_workflow_registry()` call из
`app_factory.py:103-106` (ponytail: B-10 fix уже применён в `compile_workflow` →
`emitter.py` per cycle-37 B-15), или добавить новый отчёт D-AUDIT-611
с определением функции.

---

*Reviewer: critic. HEAD: `4c0bd0de` + `a360f7a9`. Все runtime-проверки через
`.venv/bin/python`. Никаких изменений в source, lockfile, allowlist, s3.py,
blue_green, pre-existing residual gateway_adapter.py:128-129, или 15+ cycle
1+2+3+4+5 uncommitted правок. Не читал отчёты других ревью-агентов.*
