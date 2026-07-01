"""Unit-тесты для Jupyter Hub run orchestrator (S170 NEW).

Покрытие:
    * NotebookSpec.validate_parameters
    * NotebookRegistry.register/get/list
    * run_hub_notebook happy path (с mock execution_service)
    * run_hub_notebook error paths:
        - feature flag OFF → JupyterHubNotEnabledError
        - notebook not found → NotebookNotFoundError
        - parameters invalid → NotebookParameterError
        - execution error → JupyterExecutionError propagated
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.core.config.features import feature_flags
from src.backend.services.jupyter.hub_run_orchestrator import (
    HubRunResult,
    JupyterHubNotEnabledError,
    NotebookNotFoundError,
    NotebookParameterError,
    run_hub_notebook,
)
from src.backend.services.jupyter.notebook_registry import (
    NotebookRegistry,
    NotebookSpec,
)


@pytest.fixture(autouse=True)
def _enable_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enable jupyter_hub_enabled flag for most tests."""
    monkeypatch.setattr(feature_flags, "jupyter_hub_enabled", True)


@pytest.fixture
def registry() -> NotebookRegistry:
    return NotebookRegistry()


class TestNotebookSpecValidation:
    def test_validate_minimal_no_schema(self) -> None:
        spec = NotebookSpec(name="x", path="x.ipynb")
        assert spec.validate_parameters({}) == []

    def test_validate_required_missing(self) -> None:
        spec = NotebookSpec(
            name="x",
            path="x.ipynb",
            parameters_schema={"customer_id": {"type": "int"}},
        )
        errors = spec.validate_parameters({})
        assert any("customer_id" in e for e in errors)

    def test_validate_type_mismatch(self) -> None:
        spec = NotebookSpec(
            name="x",
            path="x.ipynb",
            parameters_schema={"amount": {"type": "float"}},
        )
        errors = spec.validate_parameters({"amount": "not_a_number"})
        assert any("amount" in e and "float" in e for e in errors)

    def test_validate_with_defaults(self) -> None:
        spec = NotebookSpec(
            name="x",
            path="x.ipynb",
            parameters_schema={"region": {"type": "str"}},
            default_parameters={"region": "EU"},
        )
        assert spec.validate_parameters({}) == []


class TestNotebookRegistry:
    def test_register_and_get(self) -> None:
        reg = NotebookRegistry()
        spec = NotebookSpec(name="alpha", path="alpha.ipynb")
        reg.register(spec)
        assert reg.get("alpha") == spec

    def test_register_duplicate_raises(self) -> None:
        reg = NotebookRegistry()
        spec = NotebookSpec(name="alpha", path="alpha.ipynb")
        reg.register(spec)
        with pytest.raises(ValueError, match="already registered"):
            reg.register(spec)

    def test_register_override(self) -> None:
        reg = NotebookRegistry()
        reg.register(NotebookSpec(name="alpha", path="alpha.ipynb"))
        reg.register(NotebookSpec(name="alpha", path="alpha_v2.ipynb"), override=True)
        assert reg.get("alpha").path == "alpha_v2.ipynb"

    def test_get_missing_returns_none(self) -> None:
        reg = NotebookRegistry()
        assert reg.get("absent") is None

    def test_list_names_sorted(self) -> None:
        reg = NotebookRegistry()
        for name in ("z", "a", "m"):
            reg.register(NotebookSpec(name=name, path=f"{name}.ipynb"))
        assert reg.list_names() == ["a", "m", "z"]


