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

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable
    from src.backend.core.ai.policy.spec import (
        ToolsSpec,  # S76 W3
    )
    from src.backend.core.messaging.dlq import DLQWriter
from src.backend.core.ai.policy.enforcer.handle_mixin import HandleMixin  # S67 W2: MRO
from src.backend.core.ai.policy.enforcer.input_guard_mixin import (
    InputGuardMixin,  # S67 W2: MRO
)
from src.backend.core.ai.policy.enforcer.output_guard_mixin import (
    OutputGuardMixin,  # S67 W2: MRO
)
from src.backend.core.ai.policy.enforcer.sanitize_mixin import (
    SanitizeMixin,  # S67 W2: MRO
)
from src.backend.core.ai.policy.enforcer.tools_policy import (  # S76 W3
    ToolPolicyViolationError,  # S76 W3: re-export
    check_tool_allowed,  # S76 W3: re-export
    enforce_tool_policy,  # S76 W3: re-export
    filter_tools_by_policy,  # S76 W3: re-export
)

__all__ = (
    "AIPolicyEnforcer",
    "ToolPolicyViolationError",  # S76 W3
    "check_tool_allowed",  # S76 W3
    "enforce_tool_policy",  # S76 W3
    "filter_tools_by_policy",  # S76 W3
)


class AIPolicyEnforcer(InputGuardMixin, OutputGuardMixin, HandleMixin, SanitizeMixin):
    """AI policy enforcer (4 mixins = 11 methods + 1 core)."""

    # S76 W4 fix: removed `__slots__ = ()` (S67 W2 decomp forgot про
    # instance attrs `_pii_tokenizer` etc). Same pattern as S74 W4
    # NotebookExecutionService fix — decomp bug recurring.
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

    def filter_tools(
        self,
        tool_names: Iterable[str],
        spec: "ToolsSpec",
    ) -> list[str]:
        """S76 W3 — pre-init filter tool list per AIPolicySpec.tools.

        Convenience method wrapping
        :func:`filter_tools_by_policy` для caller ergonomics.

        Args:
            tool_names: all available tool names.
            spec: AIPolicySpec.tools section (whitelist/blacklist +
                on_violation).

        Returns:
            Filtered list (allowed tools only). Original order preserved.

        **Use case** (FINAL_REPORT_V2 P0-B): caller имеет
        ``agent = PydanticAI(tools=[...all_tools])`` initialization.
        Перед init: ``agent = PydanticAI(tools=enforcer.filter_tools(
        all_tools, current_policy.tools))``. Pre-init filter
        гарантирует agent НИКОГДА не имеет disallowed tools в своём
        toolset (fail-closed defense-in-depth).

        **Note**: per-invoke enforcement (W3 stub) ещё не integrated
        в PydanticAI tool dispatch — caller должен либо
        pre-init filter (W3 approach) либо per-invoke check (W3 stub
        → call ``enforce_tool_policy(tool_name, spec)`` перед dispatch).
        """
        return filter_tools_by_policy(tool_names, spec)
