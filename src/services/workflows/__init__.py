"""Service-слой workflow-orchestration (Wave D.2 / ADR-045).

`WorkflowFacade` оборачивает `WorkflowBackend` Protocol с
capability-gate проверкой (`workflow.start` / `workflow.signal`),
чтобы плагины и DSL-routes не имели прямого доступа к backend.
"""

from src.services.workflows.facade import WorkflowFacade

__all__ = ("WorkflowFacade",)
