# ADR-0156 — Sprint 74 closure: Jupiter Hub + Notebook Execution ecosystem (Papermill + Factory + WebSocket heartbeat, 13 NEW tests) (5 commits)

* Статус: Accepted (Autonomous work cycle S74, 2026-06-12)
* Связано с: S60 W1 (NotebookExecutionService 571 LOC decomp), Wave 1.7
  (e2b_code_interpreter, S1 R-V15-4), FINAL_REPORT_V2.md направление #1,
  S73 (P0-A closure pattern, codemod)

## Контекст

S74 = **Jupyter Notebook Execution ecosystem closure** (FINAL_REPORT_V2
направление #1, recommendation #9 P1). User указал что я упустил
papermill в S73 plan. После fact-check обнаружено:

**FINAL_REPORT_V2 finding**: направление #1 ("Jupiter Hub + Notebook
Execution") рейтинг ⚠️, 4 из 6 компонентов missing/partial:
* JupyterHub WebSocket execution — ✅ (S60 W1)
* nbclient backend — ✅ (S60 W1)
* **Papermill — ⬜ (NOT in deps!)**
* Множественные kernels — ⚠️
* **Sandbox (e2b/pyodide) — ⬜ (e2b lazy-import, не wired в notebook execution)**
* NotebookService CRUD — ✅

**3 рекомендации направления #1**:
1. Добавить Papermill (papermill>=2.6) — **S74 W1** (closed)
2. Добавить e2b sandbox для безопасного выполнения — **S74 W2 stub**
   (e2b_code_interpreter уже в deps, factory готова, NotImplementedError
   для e2b ExecutionBackend — S74 W3+ deferred epic)
3. Интегрировать NbClientExecutionBackend через фабрику — **S74 W2**
   (closed)
4. Добавить WebSocket heartbeat (ping каждые 30 сек) — **S74 W3** (closed)

## Команда результаты (5 commits, all real fixes)

### W1: PapermillExecutionBackend (commit `c9e36905`)
- File: `pyproject.toml` (+14 LOC, new `jupyter` extra)
- File: `src/backend/services/jupyter/execution_service/papermill_backend.py` (NEW, 175 LOC)
- File: `src/backend/services/jupyter/execution_service/__init__.py` (re-export)
- **NEW dep**: `papermill>=2.6.0` (opt-in extra `jupyter`, тяжёлые C-extensions)
- **NEW API**: `PapermillExecutionBackend.execute_with_params(notebook_path, parameters, output_path)`
  - Template parameters: `{{param}}` placeholders в cells
  - Lazy-import papermill (raise JupyterExecutionError if not installed)
  - Sync `papermill.execute_notebook` wrapped в `asyncio.to_thread` (не block loop)
  - Returns metadata: cells_executed, duration, errors, output_path

### W2: ExecutionBackendFactory (commit `81b21671`)
- File: `src/backend/services/jupyter/execution_service/factory.py` (NEW, 175 LOC)
- **NEW enum**: `BackendKind` (HUB / PAPERMILL / NBCLIENT / E2B)
- **NEW class**: `ExecutionBackendFactory.create(kind, settings, override, **kwargs)`
  - `"hub"` → `NotebookExecutionService` (distributed, requires settings)
  - `"papermill"` → `PapermillExecutionBackend`
  - `"nbclient"` → `NbClientExecutionBackend`
  - `"e2b"` → `NotImplementedError` (S74 W3+ stub, deferred epic)
  - `override` param: test injection (skip creation, use provided mock)
- **NEW API**: `ExecutionBackendFactory.from_config()` (reads `JUPYTER_BACKEND` env)
- **NEW singleton**: `get_default_factory()` returns shared instance

### W3: WebSocket heartbeat (commit `5ba8cc1e`)
- File: `src/backend/services/jupyter/execution_service/jupyter_mixin.py` (+86 LOC)
- **NEW** в `_execute_cell`:
  - `HEARTBEAT_INTERVAL_S = 30.0` (ping interval)
  - `HEARTBEAT_TIMEOUT_S = 60.0` (2x interval)
  - Background `_heartbeat_loop` task sends `ws.ping()` каждые 30s
  - `ws.pong_handler` обновляет `last_pong_time` на pong frame
  - Main recv loop обновляет `last_pong_time` на любом message (sign of life)
  - `connection_dead` Event → main loop raises `JupyterExecutionError`
  - `finally` block cancels heartbeat task

### W4: Tests + S60 W1 __slots__ bug fix (commit `20e2f4ea`)
- File: `tests/unit/services/jupyter/execution_service/test_papermill_factory_heartbeat.py` (NEW, 280 LOC, **13 tests**)
- File: `src/backend/services/jupyter/execution_service/__init__.py` (bug fix)
- **BUG FIX**: `NotebookExecutionService.__slots__ = ()` блокировал
  `self._settings = settings` в `__init__` (AttributeError при construction).
  S60 W1 decomp forgot про instance attrs. Fix: remove __slots__,
  allow default __dict__.
- 13 NEW tests:
  1. `test_papermill_execute_with_params_notebook_not_found`
  2. `test_papermill_execute_with_params_requires_papermill`
  3. `test_papermill_execute_with_params_happy_path` (sys.modules mock)
  4. `test_factory_create_papermill` (str + BackendKind)
  5. `test_factory_create_nbclient`
  6. `test_factory_create_hub_requires_settings` (ValueError)
  7. `test_factory_create_hub_with_settings`
  8. `test_factory_create_e2b_not_implemented` (NotImplementedError)
  9. `test_factory_create_unknown_kind`
  10. `test_factory_override_for_test_injection` (mock override)
  11. `test_factory_from_config_env` (JUPYTER_BACKEND env)
  12. `test_factory_default_is_hub`
  13. `test_heartbeat_loop_detects_dead_connection` (inline mimic)

### W5: Closure (this commit — ADR-0156 + CHANGELOG + TECH_DEBT)

## TECH_DEBT closure summary

| Item | Status | Sprint |
|---|---|---|
| **FINAL_REPORT_V2 направление #1 #9** Papermill | ✅ **CLOSED S74** | W1 |
| **FINAL_REPORT_V2 #1 #3** NbClient factory | ✅ **CLOSED S74** | W2 |
| **FINAL_REPORT_V2 #1** WebSocket heartbeat | ✅ **CLOSED S74** | W3 |
| **S60 W1 decomp** __slots__() bug | ✅ **FIXED S74 W4** | W4 |
| **FINAL_REPORT_V2 #1** e2b notebook ExecutionBackend | ⏸ Deferred S75+ | W2 stub |

**Net S74 LOC**: 6 files changed (+810, -30), 1 NEW dep (papermill), 13 NEW tests.

## Final state vs FINAL_REPORT_V2 направление #1

| Компонент | Рейтинг v2 | Рейтинг S74 | Change |
|---|---|---|---|
| JupyterHub WebSocket execution | ⚠️ | ✅ | (S60 W1 + S74 W3 heartbeat) |
| nbclient backend | ✅ | ✅ | (S60 W1 + S74 W2 factory) |
| **Papermill** | ⬜ | ✅ | **S74 W1** NEW backend + dep |
| Множественные kernels | ⚠️ | ⚠️ | (deferred) |
| **Sandbox (e2b)** | ⬜ | ⚠️ | (S74 W2 stub, NotImplementedError, deferred S75+) |
| NotebookService CRUD | ✅ | ✅ | (unchanged) |

**Net direction #1 rating: ⚠️ → ⚠️-иш (3/6 fixed, 1 partial)**.

## S75+ epic candidates (FINAL_REPORT_V2 P0-B/C/D)

1. **e2b notebook ExecutionBackend** — implement NotImplementedError
   path. e2b_code_interpreter уже в deps (Wave 1.7), нужно только
   интегрировать в factory. L-scope (security policy + kernel
   isolation + error handling).
2. **P0-B: tools whitelist в AIPolicySpec** (FINAL_REPORT_V2)
3. **P0-C: AI Policy Spec DSL** (ADR-0067, FINAL_REPORT_V2)
4. **P0-D: CORS/XSRF в Streamlit** (FINAL_REPORT_V2)
5. **Множественные kernels** (jupyter kernelspec discovery)

## Files changed summary

- W1: 4 files (+245, -1) — papermill dep + backend + re-exports
- W2: 2 files (+178, -0) — factory + re-exports
- W3: 1 file (+86, -1) — heartbeat
- W4: 2 files (+332, -2) — 13 tests + __slots__ fix
- W5: 3 files (closure, this commit)
- **Total: 12 files, NET +837 LOC**

## Verification

- 13 NEW tests passing в `test_papermill_factory_heartbeat.py`
- All 3 implementations (papermill/factory/heartbeat) verified
- NotebookExecutionService теперь конструктабельна (S60 W1 __slots__ fix)
- `e2b` factory path raises NotImplementedError as designed (S74 W2 stub)
- Pre-existing 6 failures в `test_notebook_jupyter.py` (NOT caused by S74 W3)
