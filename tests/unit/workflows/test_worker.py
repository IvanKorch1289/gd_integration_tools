"""Unit tests for src.backend.workflows.worker."""

from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from src.backend.workflows.worker import (
    NoOpStepExecutor,
    _bootstrap,
    _readiness_check,
    _resolve_executor,
    _resolve_listener_dsn,
    _run_worker,
    _shutdown_connectors,
    app,
    build_spec_loader,
    main,
)

runner = CliRunner()


# ── build_spec_loader ──────────────────────────────────────────────────


def test_build_spec_loader_found() -> None:
    with patch("src.backend.infrastructure.workflow.registry.workflow_registry") as reg:
        reg.get_spec.return_value = {"steps": []}
        loader = build_spec_loader()
        assert loader("route_1") == {"steps": []}
        reg.get_spec.assert_called_once_with("route_1")


def test_build_spec_loader_not_found() -> None:
    with patch("src.backend.infrastructure.workflow.registry.workflow_registry") as reg:
        reg.get_spec.return_value = None
        loader = build_spec_loader()
        with pytest.raises(KeyError):
            loader("route_1")


# ── _resolve_executor ──────────────────────────────────────────────────


def test_resolve_executor_dsl_default() -> None:
    with patch.dict(os.environ, {}, clear=True):
        with patch(
            "src.backend.infrastructure.workflow.executor.DSLStepExecutor"
        ) as MockDSL:
            exc = _resolve_executor()
            MockDSL.assert_called_once()
            call_kwargs = MockDSL.call_args.kwargs
            assert "spec_loader" in call_kwargs
            assert callable(call_kwargs["spec_loader"])
            assert exc is MockDSL.return_value


def test_resolve_executor_noop() -> None:
    with patch.dict(os.environ, {"WORKFLOW_WORKER_EXECUTOR": "noop"}):
        exc = _resolve_executor()
        assert isinstance(exc, NoOpStepExecutor)


# ── NoOpStepExecutor ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_noop_executor_returns_done() -> None:
    with (
        patch("src.backend.infrastructure.workflow.runner.StepOutcome") as MockOutcome,
        patch("src.backend.infrastructure.workflow.runner.StepResult") as MockResult,
    ):
        MockOutcome.DONE = "DONE"
        exc = NoOpStepExecutor()
        instance = MagicMock(id="wf-1")
        result = await exc.execute_next(instance=instance, state=None)
        MockResult.assert_called_once_with(outcome="DONE", events=[], output_state=None)
        assert result is MockResult.return_value


# ── _bootstrap / _shutdown_connectors ──────────────────────────────────


@pytest.mark.asyncio
async def test_bootstrap_calls_registrations() -> None:
    with (
        patch(
            "src.backend.plugins.composition.service_setup.register_all_services"
        ) as reg_svc,
        patch("src.backend.dsl.commands.setup.register_action_handlers") as reg_act,
        patch("src.backend.dsl.routes.register_dsl_routes") as reg_routes,
        patch("src.backend.infrastructure.registry.ConnectorRegistry") as Reg,
    ):
        Reg.instance.return_value.start_all = AsyncMock()
        await _bootstrap()
        reg_svc.assert_called_once()
        reg_act.assert_called_once()
        reg_routes.assert_called_once()
        Reg.instance.assert_called_once()
        Reg.instance.return_value.start_all.assert_awaited_once()


@pytest.mark.asyncio
async def test_bootstrap_graceful_on_connector_failure() -> None:
    with (
        patch("src.backend.plugins.composition.service_setup.register_all_services"),
        patch("src.backend.dsl.commands.setup.register_action_handlers"),
        patch("src.backend.dsl.routes.register_dsl_routes"),
        patch("src.backend.infrastructure.registry.ConnectorRegistry") as Reg,
    ):
        Reg.instance.return_value.start_all = AsyncMock(
            side_effect=RuntimeError("boom")
        )
        await _bootstrap()  # should not raise


@pytest.mark.asyncio
async def test_shutdown_connectors() -> None:
    with patch("src.backend.infrastructure.registry.ConnectorRegistry") as Reg:
        Reg.instance.return_value.stop_all = AsyncMock()
        await _shutdown_connectors()
        Reg.instance.return_value.stop_all.assert_awaited_once()


@pytest.mark.asyncio
async def test_shutdown_connectors_graceful_on_failure() -> None:
    with patch("src.backend.infrastructure.registry.ConnectorRegistry") as Reg:
        Reg.instance.return_value.stop_all = AsyncMock(side_effect=RuntimeError("boom"))
        await _shutdown_connectors()  # should not raise


