from __future__ import annotations

"""IntegrationCoreMixin package (S62 W3 decomp from integration_core.py 498 LOC).

15 methods decomposed в 4 mixin files:
- ``core_mixin.py`` (3): dispatch_action, invoke, to_route
- ``workflow_mixin.py`` (3): invoke_workflow, cancel_workflow, audit
- ``utils_mixin.py`` (7): scan_file, call_function, get_setting, validate_response, evaluate_rules, render_docx, render_xlsx
- ``ai_mixin.py`` (2): llm_structured, ml_predict

No core methods (all 15 are public).

Backward-compat: ``from src.backend.dsl.builders.integration_core import IntegrationCoreMixin`` works.
"""


from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder
from src.backend.dsl.builders.integration_core.ai_mixin import AiOpsMixin  # S62 W3: MRO
from src.backend.dsl.builders.integration_core.core_mixin import (
    CoreDispatchMixin,  # S62 W3: MRO
)
from src.backend.dsl.builders.integration_core.utils_mixin import (
    UtilsMixin,  # S62 W3: MRO
)
from src.backend.dsl.builders.integration_core.workflow_mixin import (
    WorkflowOpsMixin,  # S62 W3: MRO
)
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors import (
    DispatchActionProcessor,
    PipelineRefProcessor,
)
from src.backend.dsl.engine.processors.invoke import InvokeProcessor

__all__ = ("IntegrationCoreMixin",)


class IntegrationCoreMixin(CoreDispatchMixin, WorkflowOpsMixin, UtilsMixin, AiOpsMixin):
    """Integration core mixin (4 mixins = 15 methods)."""

    __slots__ = ()
