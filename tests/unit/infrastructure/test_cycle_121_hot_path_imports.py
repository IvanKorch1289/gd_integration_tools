"""Sprint 19 iteration 13: hot-path import smoke test.

After cycle 121 cleanup (commit 7ab73047), 35 files were bulk-merged with
git conflict resolution. This test verifies the **9 critical runtime
hot-path modules** still import cleanly post-cleanup.

Why these 9:
* clickhouse, metrics, tracing — observability core (startup hot-path)
* otel_middleware, webhook_signature — request middleware (per-request)
* soap_handler, ws_handler — protocol endpoints (per-request)
* clickhouse_audit_service — audit pipeline (background)
* gateway_adapter — AI composition root (per-request)

If any of these fail to import, the app is broken at startup or
at every request. This test catches the regression class.
"""
from __future__ import annotations

import pytest

HOT_PATH_MODULES = [
    # Observability core
    "src.backend.infrastructure.clients.storage.clickhouse",
    "src.backend.infrastructure.observability.metrics",
    "src.backend.infrastructure.observability.tracing",
    # Request middleware
    "src.backend.entrypoints.middlewares.otel_middleware",
    "src.backend.entrypoints.middlewares.webhook_signature",
    # Protocol endpoints
    "src.backend.entrypoints.soap.soap_handler",
    "src.backend.entrypoints.websocket.ws_handler",
    # Audit pipeline + AI composition
    "src.backend.services.audit.clickhouse_audit_service.service",
    "src.backend.services.ai.gateway_adapter",
]


@pytest.mark.unit
@pytest.mark.parametrize("module_name", HOT_PATH_MODULES)
def test_hot_path_module_imports(module_name: str) -> None:
    """Each hot-path module must import без ImportError / SyntaxError.

    Sprint 19 cycle 121 cleanup verified all 9 modules are
    importable. This test prevents future regressions.
    """
    __import__(module_name)


@pytest.mark.unit
def test_all_hot_paths_loadable() -> None:
    """All 9 hot-path modules loadable в одном процессе (no module-level
    side effects that would prevent other imports).
    """
    import importlib

    failed = []
    for module_name in HOT_PATH_MODULES:
        try:
            importlib.import_module(module_name)
        except Exception as e:
            failed.append((module_name, str(e)))
    assert not failed, f"Failed imports: {failed}"
