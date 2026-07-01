"""E2B Code Interpreter — реализация :class:`CodeSandbox` (Wave 1.7).

`e2b-code-interpreter` запускает изолированный Python-runtime в облачной
sandbox-инфраструктуре e2b.dev. Capability ``code.execute`` проверяется
перед каждым ``run()``; artifacts сохраняются в выданный workspace
через :class:`AIFsFacade.create_new`.

Зависимость опциональная (``[ai]`` extra). При отсутствии SDK / API-key
:func:`register_e2b_sandbox` регистрирует :class:`NoOpSandbox` с warning.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

from src.backend.core.ai.sandbox import CodeSandbox, SandboxResult
from src.backend.infrastructure.logging.factory import get_logger

if TYPE_CHECKING:
    from src.backend.core.ai.fs_facade import AIFsFacade
    from src.backend.core.ai.workspace_manager import WorkspaceHandle

__all__ = ("E2BSandbox",)

_logger = get_logger("infrastructure.ai.e2b_sandbox")

CapabilityChecker = Callable[[str, str, str | None], None]


class E2BSandbox(CodeSandbox):
    """E2B-backed реализация :class:`CodeSandbox`.

    Args:
        api_key: API-ключ e2b.dev (env ``E2B_API_KEY``).
        capability_check: Callback, валидирующий ``code.execute``
            (обычно ``CapabilityGate.check``).
        plugin: Имя caller'а для capability-event.
        fs_facade: Опц. ``AIFsFacade`` для сохранения artifacts в
            выданный workspace.
    """

    def __init__(
        self,
        *,
        api_key: str,
        capability_check: CapabilityChecker | None = None,
        plugin: str = "ai-agent",
        fs_facade: AIFsFacade | None = None,
    ) -> None:
        self._api_key = api_key
        self._capability_check = capability_check
        self._plugin = plugin
        self._fs_facade = fs_facade

    async def run(
        self,
        code: str,
        *,
        timeout_s: float = 30.0,
        files: Mapping[str, bytes] | None = None,
        workspace: WorkspaceHandle | None = None,
    ) -> SandboxResult:
        """Выполняет Python-код в E2B sandbox с capability-check и artifact-выгрузкой.

        Проверяет capability ``code.execute``, создаёт E2B sandbox, опционально
        загружает файлы, выполняет код. При наличии workspace артефакты
        выгружаются в AI-filesystem facade. Sandbox гарантированно убивается
        в ``finally``.

        Args:
            code: Python-код для выполнения.
            timeout_s: Таймаут выполнения (секунды).
            files: Файлы для загрузки в sandbox (relative_path → bytes).
            workspace: Handle AI-workspace для сохранения артефактов.

        Returns:
            ``SandboxResult`` со stdout, stderr, exit_code и artifacts.

        Raises:
            RuntimeError: Если e2b-code-interpreter не установлен.
        """
        if self._capability_check is not None:
            scope = workspace.session_id if workspace is not None else None
            self._capability_check(self._plugin, "code.execute", scope)

        try:
            from e2b_code_interpreter import Sandbox as _E2BSandbox
        except ImportError as exc:
            raise RuntimeError(
                "e2b-code-interpreter не установлен; добавьте "
                "пакет в [ai] extra или используйте NoOpSandbox."
            ) from exc

        sandbox: Any = _E2BSandbox(api_key=self._api_key, timeout=int(timeout_s))
        try:
            if files:
                for relative, content in files.items():
                    sandbox.files.write(relative, content)
            execution = sandbox.run_code(code)
            stdout = "\n".join(execution.logs.stdout) if execution.logs else ""
            stderr = "\n".join(execution.logs.stderr) if execution.logs else ""
            exit_code = 1 if execution.error else 0

            artifacts: dict[str, bytes] = {}
            if workspace is not None and self._fs_facade is not None:
                artifacts = self._collect_artifacts(sandbox)
                for relative, content in artifacts.items():
                    try:
                        self._fs_facade.create_new(workspace, relative, content)
                    except Exception as art_exc:
                        _logger.warning(
                            "E2B artifact write failed: %s — %s", relative, art_exc
                        )

            return SandboxResult(
                stdout=stdout, stderr=stderr, exit_code=exit_code, artifacts=artifacts
            )
        finally:
            try:
                sandbox.kill()
            except Exception as kill_exc:
                _logger.debug("E2B sandbox kill error: %s", kill_exc)

    @staticmethod
    def _collect_artifacts(sandbox: Any) -> dict[str, bytes]:
        """Best-effort выгрузка файлов из sandbox.

        e2b SDK возвращает разные структуры в разных версиях; обрабатываем
        наиболее распространённые формы (list[dict] / iterable).
        """
        artifacts: dict[str, bytes] = {}
        try:
            entries = sandbox.files.list("/home/user")
        except Exception as _:
            return artifacts
        for entry in entries or ():
            try:
                path = getattr(entry, "path", None) or entry.get("path")
                if not path:
                    continue
                content = sandbox.files.read(path)
                artifacts[str(path)] = (
                    content.encode() if isinstance(content, str) else bytes(content)
                )
            except Exception as _:
                continue
        return artifacts
