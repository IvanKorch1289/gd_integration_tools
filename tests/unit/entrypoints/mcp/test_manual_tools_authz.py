"""Unit tests for MCP manual tools authz wrapper (Block 1.4-extension).

Покрывает:
1. ``_check_mcp_manual_tool_authz`` — passthrough/allow/deny по конфигу.
2. ``_authz_manual_tool`` — единый wrapper выше уровня tool function:
   allow-path (делегирование исходному handler'у) и deny-path (error-envelope
   без вызова исходного handler'а).
3. Smoke-тесты: каждый файл ``tools_*.py`` / ``workflow_tools.py`` импортится
   и не падает при наличии нового helper'а.

Cycle 22 (Sprint 36 audit): per-tool authz для action tools уже есть через
``_check_mcp_tool_authz`` inline в helpers.py / namespaces/*.py. Эти тесты
закрывают gap — manual tools (``route_*``, ``pipeline_*``, ``documents_*``,
``workflow_*``, ``convert_*``, ``system_*``, ``template_*``, ``macro_*``)
теперь оборачиваются единым ``_authz_manual_tool`` поверх ``@mcp.tool(...)``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


# ── _check_mcp_manual_tool_authz ──────────────────────────────────────


def test_manual_authz_disabled_allows_all() -> None:
    """tool_authz_enabled=False → passthrough (None)."""
    from src.backend.entrypoints.mcp.mcp_server.helpers import (
        _check_mcp_manual_tool_authz,
    )

    fake = MagicMock()
    fake.tool_authz_enabled = False
    fake.tool_manual_allowlist = []  # type: ignore[assignment]
    with patch("src.backend.core.config.ai_stack.mcp_settings", fake, create=True):
        assert _check_mcp_manual_tool_authz("route_execute") is None
        assert _check_mcp_manual_tool_authz("documents_to_markdown") is None


def test_manual_authz_empty_allowlist_passthrough() -> None:
    """tool_authz_enabled=True + пустой allowlist → passthrough (backward-compat)."""
    from src.backend.entrypoints.mcp.mcp_server.helpers import (
        _check_mcp_manual_tool_authz,
    )

    fake = MagicMock()
    fake.tool_authz_enabled = True
    fake.tool_manual_allowlist = []
    with patch("src.backend.core.config.ai_stack.mcp_settings", fake, create=True):
        assert _check_mcp_manual_tool_authz("route_execute") is None
        assert _check_mcp_manual_tool_authz("pipeline_from_yaml") is None
        assert _check_mcp_manual_tool_authz("any_tool") is None


def test_manual_authz_in_allowlist_allows() -> None:
    """tool_name в tool_manual_allowlist → allow."""
    from src.backend.entrypoints.mcp.mcp_server.helpers import (
        _check_mcp_manual_tool_authz,
    )

    fake = MagicMock()
    fake.tool_authz_enabled = True
    fake.tool_manual_allowlist = ["route_list", "documents_to_markdown"]
    with patch("src.backend.core.config.ai_stack.mcp_settings", fake, create=True):
        assert _check_mcp_manual_tool_authz("route_list") is None
        assert _check_mcp_manual_tool_authz("documents_to_markdown") is None


def test_manual_authz_not_in_allowlist_denies() -> None:
    """tool_name не в tool_manual_allowlist → deny."""
    from src.backend.entrypoints.mcp.mcp_server.helpers import (
        _check_mcp_manual_tool_authz,
    )

    fake = MagicMock()
    fake.tool_authz_enabled = True
    fake.tool_manual_allowlist = ["route_list"]
    with patch("src.backend.core.config.ai_stack.mcp_settings", fake, create=True):
        assert _check_mcp_manual_tool_authz("route_execute") == "not_in_manual_allowlist"
        assert (
            _check_mcp_manual_tool_authz("pipeline_from_yaml")
            == "not_in_manual_allowlist"
        )


def test_manual_authz_settings_import_error_fails_closed() -> None:
    """Settings import error → fail-CLOSED (deny)."""
    import importlib
    import sys

    ai_stack_path = "src.backend.core.config.ai_stack"
    saved = sys.modules.pop(ai_stack_path, None)
    sys.modules[ai_stack_path] = None  # type: ignore[assignment]

    try:
        # Drop cached helpers so the inner import re-resolves.
        helpers_path = "src.backend.entrypoints.mcp.mcp_server.helpers"
        helpers_mod = importlib.import_module(helpers_path)
        # Drop the module's __dict__ entry for mcp_settings to force re-import
        # attempt (in case it was already bound by a prior test).
        reason = helpers_mod._check_mcp_manual_tool_authz("route_execute")
    finally:
        if saved is not None:
            sys.modules[ai_stack_path] = saved
        else:
            sys.modules.pop(ai_stack_path, None)

    assert reason is not None
    assert "mcp_settings unavailable" in reason


# ── _manual_tool_deny_envelope ────────────────────────────────────────


def test_deny_envelope_shape() -> None:
    """Envelope содержит error/tool/reason."""
    from src.backend.entrypoints.mcp.mcp_server.helpers import (
        _manual_tool_deny_envelope,
    )

    raw = _manual_tool_deny_envelope("route_execute", "not_in_manual_allowlist")
    import orjson

    parsed = orjson.loads(raw)
    assert parsed["error"] == "mcp.tool.denied"
    assert parsed["tool"] == "route_execute"
    assert parsed["reason"] == "not_in_manual_allowlist"


# ── _authz_manual_tool decorator ──────────────────────────────────────


class _RecordingMcp:
    """Минимальный mock FastMCP, фиксирующий зарегистрированные tools."""

    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(
        self, *, name: str, description: str
    ) -> Any:
        def decorator(fn: Any) -> Any:
            self.tools[name] = fn
            return fn

        return decorator


@pytest.mark.asyncio
async def test_authz_decorator_allows_when_in_allowlist() -> None:
    """Allow-path: wrapper делегирует исходному handler'у."""
    from src.backend.entrypoints.mcp.mcp_server.helpers import _authz_manual_tool

    mcp = _RecordingMcp()
    called = {"hit": False}

    @_authz_manual_tool(mcp, name="route_list", description="test")
    async def handler() -> str:
        called["hit"] = True
        return "ok"

    fake = MagicMock()
    fake.tool_authz_enabled = True
    fake.tool_manual_allowlist = ["route_list"]
    with patch("src.backend.core.config.ai_stack.mcp_settings", fake, create=True):
        result = await handler()

    assert result == "ok"
    assert called["hit"] is True


