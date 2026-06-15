"""admin_workflows endpoint package (S56 W4 decomp from admin_workflows.py 639 LOC).

5 schemas + 1 facade + 9 helpers decomposed в 4 files:
- ``schemas.py``: 6 Pydantic schemas (path/query/body)
- ``facade.py``: _AdminWorkflowsFacade (7 methods)
- ``helpers.py``: 8 top-level helpers (lazy imports + DI + filter)
- ``input_schema.py``: input_schema_json() function

Backward-compat: ``from src.backend.entrypoints.api.v1.endpoints.admin_workflows import _AdminWorkflowsFacade`` works.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from src.backend.entrypoints.api.generator.actions import (
    ActionRouterBuilder,
    ActionSpec,
)
from src.backend.entrypoints.api.v1.endpoints.admin_workflows.facade import (
    _AdminWorkflowsFacade,  # S56 W4: re-export
    _get_facade,  # S56 W4: re-export
)
from src.backend.entrypoints.api.v1.endpoints.admin_workflows.helpers import (
    _bind_workflow_status,  # S56 W4: re-export
    _event_store,  # S56 W4: re-export
    _instance_store,  # S56 W4: re-export
    _list_instances_filtered,  # S56 W4: re-export
    _row_to_schema,  # S56 W4: re-export
    _trigger_via_action_or_store,  # S56 W4: re-export
    _wait_for_terminal,  # S56 W4: re-export
)
from src.backend.entrypoints.api.v1.endpoints.admin_workflows.input_schema import (
    input_schema_json,  # S56 W4: re-export
)
from src.backend.entrypoints.api.v1.endpoints.admin_workflows.schemas import (
    EventsQuery,  # S56 W4: re-export
    ListWorkflowsQuery,  # S56 W4: re-export
    TriggerBody,  # S56 W4: re-export
    TriggerQuery,  # S56 W4: re-export
    WorkflowInstanceIdPath,  # S56 W4: re-export
    WorkflowNamePath,  # S56 W4: re-export
)
from src.backend.schemas.workflow import (
    WorkflowCancelRequest,
    WorkflowEventSchemaOut,
    WorkflowInstanceDetailSchemaOut,
    WorkflowInstanceRef,
    WorkflowInstanceSchemaOut,
)

__all__ = (
    "router",
    "builder",
    "ActionSpec",
    "ActionRouterBuilder",
    "APIRouter",
    "status",
    "WorkflowCancelRequest",
    "WorkflowEventSchemaOut",
    "WorkflowInstanceDetailSchemaOut",
    "WorkflowInstanceRef",
    "WorkflowInstanceSchemaOut",
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

# --- Router ----------------------------------------------------------------


router = APIRouter(tags=["Admin · Workflows"])
builder = ActionRouterBuilder(router)

common_tags = ("Admin · Workflows",)


builder.add_actions(
    [
        ActionSpec(
            name="admin_list_workflows",
            method="GET",
            path="/workflows",
            summary="Список durable workflows с фильтрацией",
            service_getter=_get_facade,
            service_method="list_workflows",
            query_model=ListWorkflowsQuery,
            argument_aliases={"status": "status_filter"},
            response_model=list[WorkflowInstanceSchemaOut],
            tags=common_tags,
        ),
        ActionSpec(
            name="admin_get_workflow",
            method="GET",
            path="/workflows/{instance_id}",
            summary="Детальная информация о workflow-инстансе",
            service_getter=_get_facade,
            service_method="get_workflow",
            path_model=WorkflowInstanceIdPath,
            response_model=WorkflowInstanceDetailSchemaOut,
            tags=common_tags,
        ),
        ActionSpec(
            name="admin_get_workflow_events",
            method="GET",
            path="/workflows/{instance_id}/events",
            summary="Paginated event log workflow'а",
            service_getter=_get_facade,
            service_method="get_events",
            path_model=WorkflowInstanceIdPath,
            query_model=EventsQuery,
            response_model=list[WorkflowEventSchemaOut],
            tags=common_tags,
        ),
        ActionSpec(
            name="admin_retry_workflow",
            method="POST",
            path="/workflows/{instance_id}/retry",
            summary="Форсированный retry workflow'а",
            status_code=status.HTTP_202_ACCEPTED,
            service_getter=_get_facade,
            service_method="retry_workflow",
            path_model=WorkflowInstanceIdPath,
            tags=common_tags,
        ),
        ActionSpec(
            name="admin_cancel_workflow",
            method="POST",
            path="/workflows/{instance_id}/cancel",
            summary="Отмена workflow'а (graceful)",
            status_code=status.HTTP_202_ACCEPTED,
            service_getter=_get_facade,
            service_method="cancel_workflow",
            path_model=WorkflowInstanceIdPath,
            body_model=WorkflowCancelRequest,
            tags=common_tags,
        ),
        ActionSpec(
            name="admin_resume_workflow",
            method="POST",
            path="/workflows/{instance_id}/resume",
            summary="Возобновить paused workflow",
            status_code=status.HTTP_202_ACCEPTED,
            service_getter=_get_facade,
            service_method="resume_workflow",
            path_model=WorkflowInstanceIdPath,
            tags=common_tags,
        ),
        ActionSpec(
            name="admin_trigger_workflow",
            method="POST",
            path="/workflows/trigger/{workflow_name}",
            summary="Запустить workflow по имени",
            status_code=status.HTTP_202_ACCEPTED,
            service_getter=_get_facade,
            service_method="trigger_workflow",
            path_model=WorkflowNamePath,
            query_model=TriggerQuery,
            body_model=TriggerBody,
            response_model=WorkflowInstanceRef,
            tags=common_tags,
        ),
    ]
)
