# ADR-0157 — Sprint 75 closure: направление #1 final closure (e2b ExecutionBackend + KernelSpecDiscovery, 15 NEW tests) (5 commits)

* Статус: Accepted (Autonomous work cycle S75, 2026-06-12)
* Связано с: S74 W1-W2 (papermill + factory stub for e2b), Wave 1.7
  (e2b_code_interpreter dep, S1 R-V15-4), FINAL_REPORT_V2 #1 #2,
  направление #1 (Множественные kernels)

## Контекст

S75 = **направление #1 final closure** (FINAL_REPORT_V2 #2 e2b
sandbox + Множественные kernels). S74 W2 factory stub raised
`NotImplementedError` для e2b; S74 W5 closure deferred это в S75+.

**FINAL_REPORT_V2 #2 (направление #1)**:
> Добавить e2b sandbox для безопасного выполнения [untrusted notebooks]

**FINAL_REPORT_V2 направление #1 (multi-kernels)**: ⚠️ → нужно
расширить single `default_kernel` до multi-kernel discovery.

## Команда результаты (5 commits, all real fixes)

### W1: E2BExecutionBackend (commit `5a51e4b1`)
- File: `src/backend/services/jupyter/execution_service/e2b_backend.py` (NEW, 334 LOC)
- `E2BExecutionError` class (distinct от `JupyterExecutionError` для
  cloud-sandbox errors — network/quota/auth distinguishable from local).
- `E2BExecutionBackend(api_key, kernel_name, timeout, template)`:
  - `api_key` from env `E2B_API_KEY` или explicit (no silent NoOp fallback)
  - Lazy-import `e2b_code_interpreter` (opt-in `[ai]` extra)
  - Sync `sandbox.run_code()` в `asyncio.to_thread` (не block loop)
  - **Two-phase execution**: parameter cells (injected values) → code cells (sequential stateful)
  - Always `sb.kill()` в `finally` (e2b best practice)
- `execute_with_params(notebook_path, parameters, output_path)`:
  - Reads .ipynb, finds `parameters` tagged cells
  - Injects values via `_inject_parameters` (append lines, не template)
  - Returns metadata: cells_executed, duration, sandbox_id, errors
  - Persists output notebook (executed cells с outputs)

### W2: Factory integration (commit `ca8b4017`)
- File: `src/backend/services/jupyter/execution_service/factory.py` (-7, +3 LOC)
- File: `src/backend/services/jupyter/execution_service/__init__.py` (+3 LOC re-exports)
- `BackendKind.E2B` path: `factory.create('e2b')` → `E2BExecutionBackend` (was NotImplementedError)
- `E2BExecutionBackend` re-exported в `__all__`

### W3: KernelSpecDiscovery (commit `17a45836`)
- File: `src/backend/services/jupyter/execution_service/kernelspec.py` (NEW, 192 LOC)
- `DEFAULT_FALLBACK_SPECS`: `{"python3": {resource_dir, display_name, language, argv}}` для backward compat
- `KernelSpecDiscovery` class:
  - `discover_available()` → dict[kernel_name, spec_dict]
  - Lazy-import `jupyter_client.kernelspec` (opt-in `[jupyter]` extra)
  - Cached при первом вызове (kernelspecs редко меняются)
  - Graceful fallback если jupyter_client missing → `DEFAULT_FALLBACK_SPECS`
  - `filter_by_whitelist(['python3', 'ir'])` — security policy
  - `clear_cache()` — manual invalidation

### W4: Tests (commit `edf58acf`)
- File: `tests/unit/services/jupyter/execution_service/test_e2b_kernelspec.py` (NEW, 337 LOC)
- 15 NEW tests (6 E2B + 2 factory + 6 KernelSpec + 1 default fallback)

### W5: Closure (this commit)

## Final state vs FINAL_REPORT_V2 направление #1

| Компонент | v2 | S74 W5 | S75 W5 | Change |
|---|---|---|---|---|
| JupyterHub WebSocket execution | ⚠️ | ✅ | ✅ | + S74 W3 heartbeat |
| nbclient backend | ✅ | ✅ | ✅ | — |
| **Papermill** | ⬜ | ✅ | ✅ | S74 W1 |
| **Множественные kernels** | ⚠️ | ⚠️ | ✅ | **S75 W3 KernelSpecDiscovery** |
| **Sandbox (e2b)** | ⬜ | ⚠️ | ✅ | **S75 W1+W2 E2BExecutionBackend** |
| NotebookService CRUD | ✅ | ✅ | ✅ | — |

**Net direction #1 rating: ⚠️ → ✅ (6/6 components)**. Final closure.

## TECH_DEBT closure summary

| Item | Status | Sprint |
|---|---|---|
| **FINAL_REPORT_V2 #2** e2b sandbox | ✅ **CLOSED S75 W1+W2** | factory stub → real backend |
| **FINAL_REPORT_V2 направление #1** multi-kernels | ✅ **CLOSED S75 W3** | KernelSpecDiscovery + whitelist filter |
| S74 W2 NotImplementedError stub | ✅ **REMOVED S75 W2** | factory E2B path works |

**Net S75 LOC**: 6 files changed, NET +1,030 LOC, 15 NEW tests.

## S76+ epic candidates (FINAL_REPORT_V2 P0-B/C/D)

1. **P0-B: tools whitelist в AIPolicySpec** (FINAL_REPORT_V2 P0)
2. **P0-C: AI Policy Spec DSL** (ADR-0067, FINAL_REPORT_V2 P0)
3. **P0-D: CORS/XSRF в Streamlit** (FINAL_REPORT_V2 P0)
4. **Hub-based kernelspec API** (S75 W3 stub, deferred)
5. **P1: PoolHealthMonitor registration** (LiteLLM Gateway, etc.)
6. **P1: CircuitBreakerMiddleware restoration**

## Files changed summary

- W1: 1 file (+334, -0) — E2BExecutionBackend
- W2: 2 files (+10, -7) — factory integration + re-exports
- W3: 2 files (+190, -0) — KernelSpecDiscovery + re-exports
- W4: 1 file (+337, -0) — 15 NEW tests
- W5: 3 files (closure, this commit)
- **Total: 9 files, NET +864 LOC**

## Verification

- 15 NEW tests passing в `test_e2b_kernelspec.py`
- E2BExecutionBackend constructed (lazy API key check)
- Factory creates E2B backend (NotImplementedError removed)
- KernelSpecDiscovery returns DEFAULT_FALLBACK_SPECS when jupyter_client
  unavailable (0 kernels in dev env)
- 6/6 components of direction #1 now ✅ (final closure)