@pytest.mark.asyncio
async def test_authz_decorator_denies_with_envelope() -> None:
    """Deny-path: исходный handler НЕ вызывается, возвращается envelope."""
    from src.backend.entrypoints.mcp.mcp_server.helpers import _authz_manual_tool

    mcp = _RecordingMcp()
    called = {"hit": False}

    @_authz_manual_tool(mcp, name="route_execute", description="test")
    async def handler(route_id: str) -> str:
        called["hit"] = True
        return f"executed {route_id}"

    fake = MagicMock()
    fake.tool_authz_enabled = True
    fake.tool_manual_allowlist = ["route_list"]
    with patch("src.backend.core.config.ai_stack.mcp_settings", fake, create=True):
        result = await handler(route_id="orders")

    import orjson

    parsed = orjson.loads(result)
    assert parsed["error"] == "mcp.tool.denied"
    assert parsed["tool"] == "route_execute"
    assert parsed["reason"] == "not_in_manual_allowlist"
    assert called["hit"] is False


@pytest.mark.asyncio
async def test_authz_decorator_passthrough_when_disabled() -> None:
    """tool_authz_enabled=False → wrapper не вмешивается."""
    from src.backend.entrypoints.mcp.mcp_server.helpers import _authz_manual_tool

    mcp = _RecordingMcp()
    called = {"hit": False}

    @_authz_manual_tool(mcp, name="route_execute", description="test")
    async def handler(route_id: str) -> str:
        called["hit"] = True
        return f"executed {route_id}"

    fake = MagicMock()
    fake.tool_authz_enabled = False
    fake.tool_manual_allowlist = []
    with patch("src.backend.core.config.ai_stack.mcp_settings", fake, create=True):
        result = await handler(route_id="orders")

    assert result == "executed orders"
    assert called["hit"] is True


