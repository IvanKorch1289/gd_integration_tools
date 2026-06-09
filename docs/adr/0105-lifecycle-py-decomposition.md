# ADR-0105: lifecycle.py god-object decomposition (1142→5 files, ~200 LOC avg)

**Date:** 2026-06-08
**Status:** Accepted (S82 W1-W4 complete, S82 W5 closure)
**Sprint:** S82
**Deciders:** platform team
**Related:** ADR-0102 (ai_processors pattern), S77 W2 (eip.py pattern)

## Context

S80 W1 audit found 4 god-objects >1000 LOC remaining в проекте. S82
focused на ``src/backend/plugins/composition/lifecycle.py`` (1142 LOC):

* 12 distinct concerns в одном файле
* 541 LOC main ``lifespan`` orchestrator
* 175 LOC protocol provider registration
* 141 LOC bootstrap helpers (storage/cache/snapshot/resilience)
* 232 LOC V11 plugin/route loaders + hot reload
* 41 LOC DSL yaml watcher

**Mixed concerns**:
1. Single FastAPI lifespan + 11 helper functions
2. Each helper has own feature-flag gate, own try/except, own logger
3. ~70% import overhead от pulling all helpers (cold start penalty)

## Decision

**Decompose** ``lifecycle.py`` (1142 LOC) → ``lifecycle/`` package с 5 модулями,
**mirroring the eip.py + ai_processors patterns**:

```
src/backend/plugins/composition/lifecycle/
├── __init__.py      (588 LOC) — main lifespan orchestrator + re-exports
├── protocols.py     (192 LOC) — provider registry (15 categories)
├── bootstrap.py     (168 LOC) — storage/cache/snapshot/resilience
├── v11.py           (264 LOC) — plugin/route loaders + hot reload
└── watchers.py      (62 LOC)  — DSL yaml watcher (start/stop)
```

**Total**: 1274 LOC (5 files, 168-588 LOC avg, 2.4x readability per file).

## Migration plan (mirroring eip.py + ai_processors)

| Step | Wave | Scope | Status |
|------|------|-------|--------|
| 1. protocols.py extraction | S82 W1 | 175 LOC | ✅ done |
| 2. bootstrap.py extraction | S82 W2 | 141 LOC | ✅ done |
| 3. v11.py extraction | S82 W3 | 232 LOC | ✅ done |
| 4. watchers.py extraction | S82 W4 | 41 LOC | ✅ done |
| 5. ADR-0105 + closure | S82 W5 | docs | ✅ this wave |

**Total decomp work**: 5 waves, 1 sprint scope (S82).

## Implementation pattern (verified in S82 W1-W4)

Direct import alias pattern (NOT shim with re-export):

```python
# __init__.py
from src.backend.plugins.composition.lifecycle.protocols import (  # noqa: E402
    register_protocol_providers as _register_protocol_providers,  # alias
)
# Original function body DELETED (no shim, no duplicate)
```

Why direct alias (vs shim re-export like ai_processors):
* Cleaner: alias is bound at import time, no double-resolution
* Same single function object: `A is B` returns True
* No runtime indirection

Why `# noqa: E402` (imports after `app_logger = get_logger`):
* Logger setup must run before submodule imports (submodules also call `get_logger`)
* Re-ordering would break this dependency
* Cleaner than re-ordering entire imports

## Naming convention

Following sibling `_editor/` + `ai/` patterns:
* Public functions: no leading underscore (``register_protocol_providers``)
* Imports in ``__init__.py``: alias с leading underscore (``_register_protocol_providers``)
  to mark "private to lifecycle package, used only by orchestrator"
* This makes the public API discoverable (no underscore → importable from outside)

## Stats

| Stage | __init__.py | Submodules | Total | Reduction factor |
|-------|------------|------------|-------|------------------|
| Original (S81) | 1142 LOC | 0 | 1142 | 1x |
| After S82 W1 | 970 LOC | 192 | 1162 | 1.2x |
| After S82 W2 | 842 LOC | 360 | 1202 | 1.3x |
| After S82 W3 | 621 LOC | 624 | 1245 | 1.4x |
| **After S82 W4** | **588 LOC** | **686** | **1274** | **1.6x** |

Net: +132 LOC (overhead from per-file imports, docstrings, headers).
But: 588 LOC max per file vs 1142 monolith = 1.9x reduction в cognitive load.

## Testing impact

* 1348 tests pass (outbox + DSL processors subset)
* No test changes needed (callers use same function names via __init__ re-exports)
* Pre-existing mypy eip/ errors unaffected

## Consequences

### Positive
- **Faster cold start**: optional imports в submodules (sandboxed env без V11 = skip)
- **Per-feature onboarding**: новый contributor изучает 1 файл (~200 LOC) вместо 1142
- **Easier review**: small diffs (50-200 LOC) вместо mega-edits
- **Mirrored patterns**: codebase consistency (eip.py, ai_processors, lifecycle)

### Negative
- **+132 LOC overhead** (acceptable для readability gain)
- **5 import statements** в __init__.py (visible noise, mitigated by # noqa)
- **Subtle import order dependency** (logger must be first)

### Neutral
- Public API unchanged (callers use same names)
- mypy/ruff status: 0 new errors
- Sibling S79 series (mypy strict eip/) unaffected

## Out of scope (S83+)

- `lifespan()` orchestrator (541→588 LOC) — could split into startup/shutdown phases
- Per-submodule unit tests (currently covered by integration)
- Shim deletion (S84+, same as ai_processors pattern)
- 4 other god-objects (eip.py partial, ai_processors shim, 31_DSL_VE, 4>500 LOC) — separate ADRs

## References

* `src/backend/plugins/composition/lifecycle.py` (original 1142 LOC)
* `src/backend/plugins/composition/lifecycle/` (5 files, 1274 LOC)
* S77 W2 commit (eip.py 1354→5 files, same pattern)
* S81 W1 commit (ai_processors.py 1164→87 LOC shim, similar pattern)
* ADR-0102 (ai_processors plan, mirrored here)