class TestRunHubNotebookHappyPath:
    async def test_runs_registered_notebook(
        self, registry: NotebookRegistry
    ) -> None:
        registry.register(
            NotebookSpec(
                name="credit_scoring",
                path="notebooks/credit.ipynb",
                default_parameters={"threshold": 0.5},
                parameters_schema={"customer_id": {"type": "int"}},
            )
        )

        mock_svc = AsyncMock()
        mock_svc.execute.return_value = {
            "outputs": [
                {
                    "cell_index": 0,
                    "outputs": [{"output_type": "stream", "text": "score=0.85"}],
                }
            ]
        }

        result = await run_hub_notebook(
            notebook_name="credit_scoring",
            parameters={"customer_id": 42},
            registry=registry,
            execution_service=mock_svc,
        )

        assert isinstance(result, HubRunResult)
        assert result.notebook_name == "credit_scoring"
        assert result.notebook_path == "notebooks/credit.ipynb"
        assert result.parameters == {"customer_id": 42, "threshold": 0.5}
        assert result.cells_executed == 1
        assert result.errors == []
        mock_svc.execute.assert_awaited_once()
        call_kwargs = mock_svc.execute.await_args.kwargs
        assert call_kwargs["notebook_path"] == "notebooks/credit.ipynb"
        assert call_kwargs["parameters"] == {"customer_id": 42, "threshold": 0.5}
        assert call_kwargs["user_name"] == "default"

    async def test_passes_user_name_through(
        self, registry: NotebookRegistry
    ) -> None:
        registry.register(NotebookSpec(name="x", path="x.ipynb"))
        mock_svc = AsyncMock()
        mock_svc.execute.return_value = {"outputs": []}

        await run_hub_notebook(
            notebook_name="x", user_name="alice", registry=registry,
            execution_service=mock_svc,
        )
        assert mock_svc.execute.await_args.kwargs["user_name"] == "alice"


class TestRunHubNotebookErrors:
    async def test_feature_flag_off_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(feature_flags, "jupyter_hub_enabled", False)
        mock_svc = AsyncMock()
        with pytest.raises(JupyterHubNotEnabledError):
            await run_hub_notebook(
                notebook_name="any", execution_service=mock_svc,
                registry=NotebookRegistry(),
            )
        mock_svc.execute.assert_not_awaited()

    async def test_notebook_not_found_raises(
        self, registry: NotebookRegistry
    ) -> None:
        mock_svc = AsyncMock()
        with pytest.raises(NotebookNotFoundError, match="absent"):
            await run_hub_notebook(
                notebook_name="absent",
                registry=registry,
                execution_service=mock_svc,
            )
        mock_svc.execute.assert_not_awaited()

    async def test_parameter_validation_raises(
        self, registry: NotebookRegistry
    ) -> None:
        registry.register(
            NotebookSpec(
                name="strict",
                path="strict.ipynb",
                parameters_schema={"customer_id": {"type": "int"}},
            )
        )
        mock_svc = AsyncMock()
        with pytest.raises(NotebookParameterError) as excinfo:
            await run_hub_notebook(
                notebook_name="strict",
                parameters={"customer_id": "not_int"},
                registry=registry,
                execution_service=mock_svc,
            )
        assert "customer_id" in str(excinfo.value)
        mock_svc.execute.assert_not_awaited()

    async def test_execution_error_propagates(
        self, registry: NotebookRegistry
    ) -> None:
        registry.register(NotebookSpec(name="x", path="x.ipynb"))
        mock_svc = AsyncMock()
        from src.backend.services.jupyter.execution_service import JupyterExecutionError

        mock_svc.execute.side_effect = JupyterExecutionError("kernel died")

        with pytest.raises(JupyterExecutionError, match="kernel died"):
            await run_hub_notebook(
                notebook_name="x",
                registry=registry,
                execution_service=mock_svc,
            )


class TestCollectErrors:
    async def test_collects_cell_errors(
        self, registry: NotebookRegistry
    ) -> None:
        registry.register(NotebookSpec(name="x", path="x.ipynb"))
        mock_svc = AsyncMock()
        mock_svc.execute.return_value = {
            "outputs": [
                {
                    "cell_index": 1,
                    "outputs": [
                        {
                            "output_type": "error",
                            "ename": "ZeroDivisionError",
                            "evalue": "division by zero",
                        }
                    ],
                }
            ]
        }

        result = await run_hub_notebook(
            notebook_name="x",
            registry=registry,
            execution_service=mock_svc,
        )
        assert len(result.errors) == 1
        assert "ZeroDivisionError" in result.errors[0]
        assert "division by zero" in result.errors[0]


