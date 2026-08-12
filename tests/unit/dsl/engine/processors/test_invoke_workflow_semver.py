"""D-AUDIT-8501: regression-тесты для SemVer silent fallback (DOMAIN-WF-P1-001).

Бывший баг: ``_resolve_workflow_version()`` глотала WorkflowResolutionError
и возвращала ``self.workflow_name`` без логирования — audit-trail терял
сигнал о SemVer mismatch (workflow запускался с default version, не с
запрошенной).

Фикс (cycle 85): при except логируется WARNING с workflow_name, spec и exc.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from src.backend.dsl.engine.processors.invoke_workflow import InvokeWorkflowProcessor


def _make_processor(**overrides: Any) -> InvokeWorkflowProcessor:
    """Создать InvokeWorkflowProcessor для теста без protocol-маппинга."""
    defaults: dict[str, Any] = {
        "name": "orders.charge",
        "version": ">=2.0,<3.0",
    }
    defaults.update(overrides)
    return InvokeWorkflowProcessor(**defaults)


@pytest.mark.asyncio
async def test_resolve_version_logs_warning_on_mismatch(caplog: pytest.LogCaptureFixture) -> None:
    """SemVer resolution failure → WARNING с workflow_name, spec и exc."""
    proc = _make_processor(version=">=99.0,<100.0")

    # Мокаем WorkflowLauncher.resolve чтобы бросить WorkflowResolutionError.
    fake_exc = Exception("Installed version '1.0' does not match '>=99.0,<100.0'")
    with patch(
        "src.backend.dsl.workflow.launcher.WorkflowLauncher.resolve",
        side_effect=__import__(
            "src.backend.dsl.workflow.launcher", fromlist=["WorkflowResolutionError"],
        ).WorkflowResolutionError(str(fake_exc)),
    ):
        with caplog.at_level("WARNING", logger="src.backend.dsl.engine.processors.invoke_workflow"):
            result = await proc._resolve_workflow_version()

    # Fallback остался backward-compat (return original workflow_name).
    assert result == "orders.charge"
    # И warning был залогирован.
    assert any(
        "SemVer resolution failed" in record.message
        and "orders.charge" in record.message
        and ">=99.0,<100.0" in record.message
        for record in caplog.records
    ), f"Expected WARNING, got: {[r.message for r in caplog.records]}"


@pytest.mark.asyncio
async def test_resolve_version_no_version_returns_name() -> None:
    """Без version — короткий circuit без обращения к WorkflowLauncher."""
    proc = _make_processor(version=None)
    result = await proc._resolve_workflow_version()
    assert result == "orders.charge"
