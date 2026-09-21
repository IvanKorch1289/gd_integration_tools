"""Process-level AI Sandbox — hard resource isolation (Wave 3 #21 fix).

Pure stdlib implementation:
- ``subprocess.run`` — fresh process per call (true isolation).
- ``resource.setrlimit`` — address space, CPU, file descriptors, processes.
- Hard timeout via ``subprocess.run(timeout=...)``.
- No third-party deps.
"""

from __future__ import annotations

import logging
import os
import resource
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

__all__ = (
    "ProcessSandbox",
    "ProcessSandboxConfig",
    "ProcessSandboxResult",
    "get_process_sandbox",
)


@dataclass(slots=True)
class ProcessSandboxConfig:
    """Resource limits для subprocess execution.

    Attributes:
        max_memory_mb: Address space limit (RLIMIT_AS, bytes).
        max_cpu_seconds: CPU time limit (RLIMIT_CPU, seconds).
        max_open_files: Max open file descriptors (RLIMIT_NOFILE).
        max_processes: Max child processes (RLIMIT_NPROC).
        max_file_size_mb: Max file size (RLIMIT_FSIZE, bytes).
        env_passthrough: List of env var names to forward to subprocess.
        capture_env: Forward full env (default: True, but filtered by
            ``env_passthrough`` if set).
        python_path: List of additional PYTHONPATH entries.
        cwd: Working directory (None = current).
    """

    max_memory_mb: int = 256
    max_cpu_seconds: int = 10
    max_open_files: int = 128
    max_processes: int = 64
    max_file_size_mb: int = 16
    env_passthrough: tuple[str, ...] = ()
    capture_env: bool = True
    python_path: tuple[str, ...] = ()
    cwd: str | None = None

    def __post_init__(self) -> None:
        """Auto-validate on construction (fail-fast)."""
        self.validate()

    def validate(self) -> None:
        """Validate limits are sane (positive, non-zero where required)."""
        if self.max_memory_mb <= 0:
            raise ValueError("max_memory_mb must be > 0")
        if self.max_cpu_seconds <= 0:
            raise ValueError("max_cpu_seconds must be > 0")
        if self.max_open_files < 16:
            raise ValueError("max_open_files must be >= 16")
        if self.max_processes < 1:
            raise ValueError("max_processes must be >= 1")


@dataclass(slots=True)
class ProcessSandboxResult:
    """Subprocess execution result."""

    success: bool
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    duration_ms: float = 0.0
    error: str | None = None
    timed_out: bool = False
    oom_killed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "timed_out": self.timed_out,
            "oom_killed": self.oom_killed,
        }


def _apply_rlimits(config: ProcessSandboxConfig) -> None:
    """Apply RLIMIT_* в current subprocess (pre-exec)."""
    # Address space (virtual memory).
    resource.setrlimit(resource.RLIMIT_AS, (config.max_memory_mb * 1024 * 1024,) * 2)
    # CPU time.
    resource.setrlimit(
        resource.RLIMIT_CPU, (config.max_cpu_seconds, config.max_cpu_seconds + 1)
    )
    # Open file descriptors.
    resource.setrlimit(
        resource.RLIMIT_NOFILE, (config.max_open_files, config.max_open_files)
    )
    # Max child processes (NPROC is per-uid).
    try:
        resource.setrlimit(
            resource.RLIMIT_NPROC, (config.max_processes, config.max_processes)
        )
    except (ValueError, OSError) as exc:
        # Some platforms don't support RLIMIT_NPROC (e.g. macOS).
        logger.debug("RLIMIT_NPROC not supported: %s", exc)
    # File size.
    resource.setrlimit(
        resource.RLIMIT_FSIZE, (config.max_file_size_mb * 1024 * 1024,) * 2
    )


