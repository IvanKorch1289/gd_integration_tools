"""Тесты непокрытых веток run_hub_notebook (T3 ratchet: 82%→≥90%).

Дополнение к test_hub_run_orchestrator.py: gate OFF, inline-content OFF,
NotebookParameterError, JupyterExecutionError propagation, temp-file cleanup,
_collect_errors, _save_inline_notebook (str/JSON/invalid), _build_execution_service.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.core.config.features import feature_flags
from src.backend.services.jupyter.hub_run_orchestrator import (
    HubRunError,
    JupyterHubNotEnabledError,
    NotebookNotFoundError,
    NotebookParameterError,
    _build_execution_service,
    _collect_errors,
    _save_inline_notebook,
    run_hub_notebook,
)
from src.backend.services.jupyter.notebook_registry import (
    NotebookRegistry,
    NotebookSpec,
)

NAME = "br_alpha"


@pytest.fixture(autouse=True)
def _flags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feature_flags, "jupyter_hub_enabled", True, raising=False)
    from src.backend.core.config.security import secure_settings

    monkeypatch.setattr(
        secure_settings, "jupyter_inline_content_enabled", True, raising=False,
    )


def _exec_ok() -> AsyncMock:
    svc = AsyncMock()
    svc.execute = AsyncMock(
        return_value={
            "outputs": [
                {
                    "cell_index": 0,
                    "outputs": [{"output_type": "stream", "text": "ok"}],
                },
            ],
        },
    )
    return svc


def _registry_with_validation() -> NotebookRegistry:
    reg = NotebookRegistry()
    reg.register(
        NotebookSpec(
            name=NAME,
            path=f"{NAME}.ipynb",
            parameters_schema={"customer_id": {"type": "int"}},
        ),
    )
    return reg


# ── gate ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_gate_off_raises_not_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(feature_flags, "jupyter_hub_enabled", False, raising=False)
    with pytest.raises(JupyterHubNotEnabledError):
        await run_hub_notebook(
            notebook_name=NAME, registry=NotebookRegistry(), execution_service=AsyncMock(),
        )


# ── parameters validation ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_parameter_error_raised() -> None:
    reg = NotebookRegistry()
    reg.register(
        NotebookSpec(
            name=NAME,
            path=f"{NAME}.ipynb",
            parameters_schema={"customer_id": {"type": "int"}},
        ),
    )
    svc = AsyncMock()
    with pytest.raises(NotebookParameterError):
        await run_hub_notebook(
            notebook_name=NAME,
            parameters={"customer_id": "not-int"},
            registry=reg,
            execution_service=svc,
        )


# ── execution error propagation ─────────────────────────────────────


@pytest.mark.asyncio
async def test_execution_error_propagates() -> None:
    from src.backend.services.jupyter.execution_service.errors import (
        JupyterExecutionError,
    )

    reg = NotebookRegistry()
    reg.register(NotebookSpec(name=NAME, path=f"{NAME}.ipynb"))
    svc = AsyncMock()
    svc.execute = AsyncMock(
        side_effect=JupyterExecutionError("papermill exploded"),
    )
    with pytest.raises(JupyterExecutionError):
        await run_hub_notebook(
            notebook_name=NAME,
            registry=reg,
            execution_service=svc,
        )


# ── inline notebook: temp cleanup ───────────────────────────────────


@pytest.mark.asyncio
async def test_inline_content_runs_and_cleans_temp_file() -> None:
    """inline bytes -> temp .ipynb создаётся и удаляется после выполнения."""
    registry = NotebookRegistry()
    registry.register(NotebookSpec(name=NAME, path=f"{NAME}.ipynb"))
    svc = _exec_ok()
    result = await run_hub_notebook(
        notebook_name=NAME,
        parameters={"customer_id": 7},
        registry=registry,
        execution_service=svc,
        notebook_content=b'{"cells": []}',
    )
    assert result.cells_executed == 1
    temp_files = [f for f in os.listdir("/tmp") if f.startswith("hub_inline_")]
    assert temp_files == []


# ── inline-content disabled ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_inline_content_disabled_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.backend.core.config.security import secure_settings

    monkeypatch.setattr(
        secure_settings, "jupyter_inline_content_enabled", False, raising=False,
    )
    registry = NotebookRegistry()
    registry.register(NotebookSpec(name=NAME, path=f"{NAME}.ipynb"))
    with pytest.raises(HubRunError, match="Inline notebook content disabled"):
        await run_hub_notebook(
            notebook_name=NAME,
            notebook_content=b"{}",
            registry=registry,
            execution_service=AsyncMock(),
        )


# ── notebook not found ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_notebook_not_found() -> None:
    registry = NotebookRegistry()
    with pytest.raises(NotebookNotFoundError):
        await run_hub_notebook(
            notebook_name="absent",
            registry=registry,
            execution_service=AsyncMock(),
        )


# ── _collect_errors ─────────────────────────────────────────────────


def test_collect_errors_mixed_outputs() -> None:
    outputs: list[object] = [
        {"cell_index": 0, "outputs": [{"output_type": "stream"}]},
        {
            "cell_index": 1,
            "outputs": [
                {"output_type": "error", "ename": "E", "evalue": "boom"},
                "not-a-dict",
            ],
        },
        "junk",
    ]
    errors = _collect_errors(outputs)  # type: ignore[arg-type]
    assert errors and "cell 1" in errors[0]


# ── _save_inline_notebook ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_save_inline_str_invalid_json_raises() -> None:
    with pytest.raises(HubRunError, match="not valid JSON"):
        await _save_inline_notebook(NAME, "not-json{", output_path=None)


@pytest.mark.asyncio
async def test_save_inline_str_valid_json_uses_output_path(
    tmp_path: pytest.TempPathFactory,
) -> None:
    target = str(tmp_path / "custom.ipynb")
    path = await _save_inline_notebook(NAME, '{"cells": []}', output_path=target)
    assert path == target
    assert os.path.exists(target)


@pytest.mark.asyncio
async def test_save_inline_dict_builds_temp_target(
    tmp_path: pytest.TempPathFactory,
) -> None:
    target_dir = str(tmp_path)
    monkeypatch_env = pytest.MonkeyPatch()
    monkeypatch_env.setenv("JUPYTER_TMPDIR", target_dir)
    path = await _save_inline_notebook(NAME, b'{"cells": []}', output_path=None)
    monkeypatch_env.undo()
    assert "hub_inline_" in os.path.basename(path)
    assert path.endswith(".ipynb")
    assert os.path.exists(path)


# ── _build_execution_service ────────────────────────────────────────


def test_build_execution_service_import_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "src.backend.core.di.providers.jupyter", None)
    with pytest.raises(HubRunError, match="provider not available"):
        _build_execution_service()


def test_build_execution_service_returns_provider_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = object()
    fake_module = MagicMock()
    fake_module.get_notebook_execution_service_provider.return_value = sentinel
    monkeypatch.setitem(
        sys.modules, "src.backend.core.di.providers.jupyter", fake_module,
    )
    assert _build_execution_service() is sentinel


# ── audit emit failure (206-219) + temp cleanup (273-276) ───────────


@pytest.mark.asyncio
async def test_inline_audit_emit_failure_swallowed() -> None:
    """Сбой emit_audit_safe (206-219) не ломает inline-прогон."""
    registry = NotebookRegistry()
    registry.register(NotebookSpec(name=NAME, path=f"{NAME}.ipynb"))
    svc = _exec_ok()
    with patch(
        "src.backend.core.audit.facade.emit_audit_safe",
        side_effect=RuntimeError("audit down"),
    ):
        result = await run_hub_notebook(
            notebook_name=NAME,
            notebook_content=b'{"cells": []}',
            registry=registry,
            execution_service=svc,
        )
    assert result.notebook_name == NAME
    assert svc.execute.await_count == 1


@pytest.mark.asyncio
async def test_inline_temp_cleanup_os_error_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OSError при unlink temp-файла (273-276) -> warning, не crash."""
    import os as _os

    monkeypatch.setattr(_os, "unlink", MagicMock(side_effect=OSError("busy")))
    registry = NotebookRegistry()
    registry.register(NotebookSpec(name=NAME, path=f"{NAME}.ipynb"))
    svc = _exec_ok()
    result = await run_hub_notebook(
        notebook_name=NAME,
        notebook_content=b'{"cells": []}',
        registry=registry,
        execution_service=svc,
    )
    assert result.notebook_name == NAME
