"""LLMStructuredProcessor package (S65 W2 decomp from llm_structured.py 485 LOC).

10 methods decomposed в 4 mixin files:
- ``resolve_mixin.py`` (3): _resolve_schema (72 LOC BIG), _resolve_prompt, _provider_name
- ``process_mixin.py`` (2): process (91 LOC BIG), _call_with_completion
- ``metrics_mixin.py`` (2): _estimate_cost, _extract_tokens
- ``serialization_mixin.py`` (2): _write_result, to_spec

Core (1) остается в __init__.py: __init__.

Backward-compat: ``from src.backend.dsl.engine.processors.llm_structured import LLMStructuredProcessor`` works.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import processor as _processor_reg

if TYPE_CHECKING:
    from pydantic import BaseModel

_logger = get_logger(__name__)

# Дефолтный ``temperature`` для structured-output: детерминизм важнее
# креативности при заполнении схемы.
_DEFAULT_TEMPERATURE: float = 0.0
# Максимальное число instructor-retries (внутренний цикл валидации Pydantic).
_DEFAULT_RETRY: int = 3


from src.backend.dsl.engine.processors.llm_structured.metrics_mixin import (
    MetricsMixin,  # S65 W2: MRO
)
from src.backend.dsl.engine.processors.llm_structured.process_mixin import (
    ProcessMixin,  # S65 W2: MRO
)
from src.backend.dsl.engine.processors.llm_structured.resolve_mixin import (
    ResolveMixin,  # S65 W2: MRO
)
from src.backend.dsl.engine.processors.llm_structured.serialization_mixin import (
    SerializationMixin,  # S65 W2: MRO
)

__all__ = ("LLMStructuredProcessor",)


@_processor_reg(
    "llm_structured",
    namespace="core",
    spec_schema={
        "type": "object",
        "required": ["model", "output_schema", "prompt"],
        "properties": {
            "model": {"type": "string"},
            "output_schema": {"type": ["string", "object", "null"]},
            "prompt": {"type": "string"},
            "retry": {"type": "integer", "minimum": 0, "default": _DEFAULT_RETRY},
            "temperature": {
                "type": "number",
                "minimum": 0.0,
                "default": _DEFAULT_TEMPERATURE,
            },
            "cost_budget_usd": {"type": ["number", "null"]},
            "to": {"type": "string"},
        },
    },
    capabilities=("ai.llm.litellm", "net.outbound.litellm:external"),
    meta={"tier": 2, "category": "ai", "version": "v17"},
    tags=("ai", "llm", "structured-output"),
)
class LLMStructuredProcessor(
    ResolveMixin, ProcessMixin, MetricsMixin, SerializationMixin, BaseProcessor
):
    """LLM structured output processor (4 mixins + BaseProcessor = 9 methods + 1 core).

    .. note::
        S132 W2 fix: ``BaseProcessor`` added to MRO at the END (after all
        mixins). Originally the class inherited only from 4 mixins, so
        ``super().__init__(name=...)`` walked through mixins →
        ``object.__init__()`` and raised
        ``TypeError: object.__init__() takes exactly one argument``
        (10 tests failed in ``test_llm_structured.py``).

        Why LAST and not FIRST: Python MRO resolves the first base that
        defines a method. With ``BaseProcessor`` first, ``process`` is
        found as the abstract version (``@abstractmethod async def
        process(...): ...``) and overrides the concrete implementation
        in ``ProcessMixin``. By putting ``BaseProcessor`` LAST, MRO
        walks ``ProcessMixin`` first, finds the concrete ``process``,
        and the abstract check passes — while ``__init__`` still
        resolves to ``BaseProcessor.__init__`` (no mixin defines one).
        Affected 10 tests in ``test_llm_structured.py`` (TD-006 fix #1).
    """

    __slots__ = ()

    def __init__(
        self,
        *,
        model: str,
        output_schema: type[BaseModel] | str | None,
        prompt: str,
        retry: int = _DEFAULT_RETRY,
        temperature: float = _DEFAULT_TEMPERATURE,
        cost_budget_usd: float | None = None,
        to: str = "body.llm_result",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "llm_structured")
        if not model or "/" not in model:
            raise ValueError(
                f"llm_structured: model должен быть в формате "
                f"'<provider>/<name>', получено {model!r}"
            )
        if retry < 0:
            raise ValueError(
                f"llm_structured: retry должен быть >= 0, получено {retry!r}"
            )
        if cost_budget_usd is not None and cost_budget_usd < 0:
            raise ValueError(
                "llm_structured: cost_budget_usd должен быть >= 0, "
                f"получено {cost_budget_usd!r}"
            )
        self._model = model
        self._output_schema_ref = output_schema
        self._prompt_template = prompt
        self._retry = retry
        self._temperature = temperature
        self._cost_budget_usd = cost_budget_usd
        self._to = to
