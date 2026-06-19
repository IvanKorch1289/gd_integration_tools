"""AgentSandbox — изолированное выполнение LangGraph-агентов (S133 W4).

Предоставляет фасад над in-process и out-of-process execution backend'ами.
P0 scope: in-process (default) и spawn-process isolation через stdlib
:class:`ProcessPoolExecutor`.

Future backends (E2B, gVisor, Temporal sandbox-activity) реализуют тот же
protocol без изменений в :class:`AgentGraphProcessor`.
"""

from __future__ import annotations

import asyncio
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from src.backend.core.logging import get_logger

if TYPE_CHECKING:
    pass

__all__ = (
    "AgentSandbox",
    "AgentSandboxResult",
    "InProcessAgentSandbox",
    "ProcessPoolAgentSandbox",
    "get_process_pool_agent_sandbox",
)

_logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class AgentSandboxResult:
    """Результат выполнения агентского шага в sandbox.

    Attributes:
        success: True если sandbox-выполнение завершилось без исключения.
        data: Словарь-результат (формат ``build_and_run_agent``) либо
            ``{"error": str}`` при ``success=False``.
        backend: Имя backend'а, который произвёл выполнение.
    """

    success: bool
    data: dict[str, Any]
    backend: str


@runtime_checkable
class AgentSandbox(Protocol):
    """Backend-agnostic sandbox для LangGraph ReAct-агента."""

    async def run_react(
        self,
        *,
        prompt: str,
        tool_actions: list[str],
        model: str,
        temperature: float,
        durable: bool,
        session_id: str | None,
    ) -> AgentSandboxResult:
        """Запустить ReAct-агента в sandbox.

        Args:
            prompt: Пользовательский prompt.
            tool_actions: Список action-имён, доступных как tools.
            model: LLM model identifier.
            temperature: Sampling temperature.
            durable: Включить durable checkpointing.
            session_id: Опц. LangGraph thread_id.

        Returns:
            :class:`AgentSandboxResult`.
        """
        ...

    async def shutdown(self) -> None:
        """Освободить ресурсы backend'а (идемпотентно)."""
        ...


class InProcessAgentSandbox:
    """In-process sandbox — default, отсутствие изоляции процесса.

    Используется когда ``isolated=False`` или когда out-of-process backend
    недоступен.
    """

    async def run_react(
        self,
        *,
        prompt: str,
        tool_actions: list[str],
        model: str,
        temperature: float,
        durable: bool,
        session_id: str | None,
    ) -> AgentSandboxResult:
        from src.backend.services.ai.ai_graph import build_and_run_agent

        result = await build_and_run_agent(
            prompt=prompt,
            tool_actions=tool_actions,
            model=model,
            temperature=temperature,
            durable=durable,
            session_id=session_id,
        )
        success = "error" not in result
        return AgentSandboxResult(success=success, data=result, backend="in_process")

    async def shutdown(self) -> None:
        return None


def _sync_run_react(
    prompt: str,
    tool_actions: list[str],
    model: str,
    temperature: float,
    durable: bool,
    session_id: str | None,
) -> dict[str, Any]:
    """Sync entrypoint для ``ProcessPoolExecutor``.

    Выполняется в spawn-воркере без доступа к event loop родителя.
    """
    import asyncio

    from src.backend.services.ai.ai_graph import build_and_run_agent

    return asyncio.run(
        build_and_run_agent(
            prompt=prompt,
            tool_actions=tool_actions,
            model=model,
            temperature=temperature,
            durable=durable,
            session_id=session_id,
        )
    )


class ProcessPoolAgentSandbox:
    """Spawn-process sandbox через stdlib :class:`ProcessPoolExecutor`.

    ponytail: stdlib first — не требует E2B/API-key. Изоляция на уровне
    отдельного Python-процесса (memory, file descriptors). Для полной
    sandbox'ы (network/filesystem) нужен E2B/gVisor backend.

    Args:
        max_workers: Размер пула spawn-воркеров. Default ``1`` — агенты
            CPU/GPU-bound, параллелить внутри одного пула нецелесообразно.
    """

    def __init__(self, max_workers: int = 1) -> None:
        ctx = multiprocessing.get_context("spawn")
        self._executor = ProcessPoolExecutor(max_workers=max_workers, mp_context=ctx)
        self._closed = False

    async def run_react(
        self,
        *,
        prompt: str,
        tool_actions: list[str],
        model: str,
        temperature: float,
        durable: bool,
        session_id: str | None,
        max_wall_time_s: float = 600.0,
    ) -> AgentSandboxResult:
        """Запускает ReAct agent в subprocess с timeout enforcement (S168 W10 P1-6).

        Args:
            max_wall_time_s: Hard wall-clock timeout (default 600s = 10 min).
                При превышении — ``asyncio.TimeoutError`` → AgentSandboxResult
                с success=False, error="wall_time_exceeded".
                Pер per AgentLimits.max_wall_time_s spec (S28 W3).
        """
        if self._closed:
            raise RuntimeError("ProcessPoolAgentSandbox already shut down")

        loop = asyncio.get_running_loop()
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    self._executor,
                    _sync_run_react,
                    prompt,
                    tool_actions,
                    model,
                    temperature,
                    durable,
                    session_id,
                ),
                timeout=max_wall_time_s,
            )
            success = "error" not in result
            return AgentSandboxResult(
                success=success, data=result, backend="process_pool"
            )
        except asyncio.TimeoutError:
            _logger.warning(
                "ProcessPoolAgentSandbox: wall_time_exceeded after %.1fs",
                max_wall_time_s,
            )
            return AgentSandboxResult(
                success=False,
                data={"error": f"wall_time_exceeded after {max_wall_time_s:.1f}s"},
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
        if self._closed:
            return
        self._closed = True
        # ProcessPoolExecutor.shutdown блокирует; запускаем в thread executor.
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._executor.shutdown, True)


_process_pool_sandbox: ProcessPoolAgentSandbox | None = None


def get_process_pool_agent_sandbox() -> ProcessPoolAgentSandbox:
    """Singleton process-pool sandbox (lazy)."""
    global _process_pool_sandbox
    if _process_pool_sandbox is None:
        _process_pool_sandbox = ProcessPoolAgentSandbox(max_workers=1)
    return _process_pool_sandbox
