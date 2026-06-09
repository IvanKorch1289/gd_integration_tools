# ADR-0102: ai_processors.py god-object decomposition (1164 LOC → 6 modules)

**Date:** 2026-06-08
**Status:** Accepted (S80 W4 — design + minimal POC, S77+ scope for full split)
**Sprint:** S80
**Deciders:** core/DSL team
**Related:** ADR-0087 (ClaimCheck dedup), S77 W2 (eip.py decomp pattern)

## Context

S80 W1 audit (TECH_DEBT.md update) found remaining god-objects:
- `src/backend/dsl/engine/processors/ai_processors.py` — **1164 LOC, 16 classes** (largest remaining)
- Sibling sprints S77 W2 (eip.py 1354→5 files) + S77 W3 (31_DSL_Visual_Editor 1269→1082)
  established the decomp pattern.

`ai_processors.py` mixes 6 distinct concerns в один файл:

| Group | Classes | Domain |
|-------|---------|--------|
| LLM | PromptComposerProcessor, LLMCallProcessor, LLMParserProcessor, LLMFallbackProcessor (4) | LLM integration |
| RAG | VectorSearchProcessor, RagQueryProcessor, RagPIIRedactionProcessor, RagIngestProcessor, GetFeedbackExamplesProcessor (5) | Retrieval-Augmented Generation |
| PII | SanitizePIIProcessor, RestorePIIProcessor (2) | PII masking (DSL side) |
| Cache | CacheProcessor, CacheWriteProcessor (2) | AI-specific cache (vs general `CacheDecorator`) |
| Guardrails | GuardrailsProcessor, SemanticRouterProcessor (2) | Safety + routing |
| Token | TokenBudgetProcessor (1) | Token counting/budget |

**Current impact**:
- `wc -l` = 1164 (4th largest file в проекте, после eip.py decomposed, manage.py, test_converters_mixin.py)
- High import time (all 16 classes load на startup)
- Hard to navigate (developer must scroll через unrelated classes)
- 16 classes in one file = "find the class" requires grep, not file-tree

## Decision

**Decompose** `ai_processors.py` (1164 LOC) → 6 domain-specific files, **mirroring the S77 W2 eip.py pattern**:

```
src/backend/dsl/engine/processors/ai/
├── __init__.py                 # re-exports для backwards compat
├── ai_llm.py                  # PromptComposer, LLMCall, LLMParser, LLMFallback (4 classes)
├── ai_rag.py                  # VectorSearch, RagQuery, RagPIIRedaction, RagIngest, GetFeedbackExamples (5 classes)
├── ai_pii.py                  # SanitizePII, RestorePII (2 classes)
├── ai_cache.py                # CacheProcessor, CacheWriteProcessor (2 classes)
├── ai_guardrails.py           # Guardrails, SemanticRouter (2 classes)
└── ai_token.py                # TokenBudget (1 class)
```

**Total**: 6 new files, ~150-200 LOC each (vs 1164 in one file). Average per file = ~190 LOC.

**Migration plan** (mirroring S77 W2 eip.py split):

| Step | Wave | Scope | Status |
|------|------|-------|--------|
| 1. ADR + analysis | S80 W4 | Design + proof of concept | ✅ THIS WAVE |
| 2. Move TokenBudgetProcessor (smallest, 1 class) | S81 W1 | 1 file, ~50 LOC extracted | TODO |
| 3. Move PII processors (Sanitize, Restore) | S81 W2 | 1 file, ~100 LOC | TODO |
| 4. Move Cache processors | S81 W3 | 1 file, ~150 LOC | TODO |
| 5. Move Guardrails + SemanticRouter | S82 W1 | 1 file, ~150 LOC | TODO |
| 6. Move RAG processors (largest group) | S82 W2-W3 | 1 file, ~400 LOC (split если >500) | TODO |
| 7. Move LLM processors | S82 W4 | 1 file, ~300 LOC | TODO |
| 8. Delete ai_processors.py (old monolith) | S83 W1 | Replaced by `ai/__init__.py` re-exports | TODO |
| 9. Update `__init__.py` to use new paths | S83 W1 | Backwards-compat shim | TODO |

**Total decomp work**: ~9 waves, 1 sprint scope (S81-S83).

## Why not 1 wave (full split)

Sprint 36 rule "honest scope reduction" + previous experience:
- eip.py split (S60 W4) была **1-2 waves** для 1354→5 files
- 16 classes в одном файле — **bigger scope** than eip.py
- Each move требует:
  1. Update imports в ALL call sites
  2. Update `__init__.py` re-exports
  3. Test pass
  4. mypy pass
  5. ruff pass
- Risk: breaking backward compat (callers do `from ...ai_processors import Foo`)

1 wave = max 1 logical change = max 2-3 classes moved. 16 classes = 5+ waves.

## Minimal POC (this wave)