class ProcessSandbox:
    """Subprocess-based sandbox с hard resource limits.

    Each ``run()`` spawns a FRESH Python process. This is true isolation
    (vs ``ProcessPoolAgentSandbox`` which reuses workers). For periodic
    lightweight runs use the pool; for security-sensitive agent code use
    THIS class.

    Note: Python 3.13+ has ``sys.setrecursionlimit``, but for true RCE
    isolation use external sandboxes (Docker, E2B, gVisor). This sandbox
    mitigates accidental resource abuse, not malicious code.
    """

    def __init__(self, config: ProcessSandboxConfig | None = None) -> None:
        self._config = config or ProcessSandboxConfig()
        self._config.validate()

    @property
    def config(self) -> ProcessSandboxConfig:
        return self._config

    def update_config(self, **kwargs: Any) -> None:
        """Update config (e.g., adjust timeout, memory)."""
        from dataclasses import replace

        self._config = replace(self._config, **kwargs)
        self._config.validate()

    def run(
        self, code: str, *, timeout_seconds: float | None = None
    ) -> ProcessSandboxResult:
        """Run Python code в isolated subprocess с rlimits.

        Args:
            code: Python source code to execute.
            timeout_seconds: Wall-clock timeout (overrides config max_cpu).

        Returns:
            :class:`ProcessSandboxResult` с stdout/stderr/duration.
        """
        timeout = timeout_seconds or float(self._config.max_cpu_seconds * 2)
        start = time.time()

        # Build environment (forward selected vars).
        env: dict[str, str] = {}
        if self._config.capture_env:
            for k, v in os.environ.items():
                if (
                    self._config.env_passthrough
                    and k not in self._config.env_passthrough
                ):
                    continue
                env[k] = v
        if self._config.python_path:
            existing_pp = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = ":".join(
                (existing_pp,) + self._config.python_path
                if existing_pp
                else self._config.python_path
            )

        # Write wrapper script to temp file. We use a small inline script
        # that applies rlimits and runs user code with proper error
        # propagation.
        wrapper_script = (
            "import json, resource, sys, traceback\n"
            "try:\n"
            "    resource.setrlimit(resource.RLIMIT_AS, "
            f"({self._config.max_memory_mb * 1048576},) * 2)\n"
            "    resource.setrlimit(resource.RLIMIT_CPU, "
            f"({self._config.max_cpu_seconds}, {self._config.max_cpu_seconds + 1}))\n"
            "    resource.setrlimit(resource.RLIMIT_NOFILE, "
            f"({self._config.max_open_files}, {self._config.max_open_files}))\n"
            "    try:\n"
            f"        resource.setrlimit(resource.RLIMIT_NPROC, "
            f"({self._config.max_processes}, {self._config.max_processes}))\n"
            "    except (ValueError, OSError):\n"
            "        pass\n"
            "    resource.setrlimit(resource.RLIMIT_FSIZE, "
            f"({self._config.max_file_size_mb * 1048576},) * 2)\n"
            "except Exception as e:\n"
            "    print(f'setrlimit_error:{e}', file=sys.stderr)\n"
            "try:\n"
            f"    {code}\n"
            "except SystemExit as e:\n"
            "    print(f'__exit__:{e.code}', file=sys.stderr)\n"
            "except BaseException:\n"
            "    traceback.print_exc(file=sys.stderr)\n"
            "    sys.exit(1)\n"
        )

        tmp_path = ""
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False, encoding="utf-8"
            ) as f:
                f.write(wrapper_script)
                tmp_path = f.name
            cmd = [sys.executable, "-I", "-S", tmp_path]
            try:
                proc = subprocess.run(  # noqa: S603
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    env=env or None,
                    cwd=self._config.cwd,
                )
            except subprocess.TimeoutExpired:
                duration_ms = (time.time() - start) * 1000
                # Best-effort cleanup of stuck subprocess.
                self._kill_subprocess(cmd, env, self._config.cwd)
                return ProcessSandboxResult(
                    success=False,
                    exit_code=-1,
                    stdout="",
                    stderr=f"wall-time timeout after {timeout}s",
                    duration_ms=duration_ms,
                    error=f"timeout after {timeout}s",
                    timed_out=True,
                )
            except OSError as exc:
                duration_ms = (time.time() - start) * 1000
                return ProcessSandboxResult(
                    success=False,
                    exit_code=-1,
                    stdout="",
                    stderr=str(exc),
                    duration_ms=duration_ms,
                    error=f"OSError: {exc}",
                )

            duration_ms = (time.time() - start) * 1000
            # OOM detection: kernel sends SIGKILL (exit=-9) on RLIMIT_AS.
            oom = proc.returncode in (-9, 137)
            # Extract clean exit code from __exit__ marker.
            exit_code = proc.returncode
            stderr = proc.stderr
            for line in stderr.splitlines():
                if line.startswith("__exit__:"):
                    try:
                        exit_code = int(line.split(":", 1)[1])
                    except ValueError, IndexError:
                        pass
            success = exit_code == 0 and not oom
            return ProcessSandboxResult(
                success=success,
                exit_code=exit_code,
                stdout=proc.stdout,
                stderr=stderr,
                duration_ms=duration_ms,
                oom_killed=oom,
                error=("oom_killed" if oom else None),
            )
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def _kill_subprocess(
        self, cmd: list[str], env: dict[str, str] | None, cwd: str | None
    ) -> None:
        """Best-effort cleanup of timed-out subprocess."""
        try:
            proc = subprocess.Popen(  # noqa: S603
                cmd,
                env=env or None,
                cwd=cwd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                proc.kill()
            except OSError:
                pass
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                pass
        except Exception:
            logger.warning("Failed to clean up timed-out subprocess", exc_info=True)


# Module-level singleton (lazy).
_sandbox: ProcessSandbox | None = None


def get_process_sandbox(config: ProcessSandboxConfig | None = None) -> ProcessSandbox:
    """Module-level singleton getter."""
    global _sandbox
    if _sandbox is None:
        _sandbox = ProcessSandbox(config=config)
    return _sandbox


def reset_process_sandbox() -> None:
    """Reset singleton (test-only)."""
    global _sandbox
    _sandbox = None
