"""Skeleton: IntegrationGroupA — runtime invocation mixin.

S39 W4 classification subagent. Method bodies NOT yet moved here.
The orchestrator will perform the LSP-verified split in a follow-up step.
"""

from __future__ import annotations

__all__ = ("IntegrationGroupA",)


class IntegrationGroupA:
    """Runtime invocation mixin (skeleton).

    Methods that delegate execution to action handlers, workflows, sub-routes
    and Python function references. Returns ``self._add(SomeProcessor(...))``
    via MRO contract.

    Planned methods (6 total, sourced from
    ``src.backend.dsl.builders.integration_core.IntegrationCoreMixin``):

      1. dispatch_action(action, *, payload_factory=None, result_property='action_result')
         -> DispatchActionProcessor
      2. invoke(action, *, mode='sync', payload_factory=None, reply_channel=None,
                result_property='invoke_result', invocation_id_property='invocation_id',
                timeout=None, correlation_id=None)
         -> InvokeProcessor
      3. to_route(route_id, *, result_property='sub_result')
         -> PipelineRefProcessor
      4. invoke_workflow(name, *, mode='async-api', args=None, namespace='default',
                         task_queue='default', result_property='workflow_result',
                         invocation_id_property='invocation_id',
                         reply_timeout_seconds=60.0, version=None)
         -> InvokeWorkflowProcessor
      5. cancel_workflow(workflow_id, *, reason='', namespace='default',
                         result_property='cancel_result')
         -> CancelWorkflowProcessor
      6. call_function(ref, *, payload_from='body', result_property='function_result')
         -> CallFunctionProcessor

    Required imports (deferred until the move):
      - typing: TYPE_CHECKING, Any, Callable
      - src.backend.dsl.builders.base.RouteBuilder (TYPE_CHECKING only)
      - processors: DispatchActionProcessor, InvokeProcessor, PipelineRefProcessor,
        InvokeWorkflowProcessor, CancelWorkflowProcessor, CallFunctionProcessor

    Cross-cutting notes:
      - ``call_function`` uses a different transport (Python import via ref) than
        ``dispatch_action``/``invoke`` (ActionHandlerRegistry), but it is grouped
        here because it still delegates execution to an external callable.
      - All methods return ``"RouteBuilder"`` via ``self._add`` (MRO contract).
    """

    __slots__ = ()
