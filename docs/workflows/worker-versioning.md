# Worker Versioning (S171 M10 P0, D172)

Temporal **Worker Versioning** — механизм безопасного rollout workflow-кода
через BuildID-based pinning.

## Зачем

- Workflow executions долгоживущие (дни/недели)
- При deploy нового кода: старые executions должны continue на старой версии
- Native `workflow.patched()` API deprecated → BuildID + VersioningIntent

## Использование

```python
from src.backend.infrastructure.workflow.versioning.worker_versioning import (
    WorkerVersioningHelper,
    VersioningPolicy,
)

helper = WorkerVersioningHelper(
    deployment_name="gd-integration-tools",
    build_id="1.0.0",  # semver, git SHA, или custom
    use_versioning=True,
    policy=VersioningPolicy(
        deployment_name="gd-integration-tools",
        build_id="1.0.0",
        ramp_percentage=25,  # 25% нового трафика на этой версии
    ),
)

# kwargs для temporalio.worker.Worker()
worker_kwargs = helper.build_worker_kwargs()
worker = Worker(
    client,
    task_queue="orders",
    workflows=[...],
    activities=[...],
    **worker_kwargs,
)
```

## Backward-compat

При `use_versioning=False` (default) helper возвращает пустой dict —
Worker создаётся БЕЗ versioning (как раньше).

## Ramp rollout

```python
# Неделя 1: 10% трафика на новой версии
policy = VersioningPolicy("gd", "1.0.0", ramp_percentage=10)

# Неделя 2: 50% — если метрики OK
policy = VersioningPolicy("gd", "1.0.0", ramp_percentage=50)

# Неделя 3: 100% — sunset старой версии
policy = VersioningPolicy("gd", "1.0.0", ramp_percentage=100)
```

## Refs

- https://docs.temporal.io/production-deployment/worker-deployments/worker-versioning
- D172 Worker Versioning pattern
