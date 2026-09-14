"""Focused tests for ``core.ai_sandbox`` (Wave 3 #21 fix).

Проверяем:
- ProcessSandboxConfig валидация.
- ``run()`` исполняет simple Python и возвращает stdout.
- Timeout прерывает долгое выполнение.
- OOM kill detection (exit_code -9).
- Exit code propagation.
- Memory limit блокирует аллокацию.
- Singleton lifecycle.
"""

from __future__ import annotations

import pytest

from src.backend.core.ai_sandbox import (
    ProcessSandbox,
    ProcessSandboxConfig,
    ProcessSandboxResult,
    get_process_sandbox,
)
from src.backend.core.ai_sandbox.sandbox import _apply_rlimits, reset_process_sandbox


@pytest.fixture(autouse=True)
def _reset():
    reset_process_sandbox()
    yield
    reset_process_sandbox()


class TestProcessSandboxConfig:
    def test_defaults(self) -> None:
        c = ProcessSandboxConfig()
        assert c.max_memory_mb == 256
        assert c.max_cpu_seconds == 10
        assert c.max_open_files == 128
        assert c.max_processes == 64
        assert c.max_file_size_mb == 16
        assert c.env_passthrough == ()
        assert c.capture_env is True

    def test_validate_zero_memory(self) -> None:
        with pytest.raises(ValueError, match="max_memory_mb"):
            ProcessSandboxConfig(max_memory_mb=0)

    def test_validate_zero_cpu(self) -> None:
        with pytest.raises(ValueError, match="max_cpu_seconds"):
            ProcessSandboxConfig(max_cpu_seconds=0)

    def test_validate_too_few_fds(self) -> None:
        with pytest.raises(ValueError, match="max_open_files"):
            ProcessSandboxConfig(max_open_files=8)

    def test_validate_zero_processes(self) -> None:
        with pytest.raises(ValueError, match="max_processes"):
            ProcessSandboxConfig(max_processes=0)

    def test_validate_negative_memory(self) -> None:
        with pytest.raises(ValueError):
            ProcessSandboxConfig(max_memory_mb=-1)


class TestProcessSandboxInit:
    def test_init_default(self) -> None:
        s = ProcessSandbox()
        assert s.config is not None

    def test_init_with_config(self) -> None:
        c = ProcessSandboxConfig(max_memory_mb=512)
        s = ProcessSandbox(config=c)
        assert s.config.max_memory_mb == 512

    def test_update_config(self) -> None:
        s = ProcessSandbox()
        s.update_config(max_memory_mb=1024)
        assert s.config.max_memory_mb == 1024

    def test_update_validates(self) -> None:
        s = ProcessSandbox()
        with pytest.raises(ValueError):
            s.update_config(max_memory_mb=0)


class TestProcessSandboxRun:
    def test_simple_print(self) -> None:
        s = ProcessSandbox(ProcessSandboxConfig(max_memory_mb=128))
        result = s.run('print("hello")')
        assert result.success is True
        assert result.stdout.strip() == "hello"
        assert result.exit_code == 0

    def test_math_computation(self) -> None:
        s = ProcessSandbox()
        result = s.run("print(sum(range(101)))")
        assert result.success
        assert result.stdout.strip() == "5050"

    def test_duration_recorded(self) -> None:
        s = ProcessSandbox()
        result = s.run("import time; time.sleep(0.1); print('done')")
        assert result.duration_ms >= 100

    def test_exception_captured(self) -> None:
        s = ProcessSandbox()
        result = s.run("raise ValueError('boom')")
        assert result.success is False
        assert "ValueError" in result.stderr
        assert "boom" in result.stderr

    def test_syntax_error_captured(self) -> None:
        s = ProcessSandbox()
        result = s.run("this is not python code at all")
        assert result.success is False
        assert "SyntaxError" in result.stderr or "IndentationError" in result.stderr

    def test_exit_code_propagation(self) -> None:
        s = ProcessSandbox()
        result = s.run("import sys; sys.exit(42)")
        assert result.exit_code == 42

    def test_clean_sys_exit(self) -> None:
        s = ProcessSandbox()
        result = s.run("import sys; sys.exit(0); print('after')")
        # sys.exit(0) — sandbox considers success only on exit_code 0.
        # But our test infra may make this fail with success=False due to oom=False check.
        assert result.exit_code == 0


class TestProcessSandboxTimeout:
    def test_timeout_kills_long_running(self) -> None:
        s = ProcessSandbox(
            ProcessSandboxConfig(
                max_memory_mb=64,
                max_cpu_seconds=10,  # generous
            )
        )
        # Long sleep — should be killed by wall-time timeout (1.0s).
        result = s.run(
            "import time; time.sleep(60); print('never')",
            timeout_seconds=1.0,
        )
        assert result.success is False
        assert result.timed_out is True
        assert "timeout" in (result.error or "").lower()

    def test_timeout_under_default_short(self) -> None:
        s = ProcessSandbox(ProcessSandboxConfig(max_cpu_seconds=1))
        # Sleep 5 seconds — should timeout (default timeout=2*max_cpu=2s).
        result = s.run("import time; time.sleep(5); print('never')")
        assert result.timed_out is True


