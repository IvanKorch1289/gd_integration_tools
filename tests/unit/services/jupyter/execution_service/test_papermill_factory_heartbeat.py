"""S74 W4 — tests для PapermillExecutionBackend + ExecutionBackendFactory
+ WebSocket heartbeat (FINAL_REPORT_V2 направление #1 closure)."""
from __future__ import annotations

import asyncio
import os
import tempfile
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import nbformat
import pytest


# Papermill tests
# ============================================================================


@pytest.mark.asyncio
async def test_papermill_execute_with_params_notebook_not_found() -> None:
    """FileNotFoundError если template notebook не существует."""
    from src.backend.services.jupyter.execution_service import (
        PapermillExecutionBackend,
    )

    backend = PapermillExecutionBackend()
    with pytest.raises(FileNotFoundError, match="Template notebook не найден"):
        await backend.execute_with_params(
            notebook_path="/nonexistent/template.ipynb",
            parameters={"date": "2026-06-12"},
        )


@pytest.mark.asyncio
async def test_papermill_execute_with_params_requires_papermill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Если papermill не установлен → JupyterExecutionError с actionable msg."""
    from src.backend.services.jupyter.execution_service import (
        PapermillExecutionBackend,
    )
    from src.backend.services.jupyter.execution_service.errors import (
        JupyterExecutionError,
    )

    backend = PapermillExecutionBackend()

    # Create a temp notebook (text mode для nbformat.write)
    with tempfile.NamedTemporaryFile(
        suffix=".ipynb", delete=False, mode="w", encoding="utf-8"
    ) as f:
        from nbformat import v4 as nb_v4
        nb = nb_v4.new_notebook()
        nbformat.write(nb, f)
        nb_path = f.name

    try:
        # Simulate papermill ImportError — only intercept papermill imports.
        import builtins

        original_import = builtins.__import__

        def mock_import(name, globals=None, locals=None, fromlist=(), level=0):  # type: ignore[no-untyped-def]
            if name == "papermill" or name.startswith("papermill."):
                raise ImportError(f"No module named {name!r}")
            return original_import(name, globals, locals, fromlist, level)

        monkeypatch.setattr(builtins, "__import__", mock_import)

        with pytest.raises(JupyterExecutionError, match="papermill required"):
            await backend.execute_with_params(
                notebook_path=nb_path, parameters={"x": 1}
            )
    finally:
        os.unlink(nb_path)


@pytest.mark.asyncio
async def test_papermill_execute_with_params_happy_path() -> None:
    """Smoke test: papermill.execute_notebook вызывается с правильными args."""
    from src.backend.services.jupyter.execution_service import (
        PapermillExecutionBackend,
    )

    # Create a temp notebook with parameter cell
    with tempfile.NamedTemporaryFile(
        suffix=".ipynb", delete=False, mode="w"
    ) as f:
        from nbformat import v4 as nb_v4
        nb = nb_v4.new_notebook()
        cell = nb_v4.new_code_cell(source="x = 42")
        cell.metadata["tags"] = ["parameters"]
        nb.cells.append(cell)
        nbformat.write(nb, f)
        nb_path = f.name

    try:
        # Mock papermill.execute_notebook через sys.modules (cleaner
        # than monkeypatching builtins).
        import sys

        # Save originals
        original_pm = sys.modules.get("papermill")
        original_pm_exc = sys.modules.get("papermill.exceptions")

        # Create mock module
        mock_pm = MagicMock()
        mock_pm.execute_notebook = MagicMock(
            side_effect=lambda **kwargs: _create_dummy_output(
                kwargs.get("output_path", "/tmp/out.ipynb")
            )
        )
        # Mock exceptions submodule
        mock_exc_module = MagicMock()
        class _MockPMError(Exception):
            pass
        mock_exc_module.PapermillExecutionError = _MockPMError

        sys.modules["papermill"] = mock_pm
        sys.modules["papermill.exceptions"] = mock_exc_module

        try:
            backend = PapermillExecutionBackend(kernel_name="python3")
            result = await backend.execute_with_params(
                notebook_path=nb_path, parameters={"x": 42}
            )
            assert result["parameters_injected"] == 1
            assert result["cells_executed"] >= 0
            assert result["duration_seconds"] >= 0
            assert isinstance(result["output_path"], str)
        finally:
            # Restore originals
            if original_pm is not None:
                sys.modules["papermill"] = original_pm
            else:
                sys.modules.pop("papermill", None)
            if original_pm_exc is not None:
                sys.modules["papermill.exceptions"] = original_pm_exc
            else:
                sys.modules.pop("papermill.exceptions", None)
    finally:
        os.unlink(nb_path)


def _create_dummy_output(output_path: str) -> None:
    """Helper: write a dummy executed notebook для papermill mock."""
    from nbformat import v4 as nb_v4
    nb = nb_v4.new_notebook()
    cell = nb_v4.new_code_cell(source="x = 42")
    cell.execution_count = 1
    cell.outputs = []
    nb.cells.append(cell)
    nbformat.write(nb, output_path)


# Factory tests
# ============================================================================


def test_factory_create_papermill() -> None:
    """Factory создаёт PapermillExecutionBackend для kind='papermill'."""
    from src.backend.services.jupyter.execution_service import (
        BackendKind,
        ExecutionBackendFactory,
        PapermillExecutionBackend,
    )

    factory = ExecutionBackendFactory()
    backend = factory.create("papermill", kernel_name="python3")
    assert isinstance(backend, PapermillExecutionBackend)
    # BackendKind enum
    backend2 = factory.create(BackendKind.PAPERMILL)
    assert isinstance(backend2, PapermillExecutionBackend)


def test_factory_create_nbclient() -> None:
    """Factory создаёт NbClientExecutionBackend для kind='nbclient'."""
    from src.backend.services.jupyter.execution_service import (
        ExecutionBackendFactory,
        NbClientExecutionBackend,
    )

    factory = ExecutionBackendFactory()
    backend = factory.create("nbclient", kernel_name="python3")
    assert isinstance(backend, NbClientExecutionBackend)


def test_factory_create_hub_requires_settings() -> None:
    """Factory.create('hub', без settings) → ValueError."""
    from src.backend.services.jupyter.execution_service import (
        ExecutionBackendFactory,
    )

    factory = ExecutionBackendFactory()
    with pytest.raises(ValueError, match="HUB backend требует JupyterHubSettings"):
        factory.create("hub")


def test_factory_create_hub_with_settings() -> None:
    """Factory.create('hub', settings=...) → NotebookExecutionService."""
    from src.backend.core.config.services.jupyter_hub import JupyterHubSettings
    from src.backend.services.jupyter.execution_service import (
        ExecutionBackendFactory,
        NotebookExecutionService,
    )

    factory = ExecutionBackendFactory()
    settings = JupyterHubSettings(
        base_url="https://hub.example.com",
        api_token="test-token",
        default_kernel="python3",
    )
    backend = factory.create("hub", settings=settings)
    assert isinstance(backend, NotebookExecutionService)


def test_factory_create_e2b_not_implemented() -> None:
    """Factory.create('e2b') → E2BExecutionBackend instance (S75 W1+).

    S74 W2 был NotImplementedError stub; S75 W1 имплементировал
    E2BExecutionBackend. Test обновлён под S75 W1 (S150 W2).
    """
    from src.backend.services.jupyter.execution_service import (
        E2BExecutionBackend,
        ExecutionBackendFactory,
    )

    factory = ExecutionBackendFactory()
    backend = factory.create("e2b")
    assert isinstance(backend, E2BExecutionBackend)


def test_factory_create_unknown_kind() -> None:
    """Factory.create('unknown') → ValueError (BackendKind enum)."""
    from src.backend.services.jupyter.execution_service import (
        ExecutionBackendFactory,
    )

    factory = ExecutionBackendFactory()
    with pytest.raises(ValueError, match="not a valid BackendKind"):
        factory.create("unknown")


def test_factory_override_for_test_injection() -> None:
    """Factory.create(kind, override=mock) возвращает mock без construction."""
    from src.backend.services.jupyter.execution_service import (
        ExecutionBackendFactory,
    )

    factory = ExecutionBackendFactory()
    mock_backend = MagicMock()
    result = factory.create("hub", settings=None, override=mock_backend)
    assert result is mock_backend


def test_factory_from_config_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Factory.from_config() reads JUPYTER_BACKEND env."""
    from src.backend.services.jupyter.execution_service import (
        ExecutionBackendFactory,
        NbClientExecutionBackend,
    )

    monkeypatch.setenv("JUPYTER_BACKEND", "nbclient")
    factory = ExecutionBackendFactory()
    backend = factory.from_config()
    assert isinstance(backend, NbClientExecutionBackend)