# ── _readiness_check ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_readiness_check_success() -> None:
    with patch(
        "src.backend.infrastructure.database.session_manager.main_session_manager"
    ) as mgr:
        session = AsyncMock()
        mgr.create_session.return_value.__aenter__ = AsyncMock(return_value=session)
        mgr.create_session.return_value.__aexit__ = AsyncMock(return_value=False)
        assert await _readiness_check() is True
        session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_readiness_check_failure() -> None:
    with patch(
        "src.backend.infrastructure.database.session_manager.main_session_manager"
    ) as mgr:
        mgr.create_session.side_effect = Exception("db down")
        assert await _readiness_check() is False


# ── _resolve_listener_dsn ──────────────────────────────────────────────


def test_resolve_listener_dsn_asyncpg() -> None:
    mock_settings = MagicMock()
    mock_settings.database.async_connection_url = (
        "postgresql+asyncpg://user:pass@localhost/db"
    )
    with patch("src.backend.core.config.settings.settings", mock_settings):
        dsn = _resolve_listener_dsn()
        assert dsn == "postgresql://user:pass@localhost/db"


def test_resolve_listener_dsn_psycopg() -> None:
    mock_settings = MagicMock()
    mock_settings.database.async_connection_url = (
        "postgresql+psycopg://user:pass@localhost/db"
    )
    with patch("src.backend.core.config.settings.settings", mock_settings):
        dsn = _resolve_listener_dsn()
        assert dsn == "postgresql://user:pass@localhost/db"


def test_resolve_listener_dsn_plain() -> None:
    mock_settings = MagicMock()
    mock_settings.database.async_connection_url = "postgresql://user:pass@localhost/db"
    with patch("src.backend.core.config.settings.settings", mock_settings):
        dsn = _resolve_listener_dsn()
        assert dsn == "postgresql://user:pass@localhost/db"


def test_resolve_listener_dsn_error() -> None:
    with patch("src.backend.core.config.settings.settings") as mock_settings:
        bad_url = MagicMock()
        bad_url.__str__ = MagicMock(side_effect=Exception("fail"))
        mock_settings.database.async_connection_url = bad_url
        assert _resolve_listener_dsn() is None


# ── _run_worker ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_worker_full_lifecycle() -> None:
    event_mock = MagicMock()
    event_mock.wait = AsyncMock()
    with (
        patch("src.backend.workflows.worker.asyncio.Event", return_value=event_mock),
        patch(
            "src.backend.workflows.worker._bootstrap", new_callable=AsyncMock
        ) as boot,
        patch(
            "src.backend.infrastructure.workflow.runner.DurableWorkflowRunner"
        ) as Runner,
        patch("src.backend.infrastructure.workflow.worker_probes.WorkerProbesServer") as Probes,
        patch(
            "src.backend.workflows.worker._shutdown_connectors", new_callable=AsyncMock
        ) as shut,
        patch("src.backend.workflows.worker._resolve_listener_dsn", return_value=None),
        patch("src.backend.workflows.worker.asyncio.get_running_loop") as mock_get_loop,
    ):
        mock_loop = MagicMock()
        mock_get_loop.return_value = mock_loop
        runner_inst = AsyncMock()
        probes_inst = AsyncMock()
        Runner.return_value = runner_inst
        Probes.return_value = probes_inst

        await _run_worker(
            worker_id="w-1", max_concurrent=4, listen=False, probes_port=9100
        )

        boot.assert_awaited_once()
        Runner.assert_called_once()
        Probes.assert_called_once()
        runner_inst.start.assert_awaited_once()
        probes_inst.start.assert_awaited_once()
        runner_inst.stop.assert_awaited_once()
        probes_inst.stop.assert_awaited_once()
        shut.assert_awaited_once()
        mock_loop.add_signal_handler.assert_called()


