# ADR-0330 — W9 P2-13 Phase 5: `services/ai/agent_sandbox.py` (601 LOC) → package split

* Статус: **Accepted** (cycle 153).
* Связано с: MINIMAX W9 (god-objects); V15 forbidden pattern «God-modules
  (>500 LOC)»; ADR-0328 (W9 P2-13 Phase 3 privacy split); ADR-0329
  (W9 P2-13 Phase 4 health split).

## Контекст

`src/backend/services/ai/agent_sandbox.py` (601 LOC, top-5 god-module) —
содержит 3 sandbox implementations для AI agent execution:

* 3 sandbox classes:
  * `InProcessAgentSandbox` (lines 65-171, ~107 LOC) — direct in-process execution.
  * `ProcessPoolAgentSandbox` (lines 200-287, ~88 LOC) — separate process pool.
  * `E2BAgentSandbox` (lines 288-486, ~199 LOC) — cloud sandbox (e2b.dev).
* 2 helper exceptions: `AgentSandboxConfigError`, `AgentSandboxTimeoutError`.
* 1 sync helper: `_sync_run_react`.
* 1 selector class: `AgentSandboxSelector`.
* 2 module-level helpers: `resolve_agent_sandbox`, `get_process_pool_agent_sandbox`.

**Проблема**:
- V15 forbidden pattern «God-modules (>500 LOC)».
- 3 sandbox implementations mixed — каждый имеет свой back-end integration
  (in-process / process-pool / cloud), свои deps (e2b, multiprocessing).
- Изменения в одной sandbox touch весь файл (merge conflicts).

**Consumer audit**:
- `from src.backend.services.ai.agent_sandbox import ...` — primary API.

External importers:
- `src/backend/services/ai/` — likely re-exports.
- AI agent dispatchers — use `resolve_agent_sandbox` selector.

## Решение

### Phase 5A: Split на 5 cohesion modules

| Module | LOC est. | Содержимое |
|---|---|---|
| `agent_sandbox.py` (shim) | ~30 | thin re-exports для back-compat |
| `_types.py` | ~25 | `AgentSandboxConfigError`, `AgentSandboxTimeoutError` exceptions |
| `_in_process.py` | ~115 | `InProcessAgentSandbox` + `_sync_run_react` helper |
| `_process_pool.py` | ~95 | `ProcessPoolAgentSandbox` |
| `_e2b.py` | ~210 | `E2BAgentSandbox` |
| `_selector.py` | ~100 | `AgentSandboxSelector` + `resolve_agent_sandbox` + `get_process_pool_agent_sandbox` |

**Total**: ~575 LOC distributed (с overhead), max per-module < 250 LOC.

### Back-compat strategy (W2 P0-3 SagaLRA Variant A pattern)

* `services/ai/agent_sandbox.py` → thin re-export shim.
* `services/ai/__init__.py` (public API) без изменений.
* Все 6 публичных имён доступны через обе entry points.

### Что НЕ делаем

* **Не** рефакторим sandbox implementations (изменения логики = breaking).
* **Не** мерджим sandbox patterns в общий base class (premature abstraction).
* **Не** удаляем `resolve_agent_sandbox` — primary dispatch entry point.

## Альтернативы (отклонённые)

1. **Keep as-is (601 LOC)**: нарушает V15.
2. **Split per-method**: не имеет смысла (функции внутри sandbox cohesive).
3. **Move to extensions/**: AI sandbox — universal AI infrastructure, не business-specific.

## Verification

```
compileall -q src/backend/services/ai/                            → exit 0
ruff check --select F401,F841,F811,E9 src/backend/services/ai/   → All checks passed
python -c "from src.backend.services.ai.agent_sandbox import (
    InProcessAgentSandbox, ProcessPoolAgentSandbox, E2BAgentSandbox,
    AgentSandboxSelector, resolve_agent_sandbox, get_process_pool_agent_sandbox,
    AgentSandboxConfigError, AgentSandboxTimeoutError,
)"
                                                                  → importable
pytest tests/unit/services/ai/                                      → passed
pytest tests/unit/dsl/processors/ (consumer tests)                  → passed
```

## Roadmap (после Phase 5)

Per ADR-0328/0329 roadmap:
* Phase 6: `core/ai/skill_registry.py` (614 LOC) — skill registry split.
* Phase 7: `core/di/providers/workflow.py` (602 LOC после Phase 2) — workflow split.
* Phase 8: `infrastructure/clients/storage/s3_pool/client.py` (625 LOC) — S3 pool split.

Refs: MINIMAX W9 P2-13 Phase 5, V15 forbidden pattern «god-modules»,
ADR-0316 (W2 P0-3 SagaLRA Variant A back-compat pattern), ADR-0328 (W9 P2-13
Phase 3 privacy split), ADR-0329 (W9 P2-13 Phase 4 health split).