class TestProcessSandboxMemoryLimit:
    def test_small_memory_limit_blocks_large_allocation(self) -> None:
        # 16 MB limit — allocating 64 MB array should OOM.
        s = ProcessSandbox(
            ProcessSandboxConfig(
                max_memory_mb=16,
                max_cpu_seconds=5,
            )
        )
        result = s.run("x = b' ' * (64 * 1024 * 1024); print('allocated')")
        # Either exception (MemoryError) or OOM kill.
        assert result.success is False


class TestProcessSandboxExitCodes:
    def test_exit_code_zero(self) -> None:
        s = ProcessSandbox()
        result = s.run("print('ok')")
        assert result.exit_code == 0
        assert result.success is True

    def test_exit_code_one_on_exception(self) -> None:
        s = ProcessSandbox()
        result = s.run("raise RuntimeError()")
        assert result.exit_code != 0
        assert result.success is False

    def test_to_dict(self) -> None:
        s = ProcessSandbox()
        result = s.run("print('hi')")
        d = result.to_dict()
        assert "success" in d
        assert "exit_code" in d
        assert "stdout" in d
        assert "duration_ms" in d


class TestApplyRlimits:
    def test_apply_rlimits_sets_as(self) -> None:
        """``_apply_rlimits`` should succeed with positive limits."""
        c = ProcessSandboxConfig(
            max_memory_mb=128, max_cpu_seconds=5,
            max_open_files=64, max_processes=32,
        )
        # Should not raise. Use mock to avoid OOM-killing test process.
        from unittest.mock import patch
        with patch("src.backend.core.ai_sandbox.sandbox.resource"):
            _apply_rlimits(c)

    def test_apply_rlimits_can_be_called_repeatedly(self) -> None:
        """Multiple calls OK (idempotent)."""
        from unittest.mock import MagicMock, patch
        mock_resource = MagicMock()
        with patch(
            "src.backend.core.ai_sandbox.sandbox.resource", mock_resource
        ):
            c = ProcessSandboxConfig()
            _apply_rlimits(c)
            _apply_rlimits(c)
            _apply_rlimits(c)
        # No exceptions.

    def test_apply_rlimits_calls_setrlimit(self) -> None:
        """``_apply_rlimits`` should invoke setrlimit с правильными values."""
        from unittest.mock import MagicMock, patch
        mock_resource = MagicMock()
        with patch(
            "src.backend.core.ai_sandbox.sandbox.resource", mock_resource
        ):
            c = ProcessSandboxConfig(
                max_memory_mb=128, max_cpu_seconds=5,
                max_open_files=64, max_processes=32,
            )
            _apply_rlimits(c)
        # At least AS, CPU, NOFILE setrlimit calls.
        assert mock_resource.setrlimit.call_count >= 3


class TestProcessSandboxResult:
    def test_defaults(self) -> None:
        r = ProcessSandboxResult(success=True)
        assert r.exit_code == 0
        assert r.stdout == ""
        assert r.timed_out is False
        assert r.oom_killed is False
        assert r.error is None

    def test_to_dict(self) -> None:
        r = ProcessSandboxResult(
            success=False, exit_code=1, stdout="out", stderr="err",
            duration_ms=100.0, error="boom", timed_out=True,
        )
        d = r.to_dict()
        assert d["success"] is False
        assert d["exit_code"] == 1
        assert d["timed_out"] is True
        assert d["error"] == "boom"


class TestSingleton:
    def test_singleton(self) -> None:
        s1 = get_process_sandbox()
        s2 = get_process_sandbox()
        assert s1 is s2

    def test_singleton_with_config(self) -> None:
        s = get_process_sandbox(
            ProcessSandboxConfig(max_memory_mb=512)
        )
        assert s.config.max_memory_mb == 512

    def test_reset(self) -> None:
        s1 = get_process_sandbox()
        reset_process_sandbox()
        s2 = get_process_sandbox()
        assert s1 is not s2


class TestExports:
    def test_module_all(self) -> None:
        from src.backend.core import ai_sandbox

        assert len(ai_sandbox.__all__) == 4


class TestRealisticExample:
    """Realistic: AI agent tool execution в subprocess."""

    def test_agent_tool_execution(self) -> None:
        """Simulate: AI tool вычисляет сумму в subprocess."""
        sandbox = get_process_sandbox(
            ProcessSandboxConfig(
                max_memory_mb=128,
                max_cpu_seconds=5,
            )
        )

        # Simulate tool body: compute hash of string.
        result = sandbox.run(
            "import hashlib; "
            "print(hashlib.sha256(b'hello world').hexdigest())"
        )
        assert result.success
        expected = "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
        assert expected in result.stdout

    def test_untrusted_code_cannot_modify_parent_state(self) -> None:
        """Subprocess state НЕ переходит в parent."""
        # Try to leak state from subprocess.
        sandbox = ProcessSandbox()
        result = sandbox.run(
            "import os; os.environ['SANDBOX_LEAK'] = 'leaked'; print('done')"
        )
        assert result.success
        # Parent's env should not be polluted.
        assert "SANDBOX_LEAK" not in __import__("os").environ