def test_factory_default_is_hub(monkeypatch: pytest.MonkeyPatch) -> None:
    """Factory.from_config() default = 'hub' (для production)."""
    from src.backend.services.jupyter.execution_service import (
        ExecutionBackendFactory,
        NotebookExecutionService,
    )
    from src.backend.core.config.services.jupyter_hub import JupyterHubSettings

    monkeypatch.delenv("JUPYTER_BACKEND", raising=False)
    factory = ExecutionBackendFactory()
    settings = JupyterHubSettings(
        base_url="https://hub.example.com",
        api_token="test",
        default_kernel="python3",
    )
    backend = factory.from_config(settings=settings)
    assert isinstance(backend, NotebookExecutionService)


# Heartbeat tests (logic-level, mock websockets)
# ============================================================================


@pytest.mark.asyncio
async def test_heartbeat_loop_detects_dead_connection() -> None:
    """Heartbeat loop устанавливает connection_dead если pong timeout."""
    # Mock websockets module
    mock_ws = AsyncMock()
    mock_ws.ping = AsyncMock(side_effect=asyncio.TimeoutError)

    connection_dead = asyncio.Event()
    last_pong_time = asyncio.get_event_loop().time() - 100  # long time ago

    # Inline _heartbeat_loop logic test (mimics jupyter_mixin implementation)
    HEARTBEAT_INTERVAL_S = 0.05  # Fast для test
    HEARTBEAT_TIMEOUT_S = 0.1

    async def _heartbeat_loop() -> None:
        nonlocal last_pong_time
        while not connection_dead.is_set():
            await asyncio.sleep(HEARTBEAT_INTERVAL_S)
            if connection_dead.is_set():
                break
            now = asyncio.get_event_loop().time()
            if now - last_pong_time >= HEARTBEAT_INTERVAL_S:
                try:
                    await asyncio.wait_for(
                        mock_ws.ping(), timeout=HEARTBEAT_TIMEOUT_S
                    )
                    last_pong_time = now
                except asyncio.TimeoutError:
                    connection_dead.set()
                    break

    # Run heartbeat для 1 cycle (should detect timeout)
    task = asyncio.create_task(_heartbeat_loop())
    await asyncio.sleep(0.2)  # дать loop несколько iterations
    assert connection_dead.is_set(), "Heartbeat должен detect'нуть timeout"
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
