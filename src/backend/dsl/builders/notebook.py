"""Notebook DSL mixin для RouteBuilder (Sprint 1).

Добавляет chainable методы для создания и выполнения Jupyter notebook'ов.

Контракт mixin: stateless, ``__slots__ = ()``, без instance-атрибутов.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.dsl.builder import RouteBuilder


class NotebookMixin:
    """Notebook execution/export DSL для ``RouteBuilder``."""

    __slots__ = ()

    def notebook_dsl(
        self,
        notebook_path: str,
        *,
        parameters: dict[str, Any] | None = None,
        output_format: str | None = None,
        user_name: str = "default",
        timeout_seconds: float | None = None,
    ) -> RouteBuilder:
        """Выполнить локальный Jupyter notebook с параметрами через JupyterHub.

        Args:
            notebook_path: Локальный путь к ``.ipynb`` файлу.
            parameters: Словарь параметров для инжекции в notebook.
            output_format: Опциональный формат экспорта (``html``, ``pdf``, ``python``).
            user_name: Пользователь JupyterHub (default ``"default"``).
            timeout_seconds: Таймаут выполнения.

        Returns:
            ``RouteBuilder`` для chaining.
        """
        from src.backend.dsl.engine.processors.notebook_dsl import NotebookDSLProcessor

        return self._add(  # type: ignore[attr-defined]
            NotebookDSLProcessor(
                notebook_path=notebook_path,
                parameters=parameters,
                output_format=output_format,
                user_name=user_name,
                timeout_seconds=timeout_seconds,
            )
        )

    def notebook_execute(
        self,
        user_name: str,
        notebook_path: str,
        *,
        timeout_seconds: float | None = None,
    ) -> RouteBuilder:
        """Выполнить Jupyter notebook через JupyterHub.

        Args:
            user_name: Пользователь JupyterHub.
            notebook_path: Путь к notebook (например, ``"analysis.ipynb"``).
            timeout_seconds: Таймаут выполнения (default из settings).

        Returns:
            ``RouteBuilder`` для chaining.
        """
        from src.backend.dsl.engine.processors.notebook_execute import (
            NotebookExecuteProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            NotebookExecuteProcessor(
                user_name=user_name,
                notebook_path=notebook_path,
                timeout_seconds=timeout_seconds,
            )
        )

    def notebook_export(
        self,
        user_name: str,
        notebook_path: str,
        *,
        fmt: str = "html",
        timeout_seconds: float | None = None,
    ) -> RouteBuilder:
        """Экспортировать Jupyter notebook в HTML/PDF/Python.

        Args:
            user_name: Пользователь JupyterHub.
            notebook_path: Путь к notebook.
            fmt: Формат экспорта (``html``, ``pdf``, ``python``).
            timeout_seconds: Таймаут.

        Returns:
            ``RouteBuilder`` для chaining.
        """
        from src.backend.dsl.engine.processors.notebook_export import (
            NotebookExportProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            NotebookExportProcessor(
                user_name=user_name,
                notebook_path=notebook_path,
                fmt=fmt,
                timeout_seconds=timeout_seconds,
            )
        )
