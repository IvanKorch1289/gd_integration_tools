# ruff: noqa: S101
"""Wave 1.7: CodeSandbox + NoOp + E2B мок."""

from __future__ import annotations

import pytest

from src.backend.core.ai.sandbox import NoOpSandbox


@pytest.mark.asyncio
async def test_noop_sandbox_refuses_to_run() -> None:
    sandbox = NoOpSandbox()
    with pytest.raises(RuntimeError, match="не сконфигурирован"):
        await sandbox.run("print('hi')")


@pytest.mark.asyncio
async def test_e2b_sandbox_capability_check_called() -> None:
    """Capability ``code.execute`` проверяется до загрузки SDK."""
    from src.backend.infrastructure.ai.e2b_sandbox import E2BSandbox

    seen: list[tuple[str, str, str | None]] = []

    def fake_check(plugin: str, capability: str, scope: str | None) -> None:
        seen.append((plugin, capability, scope))
        raise RuntimeError("denied")

    sandbox = E2BSandbox(api_key="x", capability_check=fake_check)
    with pytest.raises(RuntimeError, match="denied"):
        await sandbox.run("print(1)")
    assert seen == [("ai-agent", "code.execute", None)]


@pytest.mark.asyncio
async def test_e2b_sandbox_raises_without_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    """Без e2b-code-interpreter ImportError → понятный RuntimeError."""
    import sys

    # Подменяем e2b_code_interpreter на None в sys.modules → ImportError.
    monkeypatch.setitem(sys.modules, "e2b_code_interpreter", None)
    from src.backend.infrastructure.ai.e2b_sandbox import E2BSandbox

    sandbox = E2BSandbox(api_key="x")
    with pytest.raises(RuntimeError, match="e2b-code-interpreter не установлен"):
        await sandbox.run("print(1)")


def test_register_e2b_sandbox_falls_back_to_noop_without_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Без E2B_API_KEY register_e2b_sandbox даёт NoOpSandbox."""
    from src.backend.core.ai.sandbox import CodeSandbox
    from src.backend.core.svcs_registry import clear_registry, get_service

    clear_registry()
    monkeypatch.delenv("E2B_API_KEY", raising=False)
    from src.backend.plugins.composition.ai_safety_setup import register_e2b_sandbox

    register_e2b_sandbox()
    sandbox = get_service(CodeSandbox)
    assert isinstance(sandbox, NoOpSandbox)
    clear_registry()
