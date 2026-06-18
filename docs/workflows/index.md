# Workflows

Temporal (production) + LiteTemporalBackend (dev_light).

## Архитектура

```
src/backend/workflows/
├── worker.py           # Temporal worker (S67)
├── temporal/           # Production Temporal integration
├── lite_temporal.py    # dev_light backend
└── compiler/           # DSL → Temporal workflow compiler
```

## DSL

```python
route.invoke_workflow("credit_check.full", wait=True, timeout=300.0)
```

## Режимы

- **Production**: Temporal.io cluster
- **dev_light**: LiteTemporalBackend (in-process)

## Возможности

- HITL (Human-in-the-loop) signals
- Saga compensations (LRA pattern)
- Subworkflows (with/without wait)
- Pause/resume/continue
- Failure recovery
- Retry policies (exponential backoff)
- Async, parallel, sequential

## См. также

- [DSL](../dsl/index.md)