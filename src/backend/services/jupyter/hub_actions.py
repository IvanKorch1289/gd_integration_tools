"""Jupyter Hub actions для DSL (S170 NEW).

Регистрирует action ``jupyter.hub_run`` в :class:`ActionHandlerRegistry`.

Action вызывает ``services/jupyter/hub_run_orchestrator.run_hub_notebook``:
  - Input (минимальный): ``{"notebook_name": "credit_scoring", "parameters": {...}}``
  - Input (inline file): ``{"notebook_content": b"...", "parameters": {...}}``
  - Input (base64 для JSON-RPC): ``{"notebook_content_b64": "...", "parameters": {...}}``
  - Output: ``HubRunResult`` (dataclass → dict).

Capability gate: ``jupyter.hub.run``.

Доступно через любой протокол:
  - REST:    POST /api/v1/jupyter/run (multipart + JSON)
  - GraphQL: mutation `jupyterHubRun(...)`
  - SOAP:    <JupyterHubRun> envelope
  - MCP:     tool `jupyter_hub_run`
  - WS:      {"action": "jupyter.hub_run", ...}
"""

from __future__ import annotations

import base64
from dataclasses import asdict
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.services.jupyter.hub_run_orchestrator import (
    HubRunError,
    HubRunResult,
    run_hub_notebook,
)

_logger = get_logger("services.jupyter.hub_actions")


class _RunHubNotebookService:
    """Service-фасад для action-обработчиков.

    Поддерживает все источники notebook (mutually compatible):
    - ``notebook_name`` (slug из реестра)
    - ``notebook_path`` (прямой путь к .ipynb на Hub)
    - ``notebook_content`` (bytes — для multipart)
    - ``notebook_content_b64`` (base64 — для JSON-RPC)
    """

    async def run(
        self,
        notebook_name: str | None = None,
        parameters: dict[str, Any] | None = None,
        user_name: str = "default",
        notebook_path: str | None = None,
        notebook_content: bytes | None = None,
        notebook_content_b64: str | None = None,
        output_path: str | None = None,
        **_extra: Any,
    ) -> dict[str, Any]:
        """Run notebook и вернуть HubRunResult как dict.

        Raises:
            HubRunError: при любой ошибке (not found, validation, hub).
        """
        content: bytes | None = notebook_content
        if notebook_content_b64 is not None:
            try:
                content = base64.b64decode(notebook_content_b64, validate=True)
            except (ValueError, base64.binascii.Error) as exc:
                raise HubRunError(
                    f"notebook_content_b64 is not valid base64: {exc}"
                ) from exc

        # Notebook name: требуется всегда (для logging/audit)
        effective_name = notebook_name
        if not effective_name:
            if notebook_path:
                effective_name = notebook_path.rsplit("/", 1)[-1].replace(".ipynb", "")
            elif content is not None:
                effective_name = "inline_notebook"
            else:
                raise HubRunError(
                    "either notebook_name, notebook_path or notebook_content required"
                )

        result: HubRunResult = await run_hub_notebook(
            notebook_name=effective_name,
            parameters=parameters,
            user_name=user_name,
            notebook_content=content,
            notebook_path_override=notebook_path,
            output_path=output_path,
        )
        return asdict(result)


_run_hub_service = _RunHubNotebookService()


def get_jupyter_hub_run_service() -> _RunHubNotebookService:
    """Service-getter для ActionHandlerSpec."""
    return _run_hub_service


def register_jupyter_hub_actions(registry: Any) -> list[str]:
    """Регистрирует ``jupyter.hub_run`` action в registry.

    Args:
        registry: :class:`ActionHandlerRegistry` instance.

    Returns:
        Список зарегистрированных action-имён.
    """
    from src.backend.dsl.commands.action_registry import ActionHandlerSpec

    spec = ActionHandlerSpec(
        action="jupyter.hub_run",
        service_getter=get_jupyter_hub_run_service,
        service_method="run",
        payload_model=None,  # pydantic validation skipped (DSL layer)
    )

    # ``register()`` keyword-only (action=, service_getter=, ...) и принимает
    # не spec. ``register_with_metadata()`` — для Gateway-слоя с metadata.
    # Правильный entry-point для готового ActionHandlerSpec — ``register_many``.
    if hasattr(registry, "register_many"):
        registry.register_many([spec])
    elif hasattr(registry, "register"):
        registry.register(
            action=spec.action,
            service_getter=spec.service_getter,
            service_method=spec.service_method,
            payload_model=spec.payload_model,
        )
    else:
        raise TypeError(
            f"registry {type(registry).__name__} has no register/registration method"
        )

    _logger.info("Registered jupyter.hub_run action")
    return ["jupyter.hub_run"]


__all__ = (
    "get_jupyter_hub_run_service",
    "register_jupyter_hub_actions",
)
