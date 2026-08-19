"""Tests for WorkflowSubprocessProcessor (S171 M8).

Thin wrapper для запуска sub-workflow из текущего workflow.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _bypass_auth() -> None:
    """WorkflowSubprocess/Convert требуют capability — bypass в unit-тестах."""
    from src.backend.dsl.engine.processors.workflow.workflow_convert import (
        WorkflowConvertProcessor,
    )
    from src.backend.dsl.engine.processors.workflow.workflow_subprocess import (
        WorkflowSubprocessProcessor,
    )

    WorkflowSubprocessProcessor.auth_check = AsyncMock(  # type: ignore[method-assign]
        return_value=True,
    )
    WorkflowConvertProcessor.auth_check = AsyncMock(  # type: ignore[method-assign]
        return_value=True,
    )


class TestRunWorkflowByIdStandaloneGuard:
    """Sprint 4 (audit 2026-08-19): standalone guard — production fail-closed."""

    @pytest.mark.asyncio
    async def test_standalone_production_fail_closed(self) -> None:
        """Без parent_handle + require_parent=True (default) → status='failed'."""
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_app = MagicMock()
        mock_app.state.workflow_backend = None
        mock_app.state.profile = None
        # current_workflow_handle=None → triggers standalone path (else branch).
        mock_app.state.current_workflow_handle = None

        backend = MagicMock()
        backend.start_workflow = AsyncMock()
        backend.start_child_workflow = AsyncMock()

        with (
            patch(
                "src.backend.infrastructure.workflow.factory.create_workflow_backend",
                new=AsyncMock(return_value=backend),
            ),
            patch(
                "src.backend.core.di.app_state.get_app_ref",
                return_value=mock_app,
            ),
            patch(
                "src.backend.core.config.features.feature_flags",
                new=MagicMock(workflow_subprocess_require_parent=True),
            ),
        ):
            from src.backend.dsl.engine.processors.workflow.workflow_subprocess import (
                run_workflow_by_id,
            )
            result = await run_workflow_by_id(
                "child_wf", input_data={"x": 1}, timeout=10.0,
            )

        # Standalone заблокирован.
        assert result["status"] == "failed"
        assert "standalone not allowed" in result["error"]
        # Backend НЕ вызван.
        backend.start_workflow.assert_not_called()
        backend.start_child_workflow.assert_not_called()

    @pytest.mark.asyncio
    async def test_standalone_dev_allowed_with_warning(self) -> None:
        """Без parent_handle + require_parent=False → start_workflow + warning."""
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_app = MagicMock()
        mock_app.state.workflow_backend = None
        mock_app.state.profile = None
        # current_workflow_handle=None → triggers standalone path (else branch).
        mock_app.state.current_workflow_handle = None

        fake_handle = MagicMock()
        fake_handle.workflow_id = "child_wf-sub-standalone"
        backend = MagicMock()
        backend.start_workflow = AsyncMock(return_value=fake_handle)

        with (
            patch(
                "src.backend.infrastructure.workflow.factory.create_workflow_backend",
                new=AsyncMock(return_value=backend),
            ),
            patch(
                "src.backend.core.di.app_state.get_app_ref",
                return_value=mock_app,
            ),
            patch(
                "src.backend.core.config.features.feature_flags",
                new=MagicMock(workflow_subprocess_require_parent=False),
            ),
        ):
            from src.backend.dsl.engine.processors.workflow.workflow_subprocess import (
                run_workflow_by_id,
            )
            result = await run_workflow_by_id(
                "child_wf", input_data={"x": 1}, timeout=10.0,
            )

        # Standalone прошёл, backend вызван.
        assert result["status"] == "started"
        backend.start_workflow.assert_called_once()
        backend.start_child_workflow.assert_not_called()


class TestRunWorkflowByIdReal:
    """P1-W2 (audit 2026-08-18): ``run_workflow_by_id`` реально стартует child workflow."""

    @pytest.mark.asyncio
    async def test_calls_backend_start_workflow(self) -> None:
        """С fake backend — получает child_workflow_id и handle_workflow_id."""
        from src.backend.core.workflow.fake_backend import FakeWorkflowBackend

        backend = FakeWorkflowBackend()

        with (
            patch(
                "src.backend.infrastructure.workflow.factory.create_workflow_backend",
                new=AsyncMock(return_value=backend),
            ),
            patch(
                "src.backend.core.config.features.feature_flags",
                new=MagicMock(workflow_subprocess_require_parent=False),
            ),
        ):
            from src.backend.dsl.engine.processors.workflow.workflow_subprocess import (
                run_workflow_by_id,
            )

            result = await run_workflow_by_id(
                "child_wf", input_data={"x": 1}, timeout=30.0,
            )

        # Реальные поля от backend, не stub:
        assert result["status"] == "started"
        assert "child_workflow_id" in result
        assert "handle_workflow_id" in result
        assert result["input"] == {"x": 1}
        assert result["workflow_id"] == "child_wf"
        # resolved_version должен быть not None (WorkflowLauncher нашёл version)
        assert result["resolved_version"] is not None

    @pytest.mark.asyncio
    async def test_returns_failed_on_backend_error(self) -> None:
        """При ошибке backend → status='failed' с error message (не raise)."""
        with (
            patch(
                "src.backend.infrastructure.workflow.factory.create_workflow_backend",
                new=AsyncMock(side_effect=RuntimeError("backend down")),
            ),
            patch(
                "src.backend.core.config.features.feature_flags",
                new=MagicMock(workflow_subprocess_require_parent=False),
            ),
        ):
            from src.backend.dsl.engine.processors.workflow.workflow_subprocess import (
                run_workflow_by_id,
            )

            result = await run_workflow_by_id(
                "child_wf", input_data={"x": 1}, timeout=30.0,
            )

        # Fallback тоже падает (тот же mock) — backend = None,
        # затем backend.start_workflow → AttributeError, возвращаем failed.
        assert result["status"] == "failed"
        assert "error" in result


class TestWorkflowSubprocessProcessor:
    def test_instantiates(self) -> None:
        from src.backend.dsl.engine.processors.workflow.workflow_subprocess import (
            WorkflowSubprocessProcessor,
        )
        p = WorkflowSubprocessProcessor(
            workflow_id="child_wf", input_from="body", to="body.subprocess_result",
        )
        assert p.workflow_id == "child_wf"
        assert p.input_from == "body"

    @pytest.mark.asyncio
    async def test_runs_subworkflow(self) -> None:
        from src.backend.dsl.engine.processors.workflow.workflow_subprocess import (
            WorkflowSubprocessProcessor,
        )
        p = WorkflowSubprocessProcessor(
            workflow_id="child_wf", input_from="body", to="body.subprocess_result",
        )
        ex = MagicMock()
        ex.in_message = MagicMock()
        ex.in_message.body = {"input": "test"}  # real dict  # real dict for set_result
        ex.set_property = MagicMock()
        ex.set_error = MagicMock()
        ex.stop = MagicMock()
        ctx = MagicMock()

        mock_result = {"output": "child completed"}
        with patch(
            "src.backend.dsl.engine.processors.workflow.workflow_subprocess.run_workflow_by_id",
            new=AsyncMock(return_value=mock_result),
        ):
            await p.process(ex, ctx)

        assert ex.in_message.body.get("subprocess_result") == mock_result

    @pytest.mark.asyncio
    async def test_handles_subworkflow_failure(self) -> None:
        """При ошибке sub-workflow — exception пробрасывается."""
        from src.backend.dsl.engine.processors.workflow.workflow_subprocess import (
            WorkflowSubprocessProcessor,
        )
        p = WorkflowSubprocessProcessor(workflow_id="missing_wf")
        ex = MagicMock()
        class _Msg:
            pass
        ex.in_message = _Msg()
        ex.in_message.body = {}
        ex.set_property = MagicMock()
        ex.set_error = MagicMock()
        ex.stop = MagicMock()
        ctx = MagicMock()

        with patch(
            "src.backend.dsl.engine.processors.workflow.workflow_subprocess.run_workflow_by_id",
            new=AsyncMock(side_effect=RuntimeError("workflow not found")),
        ):
            with pytest.raises(RuntimeError, match="workflow not found"):
                await p.process(ex, ctx)


class TestWorkflowConvertProcessor:
    """Конвертация между типами (JSON ↔ YAML ↔ dict ↔ pydantic)."""

    def test_instantiates(self) -> None:
        from src.backend.dsl.engine.processors.workflow.workflow_convert import (
            WorkflowConvertProcessor,
        )
        p = WorkflowConvertProcessor(
            from_format="json", to_format="yaml", source_property="body.a",
        )
        assert p.from_format == "json"
        assert p.to_format == "yaml"

    @pytest.mark.asyncio
    async def test_converts_json_to_yaml(self) -> None:
        from src.backend.dsl.engine.processors.workflow.workflow_convert import (
            WorkflowConvertProcessor,
        )
        p = WorkflowConvertProcessor(
            from_format="json", to_format="yaml", source_property="body",
        )
        ex = MagicMock()
        ex.in_message = MagicMock()
        ex.in_message.body = {"key": "value", "num": 42}
        ex.set_property = MagicMock()
        ex.set_error = MagicMock()
        ex.stop = MagicMock()
        await p.process(ex, MagicMock())
        assert ex.in_message.body.get("converted") is not None
