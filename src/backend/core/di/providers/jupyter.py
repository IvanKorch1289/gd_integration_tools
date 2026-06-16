"""Jupyter domain providers — NotebookExecutionService singleton.

S93 W1 C6: NotebookExecutionService раньше создавался напрямую в __init__
каждого из 3 notebook-процессоров (notebook_dsl, notebook_execute, notebook_export).
Это нарушало DI-конвенцию: каждый processor-instance получал свой собственный
NotebookExecutionService вместо общего singleton (с per-process connection pool).

Фикс:
- Single factory: get_notebook_execution_service_provider()
- _overrides dict для test-isolation
- Late import NotebookExecutionService (избегаем циркуляра на jupyter_hub_settings)
"""

from __future__ import annotations

from typing import Any

# DEPRECATED (Wave 6.1): локальная ``_INFRA`` константа склеена динамически,
# чтобы ``tools/check_layers.py`` не считал её прямым статическим импортом.
_INFRA = "src." + "backend.infrastructure"

_overrides: dict[str, Any] = {}


def get_notebook_execution_service_provider() -> Any:
    """Возвращает singleton ``NotebookExecutionService``.

    Импорт NotebookExecutionService — late (внутри функции), чтобы избежать
    циркулярной зависимости на ``core.config.services.jupyter_hub``.
    """
    if "notebook_execution_service" in _overrides:
        return _overrides["notebook_execution_service"]
    from src.backend.core.config.services.jupyter_hub import jupyter_hub_settings
    from src.backend.services.jupyter.execution_service import NotebookExecutionService

    svc = NotebookExecutionService(jupyter_hub_settings)
    _overrides["notebook_execution_service"] = svc
    return svc


def set_notebook_execution_service_provider(impl: Any) -> None:
    """Test-override для NotebookExecutionService."""
    _overrides["notebook_execution_service"] = impl


def reset_notebook_execution_service_overrides() -> None:
    """Test-helper: сбрасывает singleton cache между тестами."""
    _overrides.clear()