@pytest.mark.asyncio
async def test_run_worker_with_listen() -> None:
    event_mock = MagicMock()
    event_mock.wait = AsyncMock()
    with (
        patch("src.backend.workflows.worker.asyncio.Event", return_value=event_mock),
        patch("src.backend.workflows.worker._bootstrap", new_callable=AsyncMock),
        patch(
            "src.backend.infrastructure.workflow.runner.DurableWorkflowRunner"
        ) as Runner,
        patch("src.backend.infrastructure.workflow.worker_probes.WorkerProbesServer") as Probes,
        patch(
            "src.backend.workflows.worker._shutdown_connectors", new_callable=AsyncMock
        ),
        patch(
            "src.backend.workflows.worker._resolve_listener_dsn",
            return_value="postgresql://localhost/db",
        ),
        patch("src.backend.workflows.worker.asyncio.get_running_loop") as mock_get_loop,
    ):
        mock_loop = MagicMock()
        mock_get_loop.return_value = mock_loop
        runner_inst = AsyncMock()
        probes_inst = AsyncMock()
        Runner.return_value = runner_inst
        Probes.return_value = probes_inst

        await _run_worker(
            worker_id="w-2", max_concurrent=2, listen=True, probes_port=9200
        )

        cfg = Runner.call_args.kwargs["config"]
        assert cfg.worker_id == "w-2"
        assert cfg.max_concurrent == 2


@pytest.mark.asyncio
async def test_run_worker_runner_stop_timeout() -> None:
    event_mock = MagicMock()
    event_mock.wait = AsyncMock()
    with (
        patch("src.backend.workflows.worker.asyncio.Event", return_value=event_mock),
        patch("src.backend.workflows.worker._bootstrap", new_callable=AsyncMock),
        patch(
            "src.backend.infrastructure.workflow.runner.DurableWorkflowRunner"
        ) as Runner,
        patch("src.backend.infrastructure.workflow.worker_probes.WorkerProbesServer") as Probes,
        patch(
            "src.backend.workflows.worker._shutdown_connectors", new_callable=AsyncMock
        ),
        patch("src.backend.workflows.worker._resolve_listener_dsn", return_value=None),
        patch.dict(os.environ, {"SHUTDOWN_GRACE_SECONDS": "1"}),
        patch("src.backend.workflows.worker.asyncio.get_running_loop") as mock_get_loop,
    ):
        mock_loop = MagicMock()
        mock_get_loop.return_value = mock_loop
        runner_inst = AsyncMock()
        runner_inst.stop = AsyncMock(side_effect=asyncio.TimeoutError)
        probes_inst = AsyncMock()
        Runner.return_value = runner_inst
        Probes.return_value = probes_inst

        await _run_worker(
            worker_id="w-1", max_concurrent=4, listen=False, probes_port=9100
        )
        runner_inst.stop.assert_awaited_once()
        probes_inst.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_worker_runner_stop_error() -> None:
    event_mock = MagicMock()
    event_mock.wait = AsyncMock()
    with (
        patch("src.backend.workflows.worker.asyncio.Event", return_value=event_mock),
        patch("src.backend.workflows.worker._bootstrap", new_callable=AsyncMock),
        patch(
            "src.backend.infrastructure.workflow.runner.DurableWorkflowRunner"
        ) as Runner,
        patch("src.backend.infrastructure.workflow.worker_probes.WorkerProbesServer") as Probes,
        patch(
            "src.backend.workflows.worker._shutdown_connectors", new_callable=AsyncMock
        ),
        patch("src.backend.workflows.worker._resolve_listener_dsn", return_value=None),
        patch("src.backend.workflows.worker.asyncio.get_running_loop") as mock_get_loop,
    ):
        mock_loop = MagicMock()
        mock_get_loop.return_value = mock_loop
        runner_inst = AsyncMock()
        runner_inst.stop = AsyncMock(side_effect=RuntimeError("boom"))
        probes_inst = AsyncMock()
        Runner.return_value = runner_inst
        Probes.return_value = probes_inst

        await _run_worker(
            worker_id="w-1", max_concurrent=4, listen=False, probes_port=9100
        )
        runner_inst.stop.assert_awaited_once()
        probes_inst.stop.assert_awaited_once()


# ── CLI commands ───────────────────────────────────────────────────────


def test_cli_run() -> None:
    with patch("src.backend.workflows.worker.asyncio.run") as mock_run:
        result = runner.invoke(
            app,
            [
                "run",
                "--max-concurrent",
                "2",
                "--no-listen",
                "--probes-port",
                "9000",
                "--worker-id",
                "test-worker",
            ],
        )
        assert result.exit_code == 0
        mock_run.assert_called_once()


def test_cli_status() -> None:
    with patch("src.backend.workflows.worker.asyncio.run") as mock_run:
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        mock_run.assert_called_once()


def test_cli_drain() -> None:
    result = runner.invoke(app, ["drain"])
    assert result.exit_code == 0
    assert "SIGTERM" in result.output


def test_main() -> None:
    with patch("src.backend.workflows.worker.app") as mock_app:
        main()
        mock_app.assert_called_once()