**Proof of concept** that pattern works:
- Extract `TokenBudgetProcessor` (1 class, ~50 LOC, smallest group) в
  отдельный файл `src/backend/dsl/engine/processors/ai/ai_token.py`
- Old `ai_processors.py` keeps `TokenBudgetProcessor` import как
  re-export shim (backwards compat)
- Verify: tests + mypy + ruff

**Status**: design + plan, NOT impl (deferred to S81 W1).

## Naming convention

Following S77 W2 eip.py pattern:
- New dir: `src/backend/dsl/engine/processors/ai/`
- File names: `ai_<domain>.py` (snake_case prefix `ai_` для namespace clarity)
- Classes: keep `Processor` suffix (e.g., `TokenBudgetProcessor`)

## Import path strategy (backwards compat)

Three options:

**Option A: Direct new paths** (breaking, requires all callers update)
```python
from src.backend.dsl.engine.processors.ai.ai_token import TokenBudgetProcessor
```

**Option B: Package __init__ re-exports** (recommended, no breaking)
```python
# src/backend/dsl/engine/processors/ai/__init__.py
from .ai_token import TokenBudgetProcessor
from .ai_pii import SanitizePIIProcessor, RestorePIIProcessor
# ... etc

# Old call site still works:
from src.backend.dsl.engine.processors.ai import TokenBudgetProcessor
# BUT requires deleting ai_processors.py + updating all paths → still breaking
```

**Option C: Hybrid** (best — no break, clean new paths)
- New package: `src/backend/dsl/engine/processors/ai/`
- Old monolith: `src/backend/dsl/engine/processors/ai_processors.py`
  becomes 1-line shim:
  ```python
  """Backwards-compat shim → src.backend.dsl.engine.processors.ai."""
  from src.backend.dsl.engine.processors.ai import (
      TokenBudgetProcessor, SanitizePIIProcessor, ... # all 16
  )
  __all__ = ("TokenBudgetProcessor", "SanitizePIIProcessor", ..., )
  ```
- Both paths work:
  ```python
  # Old (still works, shim):
  from src.backend.dsl.engine.processors.ai_processors import TokenBudgetProcessor
  # New (preferred):
  from src.backend.dsl.engine.processors.ai.ai_token import TokenBudgetProcessor
  ```

**Decision**: Option C (hybrid shim). Sibling eip.py used this exact pattern (see S77 W2 commit `92159d53`).

## Consequences

### Positive
- **Modular imports**: каждая domain group = separate file = clearer mental model
- **Faster test collection**: pytest discovers test_ai_token.py vs test_ai_llm.py separately
- **Cleaner dependency graph**: ai_pii.py doesn't import ai_llm.py (vs current monolith)
- **Easier AI/ML team navigation**: domain experts can find their processors
- **Reduces monolith risk**: 1164 LOC → 6 files of ~190 LOC avg (4x improvement)

### Negative
- **Migration overhead**: 9 waves, 1 sprint scope (S81-S83)
- **Dual imports during transition**: both `ai_processors.py` and `ai/ai_token.py` exist
- **Possible import cycles** if new layout creates cross-dependencies
  (mitigated by alphabetical domain separation)

### Neutral
- Public API unchanged (shim обеспечивает backwards compat)
- Tests don't need rewrite (already in `tests/unit/dsl/engine/processors/`)
- mypy strict будет требовать explicit `from .ai_token import ...`

## Alternatives considered

### Alt 1: Single split (1 wave, 16 classes)
**Rejected** — too big for 1 wave, risk of broken imports, no incremental validation.

### Alt 2: Keep as-is, no split
**Rejected** — 1164 LOC is real god-object (4x avg), continues to grow as more AI processors added.

### Alt 3: Refactor to inheritance hierarchy
**Rejected** — current flat structure works, AI semantics not naturally hierarchical.

## Implementation Status

| Component | Status | Sprint |
|-----------|--------|--------|
| ADR-0102 (this document) | ✅ Written | S80 W4 |
| ai/ dir structure | TODO | S81 W1 |
| ai_token.py extraction | TODO | S81 W1 (POC) |
| ai_pii.py extraction | TODO | S81 W2 |
| ai_cache.py extraction | TODO | S81 W3 |
| ai_guardrails.py extraction | TODO | S82 W1 |
| ai_rag.py extraction | TODO | S82 W2-W3 |
| ai_llm.py extraction | TODO | S82 W4 |
| ai_processors.py shim | TODO | S83 W1 |
| Final cleanup (delete shim) | TODO | S84+ |

## References

* `src/backend/dsl/engine/processors/ai_processors.py` (1164 LOC, 16 classes)
* S77 W2 commit `92159d53` (eip.py 1354→5 files pattern)
* S77 W3 commit `c1461298` (31_DSL_Visual_Editor 1269→1082 pattern)
* ADR-0087 (ClaimCheck dedup, similar refactor scope)
* `.shared/context/TECH_DEBT.md` S80 W1 closure (4 god-objects >1000 LOC remaining)
