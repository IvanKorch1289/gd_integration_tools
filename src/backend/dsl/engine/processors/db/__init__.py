"""DB domain processors (Cycle 30 P4-#1: directory split step 1).

Re-exports DB processors from flat layout. New code should import from
this package; old code continues to work via the flat module path.

Migration path:
- OLD: from src.backend.dsl.engine.processors.db_call_procedure import ...
- NEW: from src.backend.dsl.engine.processors.db import ...

Future cycles will physically move the files here.
"""

from src.backend.dsl.engine.processors.db_call_procedure import DbCallProcedureProcessor as DbCallProcedureProcessor
from src.backend.dsl.engine.processors.db_crud import (
    DbCrudProcessor,  # noqa: F401 — re-export
)
from src.backend.dsl.engine.processors.db_query_external import (
    ExternalDbQueryProcessor as DbQueryExternalProcessor,
)

__all__ = (
    "DbCallProcedureProcessor",
    "DbCrudProcessor",
    "DbQueryExternalProcessor",
)
