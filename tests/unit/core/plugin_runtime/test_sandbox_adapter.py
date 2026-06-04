# ruff: noqa: S101
"""Sprint 14 W2 — unit-тесты ``PluginSandboxAdapter`` (resource-limits смысл)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from src.backend.core.ai.sandbox import SandboxResult
from src.backend.core.plugin_runtime.sandbox import (
    PluginSandboxAdapter,
    PluginSandboxError,
)
from src.backend.core.security.capabilities import CapabilityRef
from src.backend.services.plugins.manifest_v11 import PluginManifestV11, PluginSandbox


class _StubSandbox:
    async def run(
        self,
        code: str,  # noqa: ARG002
        *,
        timeout_s: float = 30.0,  # noqa: ARG002
        files: Mapping[str, bytes] | None = None,  # noqa: ARG002
        workspace: Any | None = None,  # noqa: ARG002
    ) -> SandboxResult:
        return SandboxResult(stdout="", stderr="", exit_code=0)


def _manifest(sandbox: PluginSandbox | None) -> PluginManifestV11:
    return PluginManifestV11(
        name="demo",
        version="1.0.0",
        requires_core=">=0.2,<1.0",
        entry_class="extensions.demo.plugin.Demo",
        capabilities=(CapabilityRef(name="code.execute"),),
        sandbox=sandbox,
    )


class TestModeValidation:
    """`mode != 'e2b'` обрабатывается через PluginSandboxError."""

    @pytest.mark.asyncio
    async def test_only_e2b_mode_accepted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manifest = _manifest(PluginSandbox(enabled=True))
        adapter = PluginSandboxAdapter(sandbox=_StubSandbox(), manifest=manifest)
        # подменяем mode в обход pydantic (frozen) для теста ветви адаптера
        object.__setattr__(manifest.sandbox, "mode", "wasm")
        with pytest.raises(PluginSandboxError, match="unsupported sandbox mode"):
            await adapter.run("pass")


class TestIsEnabledFlag:
    def test_disabled_when_none(self) -> None:
        adapter = PluginSandboxAdapter(sandbox=_StubSandbox(), manifest=_manifest(None))
        assert adapter.is_enabled is False

    def test_enabled_only_when_true(self) -> None:
        adapter = PluginSandboxAdapter(
            sandbox=_StubSandbox(), manifest=_manifest(PluginSandbox(enabled=True))
        )
        assert adapter.is_enabled is True

    def test_declared_but_disabled(self) -> None:
        adapter = PluginSandboxAdapter(
            sandbox=_StubSandbox(), manifest=_manifest(PluginSandbox(enabled=False))
        )
        assert adapter.is_enabled is False
