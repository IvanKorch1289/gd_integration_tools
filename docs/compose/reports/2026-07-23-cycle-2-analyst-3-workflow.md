# Cycle 2 — Analyst 3 (Workflow/orchestration) — Consolidated

**Status**: success
**Files scanned**: workflow + orchestration

## P0-1: docstring-outside-docstring (8 files, copy-paste pattern)
Same pattern in all 8: real docstring L1, `from __future__` L7/8, then second `"""..."""` L9+ before actual imports. Orphan string-Expr.
- `infrastructure/workflow/pg_runner_internals/{instance_store,event_store,state,rows}.py:9`
- `dsl/workflow/spec/{workflow,advanced_declarations,activity_declarations,policies}.py:10`

## P0-2: Workflow non-determinism (Temporal scope)
- `dsl/workflow/compiler/step_compilers.py:236` — `datetime.now(UTC).isoformat()` after `workflow.pause()`
- `dsl/workflow/compiler/step_compilers.py:453` — `str(_uuid.uuid4())` when `checkpoint_id` absent; payload mints per replay
- `dsl/workflow/compiler/step_compilers.py:419-427` — `compile_reflect_step` async background, no idempotency key
- `dsl/workflow/compiler/step_compilers.py:463-471` — `compile_checkpoint_step` mutates external store without stable idempotency token
- `dsl/workflow/compiler/activity_bridge.py:198-200` and `:61-74` — DSL action handlers become Temporal activities without enforced `Idempotency-Key`

## P0-3: Saga compensation DEAD CONTRACT
- `infrastructure/workflow/executor/state.py:89` — `WorkflowSpec.compensators: tuple[WorkflowStep, ...] = ()` declared
- `infrastructure/workflow/executor/__init__.py:72-82` — `_compensate_handler` is a no-op
- `infrastructure/workflow/runner.py:395-445` — `_apply_outcome` for FAILED **never invokes `spec.compensators`**
- `core/workflow/backend.py:108-112` — `compensate_workflow` Protocol removed as "unreachable dead contract"
- `dsl/workflow/compiler/step_compilers.py:160-170` — `compile_saga_step` silently skips compensation if `len(decl.compensate) < len(forward)` with **0 warnings**
- 8 workflow templates have external side-effects without compensation:
  - `incident_response`, `multi_step_approval`, `webhook_pipeline`, `report_generation`, `scheduled_audit`, `data_quality_pipeline`, `ml_training_pipeline`, `kyc_aml_check` (last has 3 forward / 1 compensate — silent no-op on 2/3)

## P1-4: Retry policy inconsistency (4+ parallel types)
- `core/ai/retry_policy.py:29-60` — `max_attempts=3, initial_interval_s=1.0, backoff_coefficient=2.0` (Pydantic)
- `core/resilience/retry.py:67-120` — different fields
- `core/resilience/connector_retry.py:68-69` — `max_attempts=3, initial_backoff=1.0`
- `core/resilience/connector_resilience.py:42-43` — `max_attempts=3, initial_backoff=0.5`
- `max_attempts=10` hardcoded in 3 places (runner, executor, registry)
- **Field name mismatch**: `ml_training_pipeline.workflow.yaml:6-11` uses `maximum_attempts` but Pydantic model uses `max_attempts` → **silently ignored**
- 8 sinks have different retry defaults (file_sink=2, s3_sink=5, mq_sink=5, nats_jetstream=5, email_sink=3, sms_sink=3, http_sink=3, others=3)

## P1-5: Hardcoded timeouts
- `_default_timeout_s = 300.0` in 5 places
- Many `timedelta(seconds=10/30/60)` magic numbers in `step_compilers.py`
- `wait_mixin.py:42-44` — HITL `human_approval` default 1h
- 20+ other files with hardcoded timeouts

## P0-8: Cross-domain import violations
- `dsl/workflow/compiler/activity_bridge.py:93,130` — DSL → services
- `infrastructure/workflow/executor/sequential_mixin.py:68` — infrastructure → dsl internals
- `infrastructure/workflow/worker.py:156,157` — infrastructure → dsl (2 violations)

## P1-9: Dead code (4 services/workflows components)
- `sla_alerting.py:195` — `SlaTracker`: zero production instantiation
- `sla_alerting.py:83,91` — `SlaAlertDispatcher` Protocol + `InMemorySlaAlertDispatcher`: only in tests
- `reactive_dispatcher.py:33,50` — `ReactiveTrigger`/`ReactiveWorkflowDispatcher`: zero production callers
- `hitl_pubsub_consumer.py:56` — `HitlPubSubConsumer`: no production wiring

## Verified clean
- 0 WorkflowBuilder duals (s213 unification is complete)
- 0 PII in workflow logs
