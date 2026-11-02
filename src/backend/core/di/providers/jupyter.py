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


def get_hub_run_provider() -> Any:
    """Вернуть ``run_hub_notebook`` — мост core→services для провайдера.

    ADR-0415: capability-провайдер ``jupyter.hub`` живёт в расширении
    (``extensions/jupyter_hub/``), а расширения по правилам слоёв не могут
    импортировать ``services/*`` напрямую. Этот DI-провайдер — sanctioned
    composition root (``core/di/providers/``), через который провайдер
    получает оркестратор запуска ноутбуков.

    Импорт late (внутри функции), чтобы не тянуть services-модуль при
    импорте core.

    Returns:
        Callable ``run_hub_notebook`` (async).
    """
    if "hub_run" in _overrides:
        return _overrides["hub_run"]
    from src.backend.services.jupyter.hub_run_orchestrator import run_hub_notebook

    _overrides["hub_run"] = run_hub_notebook
    return run_hub_notebook


def set_notebook_execution_service_provider(impl: Any) -> None:
    """Test-override для NotebookExecutionService."""
    _overrides["notebook_execution_service"] = impl


def set_hub_run_provider(impl: Any) -> None:
    """Test-override для ``run_hub_notebook``."""
    _overrides["hub_run"] = impl


def reset_notebook_execution_service_overrides() -> None:
    """Test-helper: сбрасывает singleton cache между тестами."""
    _overrides.clear()
