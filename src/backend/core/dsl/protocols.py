"""S115 W1 — DSL Protocol abstractions (core layer, импортируется всеми).

Решает проблему S114: core/services/entrypoints импортируют
``src.backend.dsl.*`` напрямую, что нарушает layer policy (DSL = meta-layer
по R3.10d, импортирует всё, а не наоборот).

Решение: Protocol-базированная инверсия. Core определяет минимальный
контракт, который ему нужен от DSL (Command, Pipeline, Engine). DSL
реализует эти Protocol'ы в своих модулях и регистрирует через
:func:`register_command`, :func:`register_pipeline` (см. ``dsl/registry.py``,
будет добавлено в S115 W3).

Usage (core layer)::

    from src.backend.core.dsl.protocols import CommandRegistry

    def my_service(registry: CommandRegistry) -> None:
        registry.execute("waf.scan", payload={"url": "..."})

    # В TypeScript-like duck typing — runtime check, no import.

Current scope (S115 W1):
- ``CommandRegistry`` Protocol: ``execute(name, payload)`` + ``register(cmd)``
- ``Pipeline`` Protocol: ``run(input)`` + ``steps: list``
- ``ExecutionEngine`` Protocol: ``run_pipeline(pipeline)`` + ``tracer``

Migration plan (S115 W2-W4):
- W2: мигрирует ``services/dsl_portal/builder_facade.py`` (5 violations)
- W3: мигрирует ``services/dsl/builder_service.py`` + ``services/plugins/registries.py``
- W4: мигрирует ``entrypoints/{dsl_routes,graphql/schema,imports}.py``
       + ``infrastructure/observability/{metrics,tracing}.py``

Backward compat: Protocol + ``runtime_checkable`` — existing concrete
classes (``ExecutionEngine``, ``Pipeline``) могут быть проверены через
``isinstance(obj, ExecutionEngineProtocol)`` без изменений.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class CommandRegistryProtocol(Protocol):
    """Минимальный контракт registry для DSL-команд.

    Реализуется в :mod:`src.backend.dsl.commands.registry` (S115 W3).
    """

    def execute(self, name: str, *, payload: dict[str, Any] | None = None) -> Any:
        """Выполняет зарегистрированную команду.

        Args:
            name: Имя команды (например, ``"waf.scan"``).
            payload: Параметры команды.

        Returns:
            Результат выполнения (type зависит от команды).
        """
        ...

    def register(self, name: str, handler: Any) -> None:
        """Регистрирует новую команду.

        Args:
            name: Имя команды.
            handler: Callable handler.
        """
        ...


@runtime_checkable
class PipelineProtocol(Protocol):
    """Минимальный контракт DSL pipeline.

    Реализуется в :class:`src.backend.dsl.engine.pipeline.Pipeline`.
    """

    steps: list[Any]

    def run(self, input: Any) -> Any:
        """Запускает pipeline.

        Args:
            input: Входные данные pipeline.

        Returns:
            Выходные данные pipeline.
        """
        ...


@runtime_checkable
class ExecutionEngineProtocol(Protocol):
    """Минимальный контракт execution engine.

    Реализуется в :class:`src.backend.dsl.engine.execution_engine.ExecutionEngine`.
    """

    def run_pipeline(self, pipeline: PipelineProtocol) -> Any:
        """Запускает pipeline через engine.

        Args:
            pipeline: Pipeline для выполнения.

        Returns:
            Результат выполнения.
        """
        ...

    def tracer(self) -> Any:
        """Возвращает tracer для observability."""
        ...


# Aliases для обратной совместимости (S115 W2+ migration).
CommandRegistry = CommandRegistryProtocol
Pipeline = PipelineProtocol
ExecutionEngine = ExecutionEngineProtocol


__all__ = (
    "CommandRegistry",
    "CommandRegistryProtocol",
    "ExecutionEngine",
    "ExecutionEngineProtocol",
    "Pipeline",
    "PipelineProtocol",
)
