"""ADR-0439 — runtime-метрики: пулы соединений и процессы workflow.

Проверяется здесь:

* эндпоинты ``/admin/pools/snapshot``, ``/admin/processes/active``,
  ``/admin/processes/stats`` зарегистрированы;
* эндпоинты читают существующие capability (менеджер пулов, store инстансов);
* портал использует живые пути (а не «endpoint не реализован»).
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def _server_paths() -> list[str]:
    """Пути, зарегистрированные сервером."""
    import sys

    sys.path.insert(0, ".")
    from tests.unit.frontend.api_clients.test_api_contract_paths import (
        _server_paths as paths,
    )

    return sorted(paths())


def test_runtime_metrics_endpoints_registered() -> None:
    """Runtime-эндпоинты зарегистрированы."""
    paths = _server_paths()
    assert "/api/v1/admin/pools/snapshot" in paths
    assert "/api/v1/admin/processes/active" in paths
    assert "/api/v1/admin/processes/stats" in paths


@pytest.mark.asyncio
async def test_pools_snapshot_uses_pool_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Снапшот пулов берётся из unified pool manager."""
    from src.backend.entrypoints.api.v1.endpoints.admin_runtime_metrics import (
        pools_snapshot,
    )

    class _Manager:
        async def get_metrics(self) -> dict[str, dict[str, object]]:
            return {"pg": {"idle": 2, "active": 1, "total": 5}}

    monkeypatch.setattr(
        "src.backend.infrastructure.clients.unified_pool_manager.get_unified_pool_manager",
        lambda: _Manager(),
    )

    metrics = await pools_snapshot()
    assert metrics["pg"]["total"] == 5


@pytest.mark.asyncio
async def test_processes_stats_uses_state_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Счётчики по статусам берутся из workflow state store."""
    from src.backend.entrypoints.api.v1.endpoints.admin_runtime_metrics import (
        processes_stats,
    )

    class _Store:
        async def count_by_status(self) -> dict[str, int]:
            return {"running": 2, "succeeded": 7}

    monkeypatch.setattr(
        "src.backend.core.di.providers.workflow.get_workflow_state_store_provider",
        lambda: _Store(),
    )

    stats = await processes_stats()
    assert stats == {"running": 2, "succeeded": 7}


def test_portal_uses_runtime_paths() -> None:
    """Портал вызывает живые runtime-пути."""
    pools = Path("src/frontend/streamlit_app/pages/55_Монитор_пула.py").read_text(
        encoding="utf-8"
    )
    processes = Path("src/frontend/streamlit_app/pages/56_Процессы.py").read_text(
        encoding="utf-8"
    )
    assert '"/api/v1/admin/pools/snapshot"' in pools
    assert '"/api/v1/admin/processes/active"' in processes
    assert '"/api/v1/admin/processes/stats"' in processes
