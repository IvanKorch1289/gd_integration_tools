# P1 split plan: core/ai/gateway.py (Q1=C mixin, Q2=C maximal)

**Plan date:** 2026-06-03 | **v9 P1:** God-объекты | **Status:** plan (no execution yet)

## Audit recap (T-P1.0)

- File: `src/backend/core/ai/gateway.py` — **1091 LOC**
- 4 classes: AIRequest (32), AIResponse (27), AIGateway (~860), _AuditContext (125)
- 24 methods (3 public + 21 private)
- 18+ external usages (services/ai, dsl/engine/processors, dsl/builders, dsl/workflow, core/ai/*, core/security/pii_tokenizer)

## Variant: C (mixin) + maximal scope

### Целевая структура (3 файла + facade)

```
core/ai/gateway.py                       # AIGateway facade (thin, ~250 LOC)
                                        # Содержит: __init__, get_policy, invoke,
                                        # _enforced_invoke (orchestrator), _legacy_invoke,
                                        # _AuditContext-light emit calls

core/ai/gateway_pipeline_mixin.py       # class PipelineStepsMixin (~600 LOC)
                                        # 9 step methods: _resolve_policy, _check_capability,
                                        # _apply_input_sanitizers, _apply_input_guards,
                                        # _render_prompt, _invoke_llm, _apply_output_guards,
                                        # _apply_output_sanitizers, _audit_emit, _cost_track
                                        # + resolvers: _resolve_sanitizer, _resolve_llm_gateway
                                        # + helpers: _language_from_policy, _extract_completion, _provider_from_model

core/ai/gateway_audit_mixin.py          # class AuditContextMixin + _AuditContext dataclass (~200 LOC)
                                        # _AuditContext + _emit, _emit_guard, _emit_final,
                                        # _emit_wrapper
```

### Mixin pattern

```python
# core/ai/gateway.py
from src.backend.core.ai.gateway_pipeline_mixin import PipelineStepsMixin
from src.backend.core.ai.gateway_audit_mixin import AuditContextMixin

class AIGateway(PipelineStepsMixin, AuditContextMixin):
    """Тонкий фасад — оркестратор 9-step pipeline."""
    def __init__(self, *, ...): ...
    async def get_policy(...): ...
    async def invoke(self, request): ...
    async def _enforced_invoke(self, request):
        # Orchestrator only — 9 method calls
        policy = await self._resolve_policy(request)
        await self._check_capability(request)
        # ... 9 lines
    async def _legacy_invoke(self, request): ...
```

### LOC reduction

| Файл | Сейчас | После | Δ |
|------|------:|------:|---:|
| core/ai/gateway.py | 1091 | ~250 | -841 (-77%) |
| core/ai/gateway_pipeline_mixin.py | — | ~600 | new |
| core/ai/gateway_audit_mixin.py | — | ~200 | new |

**Result**: top god-файл core/ai/gateway.py 1091→250, всё ещё >300 (P1 DoD).
Нужно ещё дробление (T-P1.2: pipeline_mixin → 3 step-group mixins).

## Risk assessment

### R1: Backward compatibility (HIGH risk)

18+ файлов импортируют `from src.backend.core.ai.gateway import AIGateway`.

**Mitigation:**
- Все public API (`AIGateway`, `AIRequest`, `AIResponse`) остаются в `gateway.py` без изменений
- Mixins — private (`_PipelineStepsMixin`, `_AuditContextMixin`)
- External imports не меняются

### R2: dataclass coupling (MEDIUM risk)

`_AuditContext` (dataclass) ссылается на `request: AIRequest`, `policy: AIPolicySpec`, `GuardResult`, etc. При extract в отдельный модуль — cross-module imports.

**Mitigation:**
- Type-only imports (`from typing import TYPE_CHECKING`) где возможно
- Dataclass с `from __future__ import annotations` (уже есть)
- `Any` type для cross-module refs (production code already does this)

### R3: Mixin MRO (LOW risk)

Python MRO для `class AIGateway(PipelineStepsMixin, AuditContextMixin)` — линеен (нет diamond). Безопасно.

### R4: Testing infrastructure (MEDIUM risk)

`tests/unit/core/ai/test_sandbox.py` (subagent 1) НЕ тестирует gateway. Нужно:
- Audit existing tests for `core/ai/gateway`
- Plan tests для каждого mixin отдельно (T-P1.3, после split)

## Execution plan (multi-step)

### T-P1.1a: extract AuditContextMixin (low risk, ~30 мин)
1. Create `core/ai/gateway_audit_mixin.py`
2. Move `_AuditContext` dataclass + 3 methods + `_emit_wrapper` function
3. Update `gateway.py` import (delete extracted code, add `from .gateway_audit_mixin import _AuditContext, _emit_wrapper`)
4. Verify: `pytest tests/unit/core/ai/ --cov=src.backend.core.ai.gateway` — coverage НЕ упал
5. `make lint` exit 0
6. Commit `[verified] refactor(P1.1a): gateway → extract AuditContextMixin (-125 LOC)`
7. Review: git diff, AIGateway API unchanged

### T-P1.1b: extract PipelineStepsMixin (medium risk, ~1-2 часа)
1. Create `core/ai/gateway_pipeline_mixin.py`
2. Move 9 step methods + 5 helper methods
3. Update `gateway.py` — class AIGateway(PipelineStepsMixin, AuditContextMixin)
4. Update `_enforced_invoke` — calls к `self._X` methods (no changes, уже через self)
5. Verify: pytest all 18+ usages still import OK
6. Verify: no behavior change (smoke test on `invoke`)
7. `make lint` exit 0
8. Commit `[verified] refactor(P1.1b): gateway → extract PipelineStepsMixin (-700 LOC)`
9. Review: pytest + smoke test + diff check

### T-P1.1c: final smoke test + documentation
1. Update `.shared/context/P1_1_gateway_split_summary.md` с результатами
2. Update `S38_W1_P1_split.md` plan: gateway.py done
3. Commit `[verified] docs(P1.1c): gateway split summary`

## Estimated timeline

| Step | Effort | Risk | Cumulative LOC reduction |
|------|-------:|:----:|:------------------------:|
| T-P1.1a | 30 мин | LOW | -125 |
| T-P1.1b | 1-2 часа | MEDIUM | -825 (total 77%) |
| T-P1.1c | 15 мин | NONE | — |
| **Total** | **2-3 часа** | — | **1091→266** ✅ P1 DoD |

## Open questions

- Q1: Confirm step order (T-P1.1a first → easier, then T-P1.1b)
- Q2: After gateway.py done — immediately continue с `core/di/providers.py` (Q4=D) или стоп для review?
- Q3: Mixin names: `_PipelineStepsMixin` (private) vs `PipelineStepsMixin` (public, импортируемый)? Рекомендую private — internal implementation detail.