@pytest.mark.asyncio
async def test_authz_decorator_preserves_signature_via_functools_wraps() -> None:
    """functools.wraps сохраняет имя/сигнатуру/docstring — критично для FastMCP introspection."""
    from src.backend.entrypoints.mcp.mcp_server.helpers import _authz_manual_tool

    mcp = _RecordingMcp()

    @_authz_manual_tool(mcp, name="documents_to_markdown", description="x")
    async def documents_to_markdown(path: str, mime: str | None = None) -> str:
        """Convert file."""
        return "ok"

    assert documents_to_markdown.__name__ == "documents_to_markdown"
    assert "Convert file." in (documents_to_markdown.__doc__ or "")
    import inspect

    sig = inspect.signature(documents_to_markdown)
    params = list(sig.parameters.keys())
    assert params == ["path", "mime"]


# ── Smoke: каждый tools-файл импортится и применяет _authz_manual_tool ──


@pytest.mark.parametrize(
    "module_name",
    [
        "src.backend.entrypoints.mcp.mcp_server.tools_route",
        "src.backend.entrypoints.mcp.mcp_server.tools_yaml",
        "src.backend.entrypoints.mcp.mcp_server.tools_document",
        "src.backend.entrypoints.mcp.mcp_server.tools_convert",
        "src.backend.entrypoints.mcp.mcp_server.tools_system",
        "src.backend.entrypoints.mcp.mcp_server.tools_template",
    ],
)
def test_manual_tools_files_import_and_register(module_name: str) -> None:
    """Smoke: каждый tools-файл импортится; _register_* функции существуют."""
    import importlib

    module = importlib.import_module(module_name)
    # Каждый файл экспортирует ровно одну _register_* функцию.
    register_fns = [
        name
        for name in dir(module)
        if name.startswith("_register_") and name.endswith("_tools")
    ]
    assert len(register_fns) == 1, (
        f"{module_name}: expected exactly one _register_*_tools, got {register_fns}"
    )
    assert callable(getattr(module, register_fns[0]))


def test_workflow_tools_uses_authz_wrapper() -> None:
    """workflow_tools._build_workflow_tool использует _authz_manual_tool."""
    import inspect

    from src.backend.entrypoints.mcp import workflow_tools

    src = inspect.getsource(workflow_tools._build_workflow_tool)
    assert "_authz_manual_tool" in src, (
        "workflow_tools._build_workflow_tool должна оборачивать tool "
        "через _authz_manual_tool (Block 1.4-extension)."
    )


def test_workflow_catalog_uses_authz_wrapper() -> None:
    """workflow_tools._register_catalog_tools использует _authz_manual_tool для workflow_list/workflow_status."""
    import inspect

    from src.backend.entrypoints.mcp import workflow_tools

    src = inspect.getsource(workflow_tools._register_catalog_tools)
    assert "_authz_manual_tool" in src


def test_mcp_server_exports_authz_helpers() -> None:
    """mcp_server/__init__.py экспортирует новые helpers в __all__."""
    from src.backend.entrypoints.mcp import mcp_server

    assert "_check_mcp_manual_tool_authz" in mcp_server.__all__
    assert "_authz_manual_tool" in mcp_server.__all__
    assert "_manual_tool_deny_envelope" in mcp_server.__all__
