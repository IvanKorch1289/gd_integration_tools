"""In-memory реестр доступных notebook'ов для Hub execution (S170 NEW).

Связывает ``notebook_name`` (slug, без расширения) с путём на JupyterHub
user-server'е. Заполняется из:
  1. YAML-конфига ``notebooks_dir/<name>.yaml`` (preferred — versioned)
  2. Конвенции ``<notebooks_dir>/<name>.ipynb`` (fallback)

Использование::

    registry = get_notebook_registry()
    notebook = registry.get("credit_scoring")
    if notebook is None:
        raise JupyterNotebookNotFoundError("credit_scoring")
    # notebook.path → "notebooks/credit_scoring.ipynb"
    # notebook.parameters_schema → {"customer_id": "int", "...": "..."}

Public API:
    * :class:`NotebookSpec` — описание одного notebook (name, path, params).
    * :class:`NotebookRegistry` — реестр с методами register/list/get.
    * :func:`get_notebook_registry` — singleton accessor (lazy).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from src.backend.core.logging import get_logger

_logger = get_logger("services.jupyter.notebook_registry")


class NotebookSpec(BaseModel):
    """Описание одного notebook для Hub execution.

    Attributes:
        name: Slug без расширения (e.g., ``"credit_scoring"``).
        path: Путь на JupyterHub user-server (e.g.,
            ``"notebooks/credit_scoring.ipynb"``).
        description: Человекочитаемое описание.
        parameters_schema: Схема ожидаемых параметров (key → type/description).
            Используется для валидации inputs перед papermill execute.
        default_parameters: Defaults для параметров.
        timeout_seconds: Таймаут на выполнение.
        kernel: Имя kernel (e.g., ``"python3"``).
    """

    name: str = Field(..., min_length=1, max_length=200)
    path: str = Field(..., min_length=1)
    description: str = ""
    parameters_schema: dict[str, Any] = Field(default_factory=dict)
    default_parameters: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: float = Field(default=300.0, gt=0.0, le=3600.0)
    kernel: str = "python3"

    def validate_parameters(self, params: dict[str, Any]) -> list[str]:
        """Return list of validation errors (empty if valid).

        Сверяет входные параметры с parameters_schema (тип или enum).
        Простая проверка без JSONSchema — достаточно для DSL.
        """
        errors: list[str] = []
        for key, spec in self.parameters_schema.items():
            if key not in params and key not in self.default_parameters:
                errors.append(f"missing required parameter: {key!r}")
                continue
            value = params.get(key, self.default_parameters.get(key))
            expected = spec.get("type") if isinstance(spec, dict) else None
            if expected and not _type_matches(value, expected):
                errors.append(
                    f"parameter {key!r}: expected type {expected!r}, "
                    f"got {type(value).__name__}"
                )
        return errors


def _type_matches(value: Any, expected: str) -> bool:
    """Минимальная type-mapping для DSL parameter validation."""
    mapping: dict[str, type | tuple[type, ...]] = {
        "str": str,
        "string": str,
        "int": int,
        "integer": int,
        "float": float,
        "number": (int, float),
        "bool": bool,
        "boolean": bool,
        "list": list,
        "array": list,
        "dict": dict,
        "object": dict,
    }
    py_type = mapping.get(expected.lower())
    if py_type is None:
        return True  # unknown type → no check
    return isinstance(value, py_type)


@dataclass
class _RegistryState:
    """Mutable registry state behind a lock."""

    notebooks: dict[str, NotebookSpec] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)


class NotebookRegistry:
    """Thread-safe in-memory реестр notebook specifications."""

    def __init__(self) -> None:
        self._state = _RegistryState()

    def register(self, spec: NotebookSpec, *, override: bool = False) -> None:
        """Register notebook spec. Default — fail on duplicate."""
        with self._state.lock:
            if spec.name in self._state.notebooks and not override:
                raise ValueError(f"notebook already registered: {spec.name!r}")
            self._state.notebooks[spec.name] = spec
            _logger.debug("Registered notebook: name=%s path=%s", spec.name, spec.path)

    def register_from_directory(
        self,
        notebooks_dir: Path | str,
        *,
        notebook_dir_prefix: str = "",
    ) -> int:
        """Scan ``notebooks_dir`` for ``<name>.ipynb`` and register.

        Используется как fallback, когда нет YAML manifests.
        Параметры — пустые (caller обязан передать их явно).

        Returns:
            Количество зарегистрированных notebooks.
        """
        dir_path = Path(notebooks_dir)
        if not dir_path.is_dir():
            _logger.debug("Notebooks dir not found: %s", dir_path)
            return 0
        count = 0
        for ipynb_path in sorted(dir_path.glob("*.ipynb")):
            name = ipynb_path.stem
            spec = NotebookSpec(
                name=name,
                path=f"{notebook_dir_prefix}{ipynb_path.name}",
                description=f"Auto-registered from {dir_path}",
            )
            try:
                self.register(spec)
                count += 1
            except ValueError:
                _logger.debug("Skip duplicate notebook: %s", name)
        return count

    def get(self, name: str) -> NotebookSpec | None:
        """Получить spec по name. ``None`` если не найден."""
        with self._state.lock:
            return self._state.notebooks.get(name)

    def list_names(self) -> list[str]:
        """Вернуть все зарегистрированные имена."""
        with self._state.lock:
            return sorted(self._state.notebooks.keys())

    def clear(self) -> None:
        """Очистить реестр (для тестов)."""
        with self._state.lock:
            self._state.notebooks.clear()


# Singleton accessor
_registry_singleton: NotebookRegistry | None = None
_registry_lock = threading.Lock()


def get_notebook_registry() -> NotebookRegistry:
    """Вернуть singleton :class:`NotebookRegistry`.

    Lazy-init — создаётся при первом обращении.
    """
    global _registry_singleton
    with _registry_lock:
        if _registry_singleton is None:
            _registry_singleton = NotebookRegistry()
        return _registry_singleton


def reset_notebook_registry() -> None:
    """Сброс singleton (для тестов)."""
    global _registry_singleton
    with _registry_lock:
        _registry_singleton = None


__all__ = (
    "NotebookRegistry",
    "NotebookSpec",
    "get_notebook_registry",
    "reset_notebook_registry",
)
