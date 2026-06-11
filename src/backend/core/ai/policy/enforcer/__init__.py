from __future__ import annotations
"""AIPolicyEnforcer package (S67 W2 decomp from enforcer.py 462 LOC).

1 god-class (12 methods) -> 4 mixins + 1 core:
- ``input_guard_mixin.py`` (5): guard_input, _guard_input_one, _guard_input_rebuff, _guard_input_lakera, _guard_input_llm_guard
- ``output_guard_mixin.py`` (2): guard_output, _guard_output_one
- ``handle_mixin.py`` (2): _handle_guard_block, _publish_dlq
- ``sanitize_mixin.py`` (2): sanitize_input, sanitize_output

Core (1) remains in __init__.py: __init__.

Backward-compat: ``from src.backend.core.ai.policy.enforcer import AIPolicyEnforcer`` works.
"""


from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from typing import TYPE_CHECKING, Any

from src.backend.core.logging import get_logger

if TYPE_CHECKING:
    from src.backend.core.ai.gateway import AIRequest, AIResponse
    from src.backend.core.ai.policy.spec import AIPolicySpec, GuardRef
    from src.backend.core.messaging.dlq import DLQWriter

from src.backend.core.ai.errors import GuardrailViolationError, GuardResult

from src.backend.core.ai.policy.enforcer.input_guard_mixin import InputGuardMixin  # S67 W2: MRO
from src.backend.core.ai.policy.enforcer.output_guard_mixin import OutputGuardMixin  # S67 W2: MRO
from src.backend.core.ai.policy.enforcer.handle_mixin import HandleMixin  # S67 W2: MRO
from src.backend.core.ai.policy.enforcer.sanitize_mixin import SanitizeMixin  # S67 W2: MRO

__all__ = (
    "AIPolicyEnforcer",
)

class AIPolicyEnforcer(
    InputGuardMixin,
    OutputGuardMixin,
    HandleMixin,
    SanitizeMixin,
):
    """AI policy enforcer (4 mixins = 11 methods + 1 core)."""

    __slots__ = ()
    def __init__(
        self,
        *,
        pii_tokenizer: object | None = None,
        nemo_runtime: object | None = None,
        llama_guard_runtime: object | None = None,
        llm_guard_client: Any | None = None,
        dlq_writer: DLQWriter | None = None,
    ) -> None:
        self._pii_tokenizer = pii_tokenizer
        self._nemo_runtime = nemo_runtime
        self._llama_guard_runtime = llama_guard_runtime
        self._llm_guard_client = llm_guard_client
        self._dlq_writer = dlq_writer

