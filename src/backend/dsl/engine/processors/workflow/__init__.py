"""Workflow domain processors (Cycle 31 S2: directory split step 2).

Re-exports workflow processors from flat layout. New code should
import from this package; old code continues to work via the flat
module path.

Migration path:
- OLD: from src.backend.dsl.engine.processors.cancel_workflow import ...
- NEW: from src.backend.dsl.engine.processors.workflow import ...

Future cycles will physically move the files here.
"""

from src.backend.dsl.engine.processors.cancel_workflow import (  # noqa: F401
    CancelWorkflowProcessor,
)
from src.backend.dsl.engine.processors.invoke_workflow import (  # noqa: F401
    InvokeWorkflowProcessor,
)
from src.backend.dsl.engine.processors.sub_workflow import (  # noqa: F401
    SubWorkflowProcessor,
)

__all__ = (
    "CancelWorkflowProcessor",
    "InvokeWorkflowProcessor",
    "SubWorkflowProcessor",
)