class TestHubRunAdapter:
    async def test_adapter_returns_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Adapter должен вернуть dict, не dataclass (DSL compatibility)."""
        monkeypatch.setattr(feature_flags, "jupyter_hub_enabled", True)

        from src.backend.services.jupyter import hub_run_adapter
        from src.backend.services.jupyter.hub_run_adapter import run as adapter_run

        async def _fake_run(*args: Any, **kwargs: Any) -> HubRunResult:
            return HubRunResult(
                notebook_name=kwargs.get("notebook_name", "x"),
                notebook_path="x.ipynb",
                parameters=kwargs.get("parameters", {"a": 1}),
                outputs=[],
                duration_seconds=0.5,
                cells_executed=0,
                errors=[],
            )

        monkeypatch.setattr(hub_run_adapter, "run_hub_notebook", _fake_run)

        result = await adapter_run("x", {"a": 1})
        assert isinstance(result, dict)
        assert result["notebook_name"] == "x"
        assert result["parameters"] == {"a": 1}


class TestRunHubNotebookInline:
    """S170 EXT: inline notebook content (multipart/SOAP/GraphQL)."""

    async def test_inline_notebook_bytes(
        self, registry: NotebookRegistry, tmp_path: Path
    ) -> None:
        """Inline bytes (.ipynb JSON) → save to temp → execute."""
        notebook_json = (
            b'{"cells": [{"cell_type": "code", "source": "print(1)"}], '
            b'"metadata": {}, "nbformat": 4, "nbformat_minor": 5}'
        )
        mock_svc = AsyncMock()
        mock_svc.execute.return_value = {"outputs": []}

        result = await run_hub_notebook(
            notebook_name="inline_test",
            notebook_content=notebook_json,
            output_path=str(tmp_path / "inline.ipynb"),
            registry=registry,
            execution_service=mock_svc,
        )

        assert result.notebook_name == "inline_test"
        assert result.notebook_path == str(tmp_path / "inline.ipynb")
        # Notebook файл записан
        assert (tmp_path / "inline.ipynb").exists()
        mock_svc.execute.assert_awaited_once()

    async def test_inline_notebook_str(
        self, registry: NotebookRegistry, tmp_path: Path
    ) -> None:
        """Inline str (.ipynb JSON) — также принимается."""
        notebook_json = (
            '{"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}'
        )
        mock_svc = AsyncMock()
        mock_svc.execute.return_value = {"outputs": []}

        await run_hub_notebook(
            notebook_name="inline_str",
            notebook_content=notebook_json,
            output_path=str(tmp_path / "inline_s.ipynb"),
            registry=registry,
            execution_service=mock_svc,
        )
        assert (tmp_path / "inline_s.ipynb").exists()

    async def test_inline_invalid_json_raises(
        self, registry: NotebookRegistry
    ) -> None:
        """Невалидный JSON → HubRunError."""
        from src.backend.services.jupyter.hub_run_orchestrator import HubRunError

        mock_svc = AsyncMock()
        with pytest.raises(HubRunError, match="not valid JSON"):
            await run_hub_notebook(
                notebook_name="bad",
                notebook_content=b"not a json",
                registry=registry,
                execution_service=mock_svc,
            )

    async def test_path_override_skips_registry(
        self, registry: NotebookRegistry
    ) -> None:
        """notebook_path_override используется без обращения к реестру."""
        mock_svc = AsyncMock()
        mock_svc.execute.return_value = {"outputs": []}

        await run_hub_notebook(
            notebook_name="ignored",  # not in registry
            notebook_path_override="notebooks/custom.ipynb",
            registry=registry,
            execution_service=mock_svc,
        )
        assert (
            mock_svc.execute.await_args.kwargs["notebook_path"]
            == "notebooks/custom.ipynb"
        )

    async def test_inline_takes_priority_over_registry(
        self, registry: NotebookRegistry, tmp_path: Path
    ) -> None:
        """Если передан content — registry НЕ используется."""
        registry.register(
            NotebookSpec(name="registered", path="registered.ipynb")
        )
        mock_svc = AsyncMock()
        mock_svc.execute.return_value = {"outputs": []}

        await run_hub_notebook(
            notebook_name="registered",
            notebook_content=b'{"cells": []}',
            output_path=str(tmp_path / "p.ipynb"),
            registry=registry,
            execution_service=mock_svc,
        )
        assert (
            mock_svc.execute.await_args.kwargs["notebook_path"]
            == str(tmp_path / "p.ipynb")
        )


class TestRunHubNotebookActionService:
    """S170 EXT: _RunHubNotebookService.run() — multi-source notebook."""

    async def test_action_with_base64_content(self) -> None:
        """Action service принимает base64-encoded notebook."""
        import base64

        from src.backend.services.jupyter.hub_actions import _RunHubNotebookService

        notebook_json = b'{"cells": []}'
        b64 = base64.b64encode(notebook_json).decode("ascii")

        svc = _RunHubNotebookService()
        # mock underlying run_hub_notebook
        from src.backend.services.jupyter import hub_actions

        async def _fake(**kwargs):
            from src.backend.services.jupyter.hub_run_orchestrator import HubRunResult
            return HubRunResult(
                notebook_name=kwargs.get("notebook_name", "x"),
                notebook_path=kwargs.get("notebook_path_override", "x.ipynb"),
                parameters=kwargs.get("parameters") or {},
                outputs=[],
                duration_seconds=0.1,
                cells_executed=0,
                errors=[],
            )

        original = hub_actions.run_hub_notebook
        hub_actions.run_hub_notebook = _fake
        try:
            result = await svc.run(
                notebook_content_b64=b64,
                parameters={"x": 1},
            )
        finally:
            hub_actions.run_hub_notebook = original

        assert isinstance(result, dict)
        assert result["notebook_name"] == "inline_notebook"

    async def test_action_with_invalid_base64(self) -> None:
        """Невалидный base64 → HubRunError."""
        from src.backend.services.jupyter.hub_actions import _RunHubNotebookService
        from src.backend.services.jupyter.hub_run_orchestrator import HubRunError

        svc = _RunHubNotebookService()
        with pytest.raises(HubRunError, match="not valid base64"):
            await svc.run(notebook_content_b64="not-valid-base64!!!")

    async def test_action_requires_some_notebook_source(self) -> None:
        """Без любого источника → HubRunError."""
        from src.backend.services.jupyter.hub_actions import _RunHubNotebookService
        from src.backend.services.jupyter.hub_run_orchestrator import HubRunError

        svc = _RunHubNotebookService()
        with pytest.raises(HubRunError, match="required"):
            await svc.run(notebook_name=None, parameters={"x": 1})

    async def test_action_derives_name_from_path(self) -> None:
        """Если path задан без name — name берётся из filename."""
        from src.backend.services.jupyter import hub_actions
        from src.backend.services.jupyter.hub_actions import _RunHubNotebookService
        from src.backend.services.jupyter.hub_run_orchestrator import HubRunResult

        svc = _RunHubNotebookService()

        async def _fake(**kwargs):
            return HubRunResult(
                notebook_name=kwargs["notebook_name"],
                notebook_path=kwargs.get("notebook_path_override", ""),
                parameters=kwargs.get("parameters") or {},
                outputs=[],
                duration_seconds=0.1,
                cells_executed=0,
                errors=[],
            )

        original = hub_actions.run_hub_notebook
        hub_actions.run_hub_notebook = _fake
        try:
            result = await svc.run(
                notebook_path="notebooks/credit_scoring.ipynb"
            )
        finally:
            hub_actions.run_hub_notebook = original

        assert result["notebook_name"] == "credit_scoring"
