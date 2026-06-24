"""Capability-checked facade для JupyterHub client (S123 W3).

ADR-0207: services/jupyter/execution_service/__init__.py импортирует
``JupyterHubClient`` из ``infrastructure.clients.external.jupyter_hub``.
"""

from __future__ import annotations

from src.backend.core.di.providers.infrastructure_facade import (  # noqa: F401
    get_jupyter_hub_client_class as _get_jhc_cls,
    get_jupyter_hub_error_class as _get_jhe_cls,
    get_jupyter_hub_server_class as _get_jhs_cls,
    get_jupyter_hub_user_class as _get_jhu_cls,
)
JupyterHubClient = _get_jhc_cls()
JupyterHubError = _get_jhe_cls()
JupyterHubServer = _get_jhs_cls()
JupyterHubUser = _get_jhu_cls()

__all__ = ("JupyterHubClient", "JupyterHubError", "JupyterHubServer", "JupyterHubUser")
