"""ProcessPoolAgentSandbox — separate process pool execution (W9 P2-13 Phase 5).

W9 P2-13 Phase 5 (cycle 153): извлечено из ``services/ai/agent_sandbox.py``
(601 LOC god-module). Default-OFF-safe (S172 M5 ARC-008) backend для
untrusted code — process isolation без cloud latency.

Back-compat: ``services/ai/agent_sandbox.py`` (file) продолжает re-export
через thin ``__init__.py`` shim (см. ADR-0330).
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ProcessPoolExecutor
from typing import Any

from src.backend.core.ai.agent_sandbox_protocol import AgentSandboxResult
from src.backend.core.logging import get_logger
from src.backend.services.ai.agent_sandbox._in_process import _sync_run_react

_logger = get_logger(__name__)


class ProcessPoolAgentSandbox:
    """Sandbox через ProcessPoolExecutor.

    S172 M5 ARC-008: hard isolation через отдельные процессы. Каждое
    выполнение в spawn-воркере — process isolation для memory state и
    file descriptors.

    Args:
        max_workers: Количество параллельных процессов-воркеров.
        max_wall_time_s: Hard timeout per execution (default 600s).

    """

    def __init__(self, *, max_workers: int = 1, max_wall_time_s: float = 600.0) -> None:
        # lazy-create executor (heavy resource).
        self._executor: ProcessPoolExecutor | None = None
        self._max_workers = max_workers
        self._max_wall_time_s = max_wall_time_s
        self._closed = False

    def _get_executor(self) -> ProcessPoolExecutor:
        if self._executor is None:
            self._executor = ProcessPoolExecutor(max_workers=self._max_workers)
        return self._executor

    async def run_react(
        self,
        *,
        prompt: str,
        tool_actions: list[str],
        model: str,
        temperature: float,
        durable: bool,
        session_id: str | None,
        max_wall_time_s: float | None = None,
    ) -> AgentSandboxResult:
        """Run agent в process-pool worker (sync, wrapped в to_thread)."""
        wall_time = (
            max_wall_time_s if max_wall_time_s is not None else self._max_wall_time_s
        )
        loop = asyncio.get_running_loop()

        try:
            result: dict[str, Any] = await asyncio.wait_for(
                loop.run_in_executor(
                    self._get_executor(),
                    _sync_run_react,
                    prompt,
                    tool_actions,
                    model,
                    temperature,
                    durable,
                    session_id,
                ),
                timeout=wall_time,
            )
            success = "error" not in result
            return AgentSandboxResult(
                success=success, data=result, backend="process_pool"
            )
        except TimeoutError:
            return AgentSandboxResult(
                success=False,
                data={"error": f"wall_time_exceeded after {wall_time:.1f}s"},
                backend="process_pool",
            )
        except Exception as exc:
            _logger.warning("ProcessPoolAgentSandbox run failed: %s", exc)
            return AgentSandboxResult(
                success=False,
                data={"error": f"sandbox execution failed: {exc}"},
                backend="process_pool",
            )

    async def shutdown(self) -> None:
        """Shutdown process-pool executor."""
        if self._closed:
            return
        self._closed = True
        if self._executor is None:
            return
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._executor.shutdown, True)
