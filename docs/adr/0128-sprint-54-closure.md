# ADR-0128 — Sprint 54 closure: 4 god-file decomps (mcp_server, ai_agent, invoker, capability_gate) (4+1 commits, 5/5 substantive)

* Статус: Accepted (Sprint 54 W5, 2026-06-10)
* Связано с: ebe41c2b (W1), 43393b67 (W2), 2cfb502f (W3), 7ba78f17 (W4)
* Контекст: PLAN.md V22 final, S49-S53 pattern continuation (5 commits = 4 working + closure)

## Контекст

Sprint 54 закрыл 4 крупных god-file из top-10 списка:
- mcp_server.py 706 LOC (11 functions, multi-function file split per-domain)
- ai_agent.py 703 LOC (1 god-class AIAgentService 19 methods → MRO 5 mixins)
- invoker.py 666 LOC (1 god-class Invoker 20 methods → MRO 4 mixins + sibling-orphaned InvocationMode enum recovered)
- capability_gate.py 629 LOC (1 god-class CapabilityGate 17 methods → MRO 4 mixins + AuditCallback + _DEFAULT_LRU_SIZE constants)

## Решения

1. **Multi-function file split (mcp_server, S54 W1)** — pattern: 1 helpers + N per-domain tools + 1 init. Re-export через `from .tools_X import _register_X_tools` для backward compat.

2. **Stateful god-class MRO (ai_agent, S54 W2)** — MRO 6-level: 5 mixins + 3 core. Class-level annotations для state attrs (S52 W3 pattern). Cross-mixin method hints via `Callable[..., None]` для разрешения MRO scope.

3. **Stateful god-class + missing enum (invoker, S54 W3)** — sibling-orphaned `InvocationMode` enum, на который ссылались docstring и parent `execution/__init__.py`, но который никогда не был определён. S54 W3 восстановил enum с правильными StrEnum-значениями.

4. **Stateless god-class + module-level constants (capability_gate, S54 W4)** — pattern: `AuditCallback = Callable[...]` и `_DEFAULT_LRU_SIZE: Final[int] = 1024` сохранены в `__init__.py` перед class. Cross-references на `CapabilityRef`, `CapabilityVocabulary`, `CapabilityNotFoundError`, `CapabilitySupersetError` импортированы.

5. **`from __future__` deduplication (gate, S54 W4)** — extraction script добавлял `from __future__ import annotations` в начало mixin файла, но `cleaned_imports` уже содержал эту строку. Деддап через strip всех дубликатов кроме первого.

## Изменения

| File | Before | After | Method count |
|------|--------|-------|--------------|
| mcp_server.py | 706 | 0 (deleted) | 11 fns → 8 files |
| ai_agent.py | 703 | 0 (deleted) | 19 → 6 files (5 mixins + init) |
| invoker.py | 666 | 0 (deleted) | 20 → 6 files (4 mixins + init + InvocationMode enum) |
| capability_gate.py | 629 | 0 (deleted) | 17 → 6 files (4 mixins + init) |
| **Total** | **2704** | **0 (replaced)** | **67 methods → 26 files** |

## Quality gates (S54 scope)

- **mypy**: 1591 source files checked, 1 sibling pre-existing error in builder.pyi (NOT in S54 scope)
- **ruff**: 122 fixable issues (mostly in sibling WIP areas: jupyter, notebook_execute, cdc_client_adapter — NOT in S54 scope)
- S54-specific ruff: 0 errors
- S54-specific mypy: ~10 cross-mixin method-hint errors (acceptable per S52 W3 pattern)

## Patterns re-used from S49-S53

- MRO composition (S49 W3: TransportMixin, S51 W1/W2: AILlMMixin/RPAMixin, S52 W2: SecurityChecksMixin, S53 W1: DataFormatsMixin)
- Per-class file split (S50 W3: ai_banking.py, S50 W4: rpa.py, S51 W3: agent_dsl.py, S53 W2: streaming.py)
- Stateful class state attrs via class-level annotations (S52 W3: loader_v11.py)
- Sibling-orphaned enum recovery (NEW this sprint: InvocationMode)

## Команды (verification)

