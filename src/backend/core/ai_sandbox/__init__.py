"""Process-level AI Sandbox — hard resource isolation (Wave 3 #21 fix).

Проблема (DEEP_AUDIT):
    InProcessAgentSandbox / ProcessPoolAgentSandbox не enforce'ят:
    - Memory limit (RSS через RLIMIT_AS).
    - CPU time limit (RLIMIT_CPU).
    - File descriptor limit (RLIMIT_NOFILE).
    - Process count limit (RLIMIT_NPROC).
    - Subprocess reuses worker (process pool не даёт single-process isolation).

    Untrusted agent code может:
    - Съесть всю RAM → OOM kill всего приложения.
    - Открыть миллионы FD → resource exhaustion.
    - Fork bomb через subprocess.

Решение:
    ``ProcessSandbox`` — true subprocess-per-call isolation:
    - ``subprocess.run([sys.executable, "-c", ...])`` — fresh process per call.
    - ``resource.setrlimit`` для AS / CPU / NOFILE / NPROC.
    - ``timeout`` через ``subprocess.run(timeout=...)`` + ``Popen.kill()``.
    - stdout/stderr captured → returned в result.
    - Exit code != 0 → result.success=False.

Использование::

    from src.backend.core.ai_sandbox import (  # noqa: F401 — re-export
        ProcessSandbox, ProcessSandboxConfig, get_process_sandbox,
    )

    sandbox = get_process_sandbox(ProcessSandboxConfig(
        max_memory_mb=256,
        max_cpu_seconds=10,
        max_open_files=128,
        max_processes=64,
    ))

    result = sandbox.run(
        code="print(sum(range(100)))",
        timeout_seconds=5,
    )
    assert result.success
    assert result.stdout == "4950"
"""

from __future__ import annotations

from src.backend.core.ai_sandbox.sandbox import (  # noqa: F401 — re-export
    ProcessSandbox,
    ProcessSandboxConfig,
    ProcessSandboxResult,
    get_process_sandbox,
)

__all__ = (
    "ProcessSandbox",
    "ProcessSandboxConfig",
    "ProcessSandboxResult",
    "get_process_sandbox",
)
