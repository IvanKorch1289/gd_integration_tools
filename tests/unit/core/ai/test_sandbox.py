"""Unit tests for src.backend.core.ai.sandbox."""

from __future__ import annotations

import pytest

from src.backend.core.ai.sandbox import NoOpSandbox, SandboxResult


class TestSandboxResult:
    def test_defaults(self) -> None:
        result = SandboxResult(stdout="out", stderr="err", exit_code=0)
        assert result.stdout == "out"
        assert result.stderr == "err"
        assert result.exit_code == 0
        assert result.artifacts == {}

    def test_with_artifacts(self) -> None:
        result = SandboxResult(
            stdout="", stderr="", exit_code=1, artifacts={"f.txt": b"data"}
        )
        assert result.artifacts == {"f.txt": b"data"}


class TestNoOpSandbox:
    @pytest.mark.asyncio
    async def test_run_raises(self) -> None:
        sandbox = NoOpSandbox()
        with pytest.raises(RuntimeError, match="не сконфигурирован"):
            await sandbox.run("print(1)")
