"""workflows package (DEPRECATED, S168 W11 P2-7).

S168 W11 P2-7: Master prompt v8 рекомендует merge ``src.backend.workflows.*``
в ``src.backend.infrastructure.workflow.*`` (per Strategy pattern).

Per Ponytail minimum, current commit НЕ перемещает файлы:
- 10+ callers в src/ + tests/ импортируют ``src.backend.workflows.*``
- Полное удаление требует синхронного update всех callers
- 0 functional change в этом commit (только deprecation notice)

Migration plan (separate WIP):
1. Update all callers: ``from src.backend.workflows.X`` →
   ``from src.backend.infrastructure.workflow.X`` (где applicable)
2. Для канонических X (registry, outbox_worker, worker) — move file
3. Для локальных X (dicts, worker_probes) — keep в workflows/ + deprecate
4. Update imports в shutdown.py, startup.py, facade.py, mcp/workflow_tools.py
5. Delete ``src/backend/workflows/`` после всех callers updated

WARNING: Importing из ``src.backend.workflows.*`` сейчас deprecated
и будет удалено в S169+.
"""
