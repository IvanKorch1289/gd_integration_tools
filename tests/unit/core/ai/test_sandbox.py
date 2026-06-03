"""Unit-тесты :class:`SandboxResult`, :class:`NoOpSandbox`, :class:`CodeSandbox`.

Покрывают:

* ``SandboxResult`` — frozen-dataclass с дефолтами и кастомными артефактами;
* ``NoOpSandbox.run`` — RuntimeError с понятным сообщением (защита от
  silent-fallback на ``subprocess.run``, см. V15 R-V15-4);
* ``CodeSandbox`` — structural Protocol-проверка сигнатуры.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import FrozenInstanceError

import pytest

from src.backend.core.ai.sandbox import CodeSandbox, NoOpSandbox, SandboxResult

# ─── SandboxResult ──────────────────────────────────────────────────────────


def test_sandbox_result_minimal_construction() -> None:
    """Минимальная конструкция: stdout/stderr/exit_code, артефакты по дефолту пусты."""
    result = SandboxResult(stdout="hello", stderr="", exit_code=0)
    assert result.stdout == "hello"
    assert result.stderr == ""
    assert result.exit_code == 0
    assert result.artifacts == {}


def test_sandbox_result_with_artifacts() -> None:
    """Артефакты передаются как Mapping[str, bytes]."""
    artifacts: Mapping[str, bytes] = {
        "report.csv": b"a,b\n1,2\n",
        "chart.png": b"\x89PNG\r\n\x1a\n",
    }
    result = SandboxResult(stdout="ok", stderr="", exit_code=0, artifacts=artifacts)
    assert result.artifacts == artifacts
    assert result.artifacts["report.csv"] == b"a,b\n1,2\n"
    assert result.artifacts["chart.png"][:4] == b"\x89PNG"


def test_sandbox_result_frozen() -> None:
    """SandboxResult — frozen dataclass: нельзя менять поля после создания."""
    result = SandboxResult(stdout="x", stderr="", exit_code=0)
    with pytest.raises(FrozenInstanceError):
        result.exit_code = 1  # type: ignore[misc]


def test_sandbox_result_nonzero_exit_code() -> None:
    """Ненулевой exit_code сохраняется как есть (semantic: ошибка исполнения)."""
    result = SandboxResult(stdout="", stderr="Traceback...", exit_code=137)
    assert result.exit_code == 137
    assert "Traceback" in result.stderr


def test_sandbox_result_default_factory_is_independent() -> None:
    """default_factory=dict() гарантирует, что разные инстансы не делят один dict."""
    r1 = SandboxResult(stdout="a", stderr="", exit_code=0)
    r2 = SandboxResult(stdout="b", stderr="", exit_code=0)
    # Разные объекты-словари у разных инстансов (default_factory не шарит state).
    assert r1.artifacts == {}
    assert r2.artifacts == {}
    assert r1.artifacts is not r2.artifacts


# ─── NoOpSandbox ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_noop_sandbox_raises_runtime_error() -> None:
    """NoOpSandbox.run всегда поднимает RuntimeError (нет fallback на subprocess)."""
    sandbox = NoOpSandbox()
    with pytest.raises(RuntimeError) as exc_info:
        await sandbox.run("print('hi')")
    msg = str(exc_info.value)
    # Сообщение должно подсказать, как починить (e2b / E2B_API_KEY).
    assert "E2B_API_KEY" in msg or "e2b-code-interpreter" in msg


@pytest.mark.asyncio
async def test_noop_sandbox_ignores_files_and_workspace() -> None:
    """Параметры ``files``/``workspace`` не отменяют отказ (MVP-фаза)."""
    sandbox = NoOpSandbox()
    with pytest.raises(RuntimeError):
        await sandbox.run(
            "x = 1", timeout_s=5.0, files={"input.csv": b"a\n"}, workspace=None
        )


@pytest.mark.asyncio
async def test_noop_sandbox_with_custom_timeout() -> None:
    """``timeout_s`` не влияет на NoOp — всё равно RuntimeError."""
    sandbox = NoOpSandbox()
    with pytest.raises(RuntimeError):
        await sandbox.run("raise Exception()", timeout_s=0.001)


def test_noop_sandbox_is_assignable_to_codesandbox_protocol() -> None:
    """NoOpSandbox совместим с Protocol CodeSandbox по structural subtyping."""
    sandbox: CodeSandbox = NoOpSandbox()
    assert hasattr(sandbox, "run")
    assert callable(sandbox.run)


# ─── CodeSandbox Protocol — smoke-проверка сигнатуры ────────────────────────


def test_codesandbox_protocol_has_run_attribute() -> None:
    """CodeSandbox — Protocol с обязательным async-методом ``run``."""
    assert hasattr(CodeSandbox, "run")
    # run is defined on the Protocol; smoke-проверка достаточно.
    assert callable(CodeSandbox.run) or "run" in CodeSandbox.__dict__


def test_codesandbox_is_runtime_protocol() -> None:
    """Любой класс с подходящим ``run`` совместим с CodeSandbox (structural)."""

    class MySandbox:
        async def run(
            self, code: str, *, timeout_s: float = 30.0, files=None, workspace=None
        ) -> SandboxResult:
            return SandboxResult(stdout="ok", stderr="", exit_code=0)

    sb: CodeSandbox = MySandbox()  # type: ignore[assignment]
    assert sb is not None
    assert hasattr(sb, "run")
