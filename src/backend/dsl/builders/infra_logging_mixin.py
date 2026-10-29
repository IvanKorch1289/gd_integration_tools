"""InfraLoggingMixin — DSL builders для infrastructure logging processors.

Cycle 170 (ADR-0356): добавлен mixin для интеграции ``InfraLogWriteProcessor``
с :class:`RouteBuilder`. Раньше процессор был задекларирован через
``@processor(\"infra_log_write\", namespace=\"infra\", ...)``, но
отсутствовал как метод builder'а → YAML вызов падал с
``ValueError: Unknown or forbidden processor 'infra_log_write'``.

После mixin: YAML ``- infra_log_write: {level, message}`` корректно
разрешается через :meth:`RouteBuilder.infra_log_write`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.backend.dsl.engine.processors.infra_log import InfraLogWriteProcessor

if TYPE_CHECKING:
    from typing_extensions import Self


class InfraLoggingMixin:
    """Mixin добавляет infrastructure logging processors в builder."""

    if TYPE_CHECKING:
        # type hints для IDE / mypy (mixin не имеет runtime класса).
        def infra_log_write(self, level: str, message: str) -> "Self":
            """Сигнатура метода (реализация — ниже)."""
            ...

    def infra_log_write(self, level: str, message: str) -> Any:
        """Add :class:`InfraLogWriteProcessor` в pipeline.

        Args:
            level: ``debug`` | ``info`` | ``warning`` | ``error`` | ``critical``.
            message: Текст сообщения с опциональной ``${namespace.path}``
                интерполяцией (см. InfraLogWriteProcessor docstring).

        Returns:
            Builder для chaining.

        """
        return self._add(  # type: ignore[attr-defined]
            InfraLogWriteProcessor(level=level, message=message)
        )


__all__ = ("InfraLoggingMixin",)
