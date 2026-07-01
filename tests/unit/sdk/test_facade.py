"""Тесты для Extension SDK facade (S170 + PLAT-01).

Проверяет что ``src.backend.sdk`` — стабильная публичная API surface:
    - Все элементы из ``__all__`` доступны.
    - Late-bound imports (ConnectorRegistry, get_provider, etc.) работают.
    - Jupyter Hub additions (run_hub_notebook, NotebookSpec, NotebookRegistry).
    - AgentToolPolicy (S170 P0-7).
"""

from __future__ import annotations

import pytest


class TestSdkFacade:
    def test_direct_imports_available(self) -> None:
        from src.backend.sdk import (
            BaseError,
            Clock,
            Exchange,
            Pipeline,
            app_state_singleton,
            get_service,
            register_factory,
        )

        assert Exchange is not None
        assert Pipeline is not None
        assert get_service is not None
        assert register_factory is not None
        assert app_state_singleton is not None
        assert BaseError is not None
        assert Clock is not None

    def test_lazy_imports_resolve(self) -> None:
        from src.backend.sdk import ConnectorRegistry, get_provider, register_provider

        assert ConnectorRegistry is not None
        assert get_provider is not None
        assert register_provider is not None

    def test_jupyter_hub_exports(self) -> None:
        from src.backend.sdk import NotebookRegistry, NotebookSpec, run_hub_notebook

        assert callable(run_hub_notebook)
        assert NotebookSpec is not None
        assert NotebookRegistry is not None

    def test_agent_tool_policy_export(self) -> None:
        from src.backend.sdk import AgentToolPolicy

        assert AgentToolPolicy is not None
        # Sanity: can instantiate
        policy = AgentToolPolicy(agent_id="test", allowed_tools=["x"])
        assert policy.agent_id == "test"

    def test_unknown_attribute_raises(self) -> None:
        from src.backend import sdk

        with pytest.raises(AttributeError, match="no attribute"):
            _ = sdk.__getattr__("does_not_exist")

    def test_sdk_is_in_all(self) -> None:
        """Все документированные экспорты должны быть в __all__."""
        from src.backend import sdk

        documented = {
            "Exchange", "Pipeline", "get_service", "register_factory",
            "app_state_singleton", "BaseError", "Clock",
            "run_hub_notebook", "NotebookSpec", "NotebookRegistry",
            "AgentToolPolicy",
            "ConnectorRegistry", "get_provider", "register_provider",
        }
        assert documented.issubset(set(sdk.__all__)), \
            f"missing from __all__: {documented - set(sdk.__all__)}"
