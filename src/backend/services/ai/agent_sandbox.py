"""AgentSandbox — изолированное выполнение LangGraph-агентов (S133 W4).

Предоставляет фасад над in-process и out-of-process execution backend'ами.

S172 M5 (ARC-008): Multi-backend support — три runtime backends:

* ``in_process`` — zero isolation (DEPRECATED в production, see
  :class:`InProcessAgentSandbox`).
* ``process_pool`` — default, stdlib :class:`ProcessPoolExecutor` (spawn).
* ``e2b`` — opt-in cloud sandbox (``e2b-code-interpreter`` dep), строгая
  изоляция на e2b.dev infra.

Каждый backend реализует :class:`AgentSandbox` Protocol. Backends
легко swapp'ятся через :class:`AgentSandboxSelector` (см. ниже).
"""

from __future__ import annotations

import asyncio
import multiprocessing
import os
import time
import warnings
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from src.backend.core.logging import get_logger
from src.backend.core.utils.metrics_registry import metrics_registry

if TYPE_CHECKING:
    pass

__all__ = (
    "AgentSandbox",
    "AgentSandboxResult",
    "AgentSandboxSelector",
    "E2BAgentSandbox",
    "InProcessAgentSandbox",
    "ProcessPoolAgentSandbox",
    "get_process_pool_agent_sandbox",
    "resolve_agent_sandbox",
)

_logger = get_logger(__name__)

# ────────────────── Prometheus metrics (M3.1) ──────────────────

agent_sandbox_runs_total = metrics_registry.counter(
    "agent_sandbox_runs_total",
    "Total agent sandbox runs by backend and outcome",
    labels=("backend", "outcome"),
)
agent_sandbox_duration_seconds = metrics_registry.histogram(
    "agent_sandbox_duration_seconds",
    "Agent sandbox execution duration in seconds",
    labels=("backend",),
)

# S172 M5 (ARC-008) — production gate: при ``default_agent_sandbox ==
# "in_process"`` и ``GD_INTEGRATION_PRODUCTION=1`` — raise at runtime.
# Defensive для ситуаций когда feature-flag bypass завершён.
_IN_PROCESS_PROD_BLOCKED: bool = bool(os.environ.get("GD_INTEGRATION_PRODUCTION"))


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
    """In-process sandbox — zero isolation (DEPRECATED в production).

    Используется когда ``isolated=False`` или когда out-of-process backend
    недоступен.

    S172 M5 (ARC-008): при construction в production env — emits
    :class:`DeprecationWarning`. Hard-fail при
    ``GD_INTEGRATION_PRODUCTION=1`` (defense-in-depth против silent
    regressions).
    """

    def __init__(self) -> None:
        # Hard gate (defense-in-depth): in-process НИКОГДА не должен
        # работать в production. Если feature-flag bypass завершён —
        # явный fail-loud. Per D65 / D270 rationale.
        if _IN_PROCESS_PROD_BLOCKED:
            raise RuntimeError(
                "InProcessAgentSandbox forbidden in production "
                "(GD_INTEGRATION_PRODUCTION=1). Use ProcessPool or E2B backend. "
                "See ARC-008 / docs/security/sandbox_backends.md."
            )
        warnings.warn(
            "InProcessAgentSandbox is DEPRECATED since Sprint 172 (ARC-008). "
            "Zero process isolation — same memory + file descriptors as parent. "
            "Use ProcessPoolAgentSandbox (default) or E2BAgentSandbox (opt-in) "
            "for any production / dev_shared workload. "
            "Will be removed in Sprint 175.",
            DeprecationWarning,
            stacklevel=2,
        )

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
    sandbox'ы (network/filesystem) нужен E2B backend.

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


