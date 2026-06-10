"""admin_workflows endpoint package (S56 W4 decomp from admin_workflows.py 639 LOC).

5 schemas + 1 facade + 9 helpers decomposed в 4 files:
- ``schemas.py``: 6 Pydantic schemas (path/query/body)
- ``facade.py``: _AdminWorkflowsFacade (7 methods)
- ``helpers.py``: 8 top-level helpers (lazy imports + DI + filter)
- ``input_schema.py``: input_schema_json() function

Backward-compat: ``from src.backend.entrypoints.api.v1.endpoints.admin_workflows import _AdminWorkflowsFacade`` works.
"""

from __future__ import annotations

from src.backend.entrypoints.api.v1.endpoints.admin_workflows.schemas import WorkflowInstanceIdPath  # S56 W4: re-export
from src.backend.entrypoints.api.v1.endpoints.admin_workflows.schemas import WorkflowNamePath  # S56 W4: re-export
from src.backend.entrypoints.api.v1.endpoints.admin_workflows.schemas import ListWorkflowsQuery  # S56 W4: re-export
from src.backend.entrypoints.api.v1.endpoints.admin_workflows.schemas import EventsQuery  # S56 W4: re-export
from src.backend.entrypoints.api.v1.endpoints.admin_workflows.schemas import TriggerQuery  # S56 W4: re-export
from src.backend.entrypoints.api.v1.endpoints.admin_workflows.schemas import TriggerBody  # S56 W4: re-export
from src.backend.entrypoints.api.v1.endpoints.admin_workflows.facade import _AdminWorkflowsFacade  # S56 W4: re-export
from src.backend.entrypoints.api.v1.endpoints.admin_workflows.helpers import _bind_workflow_status  # S56 W4: re-export
from src.backend.entrypoints.api.v1.endpoints.admin_workflows.helpers import _instance_store  # S56 W4: re-export
from src.backend.entrypoints.api.v1.endpoints.admin_workflows.helpers import _event_store  # S56 W4: re-export
from src.backend.entrypoints.api.v1.endpoints.admin_workflows.helpers import _row_to_schema  # S56 W4: re-export
from src.backend.entrypoints.api.v1.endpoints.admin_workflows.helpers import _list_instances_filtered  # S56 W4: re-export
from src.backend.entrypoints.api.v1.endpoints.admin_workflows.helpers import _get_facade  # S56 W4: re-export
from src.backend.entrypoints.api.v1.endpoints.admin_workflows.helpers import _trigger_via_action_or_store  # S56 W4: re-export
from src.backend.entrypoints.api.v1.endpoints.admin_workflows.helpers import _wait_for_terminal  # S56 W4: re-export
from src.backend.entrypoints.api.v1.endpoints.admin_workflows.input_schema import input_schema_json  # S56 W4: re-export

__all__ = (
    "WorkflowInstanceIdPath",
    "WorkflowNamePath",
    "ListWorkflowsQuery",
    "EventsQuery",
    "TriggerQuery",
    "TriggerBody",
    "_AdminWorkflowsFacade",
    "_bind_workflow_status",
    "_instance_store",
    "_event_store",
    "_row_to_schema",
    "_list_instances_filtered",
    "_get_facade",
    "_trigger_via_action_or_store",
    "_wait_for_terminal",
    "input_schema_json",
)
