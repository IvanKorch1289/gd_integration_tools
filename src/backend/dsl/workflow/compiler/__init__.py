"""DSL Workflow Compiler — материализация WorkflowDeclaration в Temporal-classes.

План V16.1 §4 Sprint 4 (К3): декларативный workflow YAML/Python builder
компилируется в Temporal ``@workflow.defn`` классы. Эти классы можно
запустить через ``LiteTemporalBackend`` (dev_light) или реальный Temporal
кластер (staging/prod) — поведение идентично.

Public API:
    * :func:`compile_workflow` — :class:`WorkflowDeclaration` →
      динамически сгенерированный workflow-класс
      (``@workflow.defn``).
    * :func:`compile_workflows` — bulk-вариант для списка деклараций.
    * :class:`CompiledWorkflow` — пара (workflow-class, имя),
      используется при регистрации в Worker.
    * :func:`get_activity_callables` — получить список activity
      функций для регистрации в Worker (через :mod:`activity_bridge`).
    * :class:`WorkflowCompilerRegistry` — кеш скомпилированных
      воркфлоу (deterministic re-emission, hot-reload safe).

Архитектура:
    * Компилятор использует динамическое ``type()`` для генерации
      классов вместо Jinja2-codegen в файл — это убирает второй
      источник правды и snapshot-race при hot-reload.
    * ``temporalio`` импортируется **лениво** только при первом
      обращении к compiler (heavy ~15-20MB SDK). Импорт
      :mod:`dsl.workflow.compiler` БЕЗ ``temporalio`` бросает
      понятную ошибку с инструкцией ``uv sync --extra workflow``.
    * Activity-функции собираются через :mod:`activity_bridge` —
      обёртки над DSL action handlers, регистрируемые лениво в
      :func:`register_workflows_with_temporal`. Workflow-сэндбокс
      не импортирует I/O.
"""

from __future__ import annotations

from src.backend.dsl.workflow.compiler.activity_bridge import (
    ActivityBridge,
    bridge_action_handler,
    get_activity_callables,
)
from src.backend.dsl.workflow.compiler.emitter import (
    CompiledWorkflow,
    compile_workflow,
    compile_workflows,
)
from src.backend.dsl.workflow.compiler.registry import WorkflowCompilerRegistry

__all__ = (
    "ActivityBridge",
    "CompiledWorkflow",
    "WorkflowCompilerRegistry",
    "bridge_action_handler",
    "compile_workflow",
    "compile_workflows",
    "get_activity_callables",
)
