# ruff: noqa: S101
"""Sprint 14 W2 — unit-тесты декларативного ``PluginSandbox`` профиля.

Покрывает Pydantic-валидацию полей и интеграцию через
:class:`PluginSandboxAdapter`. e2b backend замокан — реальный e2b
запускать не будем (feature_flag plugin_sandbox_strict OFF до приёмки).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from src.backend.core.ai.sandbox import CodeSandbox, SandboxResult
from src.backend.core.plugin_runtime.sandbox import (
    PluginSandboxAdapter,
    PluginSandboxError,
)
from src.backend.core.security.capabilities import CapabilityRef
from src.backend.services.plugins.manifest_v11 import PluginManifestV11, PluginSandbox


class FakeSandbox:
    """Минимальный CodeSandbox для unit-тестов (не делает реальных вызовов)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, float]] = []

    async def run(
        self,
        code: str,
        *,
        timeout_s: float = 30.0,
        files: Mapping[str, bytes] | None = None,
        workspace: Any | None = None,
    ) -> SandboxResult:
        self.calls.append((code, timeout_s))
        return SandboxResult(stdout="ok", stderr="", exit_code=0)


def _make_manifest(
    *,
    sandbox: PluginSandbox | None = None,
    capabilities: tuple[CapabilityRef, ...] = (),
) -> PluginManifestV11:
    return PluginManifestV11(
        name="demo",
        version="1.0.0",
        requires_core=">=0.2,<1.0",
        entry_class="extensions.demo.plugin.Demo",
        capabilities=capabilities,
        sandbox=sandbox,
    )


class TestSandboxModel:
    """Валидация ``[sandbox]`` секции в plugin.toml."""

    def test_defaults(self) -> None:
        s = PluginSandbox()
        assert s.enabled is False
        assert s.mode == "e2b"
        assert s.max_memory_mb == 512
        assert s.max_cpu_seconds == 30

    def test_explicit_fields(self) -> None:
        s = PluginSandbox(
            enabled=True,
            mode="e2b",
            max_memory_mb=1024,
            max_cpu_seconds=60,
            allow_imports=("requests",),
        )
        assert s.allow_imports == ("requests",)
        assert s.max_memory_mb == 1024

    @pytest.mark.parametrize(
        "field,value",
        [
            ("max_memory_mb", 4),  # ниже минимума 16
            ("max_memory_mb", 99999),  # выше максимума 8192
            ("max_cpu_seconds", 0),
            ("max_cpu_seconds", 999_999),
        ],
    )
    def test_invalid_ranges_rejected(self, field: str, value: int) -> None:
        with pytest.raises(ValueError):
            PluginSandbox(**{field: value})


class TestSandboxAdapter:
    """`PluginSandboxAdapter` делегирует в базовый CodeSandbox."""

    @pytest.mark.asyncio
    async def test_disabled_raises(self) -> None:
        manifest = _make_manifest(sandbox=None)
        adapter = PluginSandboxAdapter(sandbox=FakeSandbox(), manifest=manifest)
        assert adapter.is_enabled is False
        with pytest.raises(PluginSandboxError, match="not declared"):
            await adapter.run("print('x')")

    @pytest.mark.asyncio
    async def test_missing_code_execute_capability(self) -> None:
        manifest = _make_manifest(sandbox=PluginSandbox(enabled=True), capabilities=())
        adapter = PluginSandboxAdapter(sandbox=FakeSandbox(), manifest=manifest)
        with pytest.raises(PluginSandboxError, match="code.execute"):
            await adapter.run("print('x')")

    @pytest.mark.asyncio
    async def test_run_delegates_to_sandbox(self) -> None:
        manifest = _make_manifest(
            sandbox=PluginSandbox(enabled=True, max_cpu_seconds=15),
            capabilities=(CapabilityRef(name="code.execute"),),
        )
        fake = FakeSandbox()
        adapter = PluginSandboxAdapter(sandbox=fake, manifest=manifest)
        result = await adapter.run("print('hello')")
        assert result.stdout == "ok"
        assert fake.calls == [("print('hello')", 15.0)]

    @pytest.mark.asyncio
    async def test_capability_check_invoked(self) -> None:
        observed: list[tuple[str, str, str | None]] = []

        def fake_check(plugin: str, capability: str, scope: str | None) -> None:
            observed.append((plugin, capability, scope))

        manifest = _make_manifest(
            sandbox=PluginSandbox(enabled=True),
            capabilities=(CapabilityRef(name="code.execute"),),
        )
        adapter = PluginSandboxAdapter(
            sandbox=FakeSandbox(), manifest=manifest, capability_check=fake_check
        )
        await adapter.run("print('x')")
        assert observed == [("demo", "code.execute", None)]
