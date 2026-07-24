"""DB domain processors (Cycle 30 P4-#1: directory split step 1).

Re-exports DB processors from flat layout. New code should import from
this package; old code continues to work via the flat module path.

Migration path:
- OLD: from src.backend.dsl.engine.processors.db_call_procedure import ...
- NEW: from src.backend.dsl.engine.processors.db import ...

Future cycles will physically move the files here.
"""

from src.backend.dsl.engine.processors.db_call_procedure import (  # noqa: F401
    DbCallProcedureProcessor,
)
from src.backend.dsl.engine.processors.db_crud import (  # noqa: F401
    DbCrudProcessor,
)
from src.backend.dsl.engine.processors.db_query_external import (  # noqa: F401
    DbQueryExternalProcessor,
)

__all__ = (
    "DbCallProcedureProcessor",
    "DbCrudProcessor",
    "DbQueryExternalProcessor",
)
