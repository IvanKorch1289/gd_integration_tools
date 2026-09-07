"""Тесты NotebookExecutionService.execute_notebook (T3 ratchet: core_mixin 21%→≥90%).

Сервис мокается на границе Hub-клиента: JupyterHubClient заменяется фейком,
IOMixin/JupyterBackendMixin методы — заглушками через patch.object.
Проверяем оркестрацию: spawn → wait → upload → session → per-cell execute
→ ошибочные ветки (нет server URL, нет kernel id).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.backend.services.jupyter.execution_service import NotebookExecutionService
from src.backend.services.jupyter.execution_service.errors import JupyterExecutionError


def _service() -> tuple[NotebookExecutionService, AsyncMock, AsyncMock]:
    settings = SimpleNamespace(timeout_seconds=30.0)
    svc = NotebookExecutionService(settings)  # type: ignore[arg-type]
    hub = AsyncMock()
    svc._hub = hub
    return svc, hub


def _server(url: str = "http://hub:8888", ready: bool = True) -> SimpleNamespace:
    return SimpleNamespace(url=url, ready=ready)


def _session(kernel_id: str | None) -> dict[str, Any]:
    kernel: dict[str, Any] = {}
    if kernel_id is not None:
        kernel["id"] = kernel_id
    return {"kernel": kernel}


def _patch_pipeline(
    svc: NotebookExecutionService,
    server: SimpleNamespace,
    kernel_id: str | None = "kid-1",
    cell_outputs: list[dict[str, object]] | None = None,
) -> tuple[AsyncMock, AsyncMock, AsyncMock]:
    upload = AsyncMock()
    create_session = AsyncMock(return_value=_session(kernel_id))
    execute_cell = AsyncMock(return_value=cell_outputs or [{"output_type": "stream"}])
    wait_for_server = AsyncMock(return_value=server)

    patch.object(svc, "_upload_notebook", upload).start()
    patch.object(svc, "_create_session", create_session).start()
    patch.object(svc, "_execute_cell", execute_cell).start()
    patch.object(svc, "_wait_for_server", wait_for_server).start()
    return upload, create_session, execute_cell


def _cells() -> list[dict[str, object]]:
    return [
        {"cell_type": "code", "source": "print(1)"},
        {"cell_type": "markdown", "source": "# md"},  # пропускается
        {"cell_type": "code", "source": "print(2)"},
    ]


# ── happy path ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_notebook_happy_path() -> None:
    svc, hub = _service()
    hub.get_server = AsyncMock(return_value=_server())
    upload, create_session, execute_cell = _patch_pipeline(svc, _server())

    results = await svc.execute_notebook(
        "alice", "analysis.ipynb", _cells(),  # type: ignore[arg-type]
    )

    assert [r["cell_index"] for r in results] == [0, 2]  # markdown пропущен
    upload.assert_awaited_once()
    create_session.assert_awaited_once()
    assert execute_cell.await_count == 2


@pytest.mark.asyncio
async def test_spawns_server_when_not_ready() -> None:
    """server не ready -> start_server + wait_for_server (spawn-ветка)."""
    svc, hub = _service()
    unready = _server(ready=False)
    hub.get_server = AsyncMock(side_effect=[unready, _server()])
    hub.start_server = AsyncMock()
    upload = AsyncMock()
    create_session = AsyncMock(return_value=_session("kid-9"))
    execute_cell = AsyncMock(return_value=[{"output_type": "stream"}])

    with (
        patch.object(svc, "_upload_notebook", upload),
        patch.object(svc, "_create_session", create_session),
        patch.object(svc, "_execute_cell", execute_cell),
        patch.object(svc, "_wait_for_server", AsyncMock(return_value=_server())),
    ):
        results = await svc.execute_notebook("alice", "a.ipynb", [
            {"cell_type": "code", "source": "1"},
        ])

    assert len(results) == 1
    hub.start_server.assert_awaited_once_with("alice")
    hub.get_server.assert_awaited()


# ── ошибочные ветки ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_server_url_raises() -> None:
    """server.url пуст после spawn -> JupyterExecutionError."""
    svc, hub = _service()
    hub.get_server = AsyncMock(return_value=_server(url="", ready=False))
    hub.start_server = AsyncMock()
    with (
        patch.object(svc, "_wait_for_server", AsyncMock(return_value=_server(url=""))),
        pytest.raises(JupyterExecutionError, match="Server URL unavailable"),
    ):
        await svc.execute_notebook("alice", "a.ipynb", [
            {"cell_type": "code", "source": "1"},
        ])


@pytest.mark.asyncio
async def test_missing_kernel_id_raises() -> None:
    svc, hub = _service()
    hub.get_server = AsyncMock(return_value=_server())
    upload, create_session, execute_cell = _patch_pipeline(svc, _server(), kernel_id=None)

    with pytest.raises(JupyterExecutionError, match="Kernel ID"):
        await svc.execute_notebook("alice", "a.ipynb", [
            {"cell_type": "code", "source": "1"},
        ])
    upload.assert_awaited_once()
    execute_cell.assert_not_awaited()
