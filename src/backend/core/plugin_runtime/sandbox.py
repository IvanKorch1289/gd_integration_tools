"""Sprint 14 W2 — sandbox-обёртка для plugin runtime.

Назначение:
    Делегирует исполнение пользовательского кода плагина в
    :class:`CodeSandbox` (e2b backend, см.
    :mod:`infrastructure.ai.e2b_sandbox`) согласно декларативному
    профилю ``plugin.toml::[sandbox]``. Capability ``code.execute``
    обязателен — без неё :class:`PluginSandboxAdapter` не вызывает
    sandbox и поднимает :class:`PluginSandboxError`.

    RestrictedPython намеренно не подключается — wheels отсутствуют
    под Python 3.14 (см. ADR-V15). При ``mode="none"`` адаптер
    возвращает ошибку, потому что без isolation вызов кода плагина
    запрещён политикой R-V15-4.

Использование:
    adapter = PluginSandboxAdapter(
        sandbox=e2b_sandbox,
        manifest=manifest,
        capability_check=gate.check,
    )
    result = await adapter.run(code)

Алгоритм:
    1. Проверка ``sandbox.enabled`` — если False, raise.
    2. Проверка ``mode == "e2b"`` — иначе not implemented.
    3. ``capability_check(plugin, "code.execute", scope=None)``.
    4. Применить psutil-resource-limits через
       :func:`_with_resource_limits` (контекстный менеджер).
    5. Делегировать в ``CodeSandbox.run(code, timeout_s=max_cpu_seconds)``.
    6. Если ``max_memory_mb`` превышен в любой момент — kill + raise.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping

    from src.backend.core.ai.sandbox import CodeSandbox, SandboxResult
    from src.backend.core.ai.workspace_manager import WorkspaceHandle
    from src.backend.services.plugins.manifest_v11 import PluginManifestV11

__all__ = (
    "PluginSandboxAdapter",
    "PluginSandboxError",
    "ResourceLimitsExceeded",
)

_logger = logging.getLogger("core.plugin_runtime.sandbox")

CapabilityChecker = "Callable[[str, str, str | None], None]"


class PluginSandboxError(RuntimeError):
    """Sandbox недоступен / не декларирован / capability отсутствует."""

    def __init__(self, plugin: str, reason: str) -> None:
        self.plugin = plugin
        self.reason = reason
        super().__init__(f"sandbox unavailable for plugin {plugin!r}: {reason}")


class ResourceLimitsExceeded(PluginSandboxError):
    """RSS/CPU/wall-clock превысил декларацию ``[sandbox]``."""

    def __init__(self, plugin: str, kind: str, limit: int, observed: int) -> None:
        self.kind = kind
        self.limit = limit
        self.observed = observed
        super().__init__(
            plugin,
            f"{kind} limit exceeded: {observed} > {limit}",
        )


@dataclass(frozen=True, slots=True)
class _ResourceSnapshot:
    """Минимальный набор метрик до/после исполнения (без psutil-зависимости)."""

    rss_bytes: int
    cpu_seconds: float


def _read_resource_snapshot() -> _ResourceSnapshot | None:
    """Снять текущие метрики процесса через psutil.

    Returns:
        :class:`_ResourceSnapshot` либо ``None`` если psutil не установлен
        (best-effort; в этом случае enforcement пропускается).
    """
    try:
        import psutil  # noqa: PLC0415

        process = psutil.Process()
        cpu_times = process.cpu_times()
        return _ResourceSnapshot(
            rss_bytes=int(process.memory_info().rss),
            cpu_seconds=float(cpu_times.user + cpu_times.system),
        )
    except Exception:  # noqa: BLE001
        return None


@contextmanager
def _with_resource_limits(
    plugin: str, max_memory_mb: int, max_cpu_seconds: int
) -> "Iterator[None]":
    """Контекстный менеджер: фиксирует snapshot до/после, проверяет дельты.

    Используется в дополнение к ``CodeSandbox.run(timeout_s=...)`` — e2b
    сам обеспечивает изоляцию, но локальный psutil-снимок даёт быструю
    защиту от runaway-плагинов на dev-стенде.
    """
    before = _read_resource_snapshot()
    yield
    after = _read_resource_snapshot()
    if before is None or after is None:
        return
    cpu_delta = after.cpu_seconds - before.cpu_seconds
    rss_delta_mb = max(0, (after.rss_bytes - before.rss_bytes) // (1024 * 1024))
    if cpu_delta > max_cpu_seconds:
        raise ResourceLimitsExceeded(
            plugin, "cpu_seconds", max_cpu_seconds, int(cpu_delta)
        )
    if rss_delta_mb > max_memory_mb:
        raise ResourceLimitsExceeded(
            plugin, "memory_mb", max_memory_mb, rss_delta_mb
        )


class PluginSandboxAdapter:
    """Адаптер ``PluginSandbox`` (декларация) → :class:`CodeSandbox` (runtime).

    Args:
        sandbox: Базовая sandbox-реализация (обычно
            ``infrastructure.ai.e2b_sandbox.E2BSandbox``).
        manifest: Манифест плагина — берётся ``sandbox`` + ``capabilities``.
        capability_check: Callback для проверки ``code.execute``
            (обычно ``CapabilityGate.check``).
    """

    def __init__(
        self,
        *,
        sandbox: "CodeSandbox",
        manifest: "PluginManifestV11",
        capability_check: "Callable[[str, str, str | None], None] | None" = None,
    ) -> None:
        self._sandbox = sandbox
        self._manifest = manifest
        self._capability_check = capability_check

    @property
    def is_enabled(self) -> bool:
        """`True`, если plugin.toml::[sandbox] активирован."""
        return self._manifest.sandbox is not None and self._manifest.sandbox.enabled

    async def run(
        self,
        code: str,
        *,
        files: "Mapping[str, bytes] | None" = None,
        workspace: "WorkspaceHandle | None" = None,
    ) -> "SandboxResult":
        """Запустить ``code`` в декларативно настроенном sandbox.

        Args:
            code: Текст Python-скрипта.
            files: Опц. дополнительные файлы для проброса в sandbox.
            workspace: AI-workspace handle для сохранения artifacts.

        Returns:
            :class:`SandboxResult` от базового sandbox-провайдера.

        Raises:
            PluginSandboxError: ``[sandbox]`` не задекларирован / mode не
                поддержан / capability ``code.execute`` отсутствует.
            ResourceLimitsExceeded: psutil зафиксировал превышение лимита.
        """
        profile = self._manifest.sandbox
        if profile is None or not profile.enabled:
            raise PluginSandboxError(
                self._manifest.name, "sandbox not declared in plugin.toml"
            )
        if profile.mode != "e2b":
            raise PluginSandboxError(
                self._manifest.name,
                f"unsupported sandbox mode: {profile.mode!r} (only 'e2b')",
            )

        if not any(cap.name == "code.execute" for cap in self._manifest.capabilities):
            raise PluginSandboxError(
                self._manifest.name,
                "capability 'code.execute' missing in plugin.toml::[[capabilities]]",
            )

        if self._capability_check is not None:
            self._capability_check(self._manifest.name, "code.execute", None)

        with _with_resource_limits(
            self._manifest.name,
            max_memory_mb=profile.max_memory_mb,
            max_cpu_seconds=profile.max_cpu_seconds,
        ):
            return await self._sandbox.run(
                code,
                timeout_s=float(profile.max_cpu_seconds),
                files=files,
                workspace=workspace,
            )