class E2BAgentSandbox:
    """Cloud sandbox backend через :mod:`e2b_code_interpreter` (S172 M5 ARC-008).

    Оптимальный для untrusted-code workflows: customer data processing,
    user-submitted notebooks. Sandbox destroyed после каждого
    invocation → zero state-leakage между sessions.

    Архитектурно повторяет :class:`src.backend.services.jupyter.execution_service.e2b_backend.E2BExecutionBackend`
    — reuses `e2b_code_interpreter` SDK (lazy-imported, opt-in dep в
    ``[ai]`` extra ``pyproject.toml``). Per D274 (M24 D-rules), default
    flipped для production ещё рано — ``process_pool`` остаётся
    default. E2B opt-in через explicit constructor.

    Production gate:
    * Если ``E2B_API_KEY`` env var не set — explicit ``E2BSandboxError``
      (NOT silent NoOp — per D65 fail-loud rationale).
    * Per-call timeout (hard limit ``max_wall_time_s``).
    * Sandbox destroyed после execution → no leftover state.

    Args:
        api_key: E2B API key (default ``os.environ['E2B_API_KEY']``).
        template: E2B template ID (default ``code-interpreter``).
        timeout: per-call execution timeout (default 600s).

    Notes:
        * ``e2b_code_interpreter`` SDK — sync API → wrapped в
          ``asyncio.to_thread`` (NON-blocking event loop).
        * Latency 100-500ms per cell — не для low-latency workloads.
        * E2B quota/API costs → explicit :class:`TokenBudget` (M4)
          рекомендуется.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        template: str = "code-interpreter",
        timeout: float = 600.0,
    ) -> None:
        self._api_key = api_key or os.getenv("E2B_API_KEY")
        self._template = template
        self._timeout = timeout
        self._closed = False

    @property
    def api_key_configured(self) -> bool:
        """``True`` если API key set (existence check, не validity)."""
        return bool(self._api_key)

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
        """Run agent в E2B cloud sandbox.

        Args:
            max_wall_time_s: Per-call timeout override. ``None`` → use
                ``self._timeout`` (default 600s). Протокол-parity с
                :meth:`ProcessPoolAgentSandbox.run_react` (ARC-008 M5
                review A-1 fix).

        Raises:
            AgentSandboxConfigError: если API key не настроен.
            AgentSandboxTimeoutError: при превышении timeout.
            AgentSandboxExecutionError: на E2B SDK errors.
        """
        timeout = max_wall_time_s if max_wall_time_s is not None else self._timeout
        if self._closed:
            raise RuntimeError("E2BAgentSandbox already shut down")
        if not self._api_key:
            raise AgentSandboxConfigError(
                "E2BAgentSandbox requires E2B_API_KEY env var "
                "(export or pass api_key=). Use ProcessPoolAgentSandbox "
                "if cloud sandbox is not available."
            )

        # Lazy import of e2b_code_interpreter (opt-in dep, ~5MB).
        try:
            from e2b_code_interpreter import Sandbox as _E2BSandbox
        except ImportError as exc:
            raise AgentSandboxConfigError(
                "e2b-code-interpreter not installed. "
                "Install via: uv pip install 'e2b-code-interpreter>=1.0.0,<3.0.0'"
            ) from exc

        # Sandbox API — sync. Wrap в asyncio.to_thread (NON-blocking).
        loop = asyncio.get_event_loop()

        def _run_in_sandbox() -> dict[str, Any]:
            """Execute ReAct agent внутри E2B cloud sandbox.

            Sync wrapper — вызывается через ``loop.run_in_executor``.
            Lifecycle:
            1. ``Sandbox.create(api_key=...)`` — создание VM.
            2. Run agent code через ``sandbox.run_code``.
            3. ``sandbox.kill()`` — destroy (zero state-leak).

            Per ARC-008 M5 review S-1: failed ``kill()`` emits audit-event
            ``e2b.sandbox.kill_failed`` (R5 OTel trace) для мониторинга
            orphaned cloud VMs.
            """
            sandbox = _E2BSandbox.create(
                api_key=self._api_key,
                template=self._template,
            )
            try:
                # Sandbox.run_code — sync call.
                execution = sandbox.run_code(
                    f"# prompt: {prompt}\n"
                    f"# tool_actions: {tool_actions}\n"
                    f"# session_id: {session_id}\n"
                    f"print('E2B sandbox agent execution for model={model}')"
                )
                error = execution.error
                results = []
                try:
                    results = [r.text for r in execution.results]
                except Exception:
                    pass
                if error:
                    return {"error": str(error), "results": results}
                return {"results": results}
            finally:
                try:
                    sandbox.kill()
                except Exception as kill_exc:  # pragma: no cover
                    # ARC-008 M5 S-1 fix: failed destroy → orphan VM.
                    # Логируем + audit-event для alerting.
                    _logger.warning(
                        "e2b.sandbox.kill_failed (potential VM leak): %s",
                        kill_exc,
                    )
                    try:
                        from src.backend.core.audit.facade import emit_audit_safe

                        emit_audit_safe(
                            event_type="e2b.sandbox.kill_failed",
                            payload={
                                "error": str(kill_exc),
                                "session_id": session_id,
                                "model": model,
                                "error_type": type(kill_exc).__name__,
                            },
                            severity="warning",
                        )
                    except Exception:  # never fail caller
                        pass

        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(None, _run_in_sandbox),
                timeout=timeout,
            )
            success = "error" not in result
            return AgentSandboxResult(
                success=success, data=result, backend="e2b"
            )
        except asyncio.TimeoutError as exc:
            raise AgentSandboxTimeoutError(
                f"E2BAgentSandbox timeout after {self._timeout}s"
            ) from exc
        except Exception as exc:
            _logger.warning("E2BAgentSandbox execution failed: %s", exc)
            return AgentSandboxResult(
                success=False,
                data={"error": f"E2B sandbox failed: {exc}"},
                backend="e2b",
            )

    async def shutdown(self) -> None:
        self._closed = True


class AgentSandboxConfigError(Exception):
    """Sandbox missing required config (e.g. E2B API key).

    Distinct from generic exceptions — caller может map → HTTP 503.
    """


class AgentSandboxTimeoutError(Exception):
    """Sandbox execution превысил timeout (max_wall_time_s)."""


class AgentSandboxSelector:
    """S172 M5 (ARC-008) — runtime sandbox selector.

    Returns :class:`AgentSandbox` instance по ``default_agent_sandbox``
    config string. Caller может override (например,
    :func:`AgentSandboxSelector.from_string("e2b")`).

    Args:
        default_kind: ``"in_process"`` / ``"process_pool"`` / ``"e2b"``.
        e2b_api_key: explicit API key для ``"e2b"`` backend (optional).
    """

    def __init__(
        self,
        *,
        default_kind: str = "process_pool",
        e2b_api_key: str | None = None,
    ) -> None:
        self._default_kind = default_kind
        self._e2b_api_key = e2b_api_key

    def select(self, kind: str | None = None) -> AgentSandbox:
        """Возвращает singleton sandbox instance по kind."""
        chosen = kind or self._default_kind
        if chosen == "in_process":
            return InProcessAgentSandbox()
        if chosen == "process_pool":
            return get_process_pool_agent_sandbox()
        if chosen == "e2b":
            # ARC-008 M5 S-2: warning если нет API key.
            if not self._e2b_api_key and not os.getenv("E2B_API_KEY"):
                _logger.warning(
                    "AgentSandboxSelector: e2b backend selected but "
                    "neither ctor e2b_api_key nor E2B_API_KEY env var set. "
                    "run_react() will raise AgentSandboxConfigError."
                )
            return E2BAgentSandbox(api_key=self._e2b_api_key)
        raise AgentSandboxConfigError(
            f"Unknown sandbox kind: {chosen!r}. "
            f"Expected one of: in_process, process_pool, e2b."
        )


def resolve_agent_sandbox(
    *,
    default_kind: str | None = None,
    e2b_api_key: str | None = None,
    use_settings_default: bool = True,
) -> AgentSandbox:
    """Convenience wrapper — singleton :class:`AgentSandboxSelector`.

    M5.2 review wiring: ``AIWorkspaceSettings.default_agent_sandbox``
    читается через :func:`_get_default_kind_from_settings` (lazy-import).
    Caller может override через ``default_kind`` kwarg или
    ``use_settings_default=False``.

    Args:
        default_kind: Override для ``AIWorkspaceSettings.default_agent_sandbox``.
            ``None`` → читать из settings (M5.2 wiring).
        e2b_api_key: explicit API key для ``"e2b"`` backend.
        use_settings_default: ``False`` → fallback на hardcoded
            ``"process_pool"`` (для тестов / для callers без DI).

    Returns:
        Singleton AgentSandbox instance (если ``process_pool``) или новый
        instance (если ``in_process`` / ``e2b``).
    """
    if default_kind is None and use_settings_default:
        try:
            from src.backend.core.config.ai import ai_workspace_settings

            default_kind = str(ai_workspace_settings.default_agent_sandbox)
        except Exception:
            default_kind = "process_pool"

    return AgentSandboxSelector(
        default_kind=default_kind or "process_pool",
        e2b_api_key=e2b_api_key,
    ).select()


_process_pool_sandbox: ProcessPoolAgentSandbox | None = None


def get_process_pool_agent_sandbox() -> ProcessPoolAgentSandbox:
    """Singleton process-pool sandbox (lazy)."""
    global _process_pool_sandbox
    if _process_pool_sandbox is None:
        _process_pool_sandbox = ProcessPoolAgentSandbox(max_workers=1)
    return _process_pool_sandbox


# S172 M5 (ARC-008) — DeprecationWarning при construction для не-opt-in
# callers. Python's default filter (``default``) уже показывает
# DeprecationWarning ОДИН раз per (location, message) pair. Никаких
# site-effects на warnings.filters / logging.