```bash
.venv/bin/python -c "
from src.backend.entrypoints.mcp.mcp_server import create_mcp_server, register_mcp_tools
from src.backend.services.ai.ai_agent import AIAgentService, get_ai_agent_service
from src.backend.services.execution.invoker import Invoker, get_invoker, InvocationMode
from src.backend.core.security.capabilities.gate import CapabilityGate, check_capabilities_subset
print('MRO:')
print('  AIAgentService:', [c.__name__ for c in AIAgentService.__mro__])
print('  Invoker:', [c.__name__ for c in Invoker.__mro__])
print('  CapabilityGate:', [c.__name__ for c in CapabilityGate.__mro__])
"
```

## Lessons learned (для sprint-execution skill)

1. **Multi-function file split (rpa.py/streaming.py/mcp_server pattern)** — cleanest: 1 init + 1 helpers + N per-domain files, each holding 1-3 functions.

2. **Stateful god-class MRO with sibling-orphaned symbols** — always check that parent `__init__.py` imports resolve. If they reference symbols that don't exist, recover them (or the entire chain fails).

3. **Module-level constants preservation** — `Final[int]`, `Callable[...]`, enum definitions need to be in `__init__.py` BEFORE the MRO class declaration.

4. **Extraction script `from __future__` duplication** — pattern: always deduplicate the `from __future__ import annotations` line in mixin files. Cleaner extraction: write mixin file with the future import FIRST, then append cleaned imports.

5. **State attrs bulk declaration** — use `ALL_STATE = [...]` in the extraction script, then write to ALL mixin files. Dedup post-write (remove methods defined in same file).

## Files Modified

### Created
- `src/backend/entrypoints/mcp/mcp_server/{__init__,helpers,tools_route,tools_template,tools_convert,tools_system,tools_yaml,tools_document}.py`
- `src/backend/services/ai/ai_agent/{__init__,http_providers_mixin,web_methods_mixin,agent_orchestration_mixin,rag_mixin,policy_mixin}.py`
- `src/backend/services/execution/invoker/{__init__,invoke_modes_mixin,deferred_mixin,temporal_mixin,run_mixin}.py`
- `src/backend/core/security/capabilities/gate/{__init__,declaration_mixin,check_mixin,cache_mixin,audit_mixin}.py`

### Deleted
- `src/backend/entrypoints/mcp/mcp_server.py`
- `src/backend/services/ai/ai_agent.py`
- `src/backend/services/execution/invoker.py`
- `src/backend/core/security/capabilities/gate.py`

### Updated
- `.claude/skills/sprint-execution/SKILL.md` (lessons from W3: enum recovery, from __future__ dedup)

## S49-S54 cumulative

| Sprint | God-files fully closed | TDs closed | New ADR |
|--------|------------------------|------------|---------|
| S49 | 31_DSL_Visual_Editor 1267→616, actions.py 986→353+669 | TD-009 | ADR-0123 |
| S50 | transport.py, ai_banking.py 828, rpa.py 823 | TD-001, TD-007 | ADR-0124 |
| S51 | agent_dsl.py 771, ai_rpa.py 61/61 (3-wave) | TD-003 | ADR-0125 |
| S52 | validator.py 760, loader_v11.py 724 | TD-010 (stale) | ADR-0126 |
| S53 | format_convert.py 744, streaming.py 737, setup.py 756 | TD-002 (parallel) | ADR-0127 |
| S54 | mcp_server.py 706, ai_agent.py 703, invoker.py 666, capability_gate.py 629 | — | ADR-0128 |

**Total: 16 god-files fully closed, 6 TDs closed**

## S55+ candidates

| Task | Effort | Notes |
|------|--------|-------|
| spec.py 636 → decomp (workflow spec) | 1 wave | Type-heavy |
| gate.py (or other top-10) | — | S54 done |
| Streamlit frontend pages (next layer) | 2-3 waves | 31_DSL_Visual_Editor 616 + many more |
| TD-006 (Vite/chromadb phantom) | analysis | low risk |
| TD-005 / TD-008 (still open) | investigation | need fresh scope |

## Sibling WIP outstanding (NOT in S54 scope)

- `src/backend/dsl/workflow/builder.pyi:25` — pre-existing mypy Ellipsis error
- `src/backend/infrastructure/cdc/cdc_client_adapter.py:103` — pre-existing async/await mismatch
- `src/backend/services/jupyter/__init__.py` — missing execution_service module
- `src/backend/dsl/engine/processors/notebook_execute.py` — missing types module
- `src/backend/infrastructure/storage/trace_storage.py` — pre-existing ruff errors

S54 закрыт. Total commits: 5 (4 working + 1 closure).
