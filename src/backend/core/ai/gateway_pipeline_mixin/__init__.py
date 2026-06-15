"""PipelineStepsMixin package (S56 W2 decomp from gateway_pipeline_mixin.py 620 LOC).

15 methods decomposed в 5 mixin files:
- ``policy_mixin.py`` (3): policy + capability checks
- ``input_mixin.py`` (3): input sanitization + guards
- ``llm_mixin.py`` (4): LLM invocation (render, invoke, extract, provider)
- ``output_mixin.py`` (3): output sanitization + guards + LLM gateway
- ``observability_mixin.py`` (2): audit + cost tracking

Backward-compat: ``from src.backend.core.ai.gateway_pipeline_mixin import PipelineStepsMixin`` works.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

"""PipelineStepsMixin для :class:`AIGateway` (S38 P1.1b, v9 P1 split).

Извлечено из ``core/ai/gateway.py`` в рамках T-P1.1b (v9 P1 God-объекты
split, Variant C mixin, maximal scope) для уменьшения god-файла
(939 → ~250 LOC facade + 600 LOC mixin).

Mixin содержит 9-step pipeline methods (policy resolve, capability check,
input/output sanitizers, input/output guards, render prompt, invoke LLM,
audit emit, cost track) + 5 helpers (resolvers + static utilities).

Composition::

    class AIGateway(PipelineStepsMixin, AuditContextMixin):
        def __init__(self, ...): ...   # facade owns init/state
        async def invoke(self, request): ...   # entry point
        async def _enforced_invoke(self, request): ...   # orchestrator

Mixin не имеет ``__init__`` — relies on facade's ``__init__`` для ``self._X`` attrs.

См. также:
* :class:`AIGateway` — :mod:`core.ai.gateway` (ADR-NEW-19);
* :class:`AuditContextMixin` — :mod:`core.ai.gateway_audit_mixin`.
"""

from typing import TYPE_CHECKING
from src.backend.core.logging import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)

from src.backend.core.ai.gateway_pipeline_mixin.input_mixin import (
    InputMixin,  # S56 W2: MRO
)
from src.backend.core.ai.gateway_pipeline_mixin.llm_mixin import (
    LlmInvocationMixin,  # S56 W2: MRO
)
from src.backend.core.ai.gateway_pipeline_mixin.observability_mixin import (
    ObservabilityMixin,  # S56 W2: MRO
)
from src.backend.core.ai.gateway_pipeline_mixin.output_mixin import (
    OutputMixin,  # S56 W2: MRO
)
from src.backend.core.ai.gateway_pipeline_mixin.policy_mixin import (
    PolicyMixin,  # S56 W2: MRO
)

__all__ = ("PipelineStepsMixin",)


class PipelineStepsMixin(
    PolicyMixin, InputMixin, LlmInvocationMixin, OutputMixin, ObservabilityMixin
):
    """AI Gateway Pipeline Steps (5 mixins = 15 methods)."""

    __slots__ = ()
