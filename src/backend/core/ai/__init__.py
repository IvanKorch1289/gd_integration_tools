"""AI Safety subsystem (V15 R-V15-4 + W22).

Контракт:

* :class:`AIWorkspaceManager` — выдаёт изолированные writable-каталоги
  для AI-агентов: ``${AI_WORKSPACE}/<tenant>/<session>/<artifact>``;
* :class:`AIFsFacade` — единственный санкционированный путь FS-доступа
  для AI-плагинов; ``read(path)`` через capability ``fs.read.<path>``,
  ``create_new(path, content)`` через capability ``fs.create_new.<workspace>``;
* TTL=7 дней + per-tenant quota; cleanup-loop через ``TaskRegistry``.

Запрещено:

* запись существующих файлов проекта;
* удаление файлов;
* прямой ``subprocess.run`` (только sandboxed e2b/pyodide).
"""

from src.backend.core.ai.errors import (
    WorkspaceQuotaExceededError,
    WorkspaceTTLExpiredError,
)
from src.backend.core.ai.fs_facade import AIFsFacade
from src.backend.core.ai.workspace_manager import AIWorkspaceManager, WorkspaceHandle

__all__ = (
    "AIFsFacade",
    "AIWorkspaceManager",
    "WorkspaceHandle",
    "WorkspaceQuotaExceededError",
    "WorkspaceTTLExpiredError",
)
