"""AI subsystem — Safety (V15 R-V15-4 + W22) + Platform (V22.4 S25-S27).

Контракты Safety (V15):

* :class:`AIWorkspaceManager` — выдаёт изолированные writable-каталоги
  для AI-агентов: ``${AI_WORKSPACE}/<tenant>/<session>/<artifact>``;
* :class:`AIFsFacade` — единственный санкционированный путь FS-доступа
  для AI-плагинов; ``read(path)`` через capability ``fs.read.<path>``,
  ``create_new(path, content)`` через capability ``fs.create_new.<workspace>``;
* TTL=7 дней + per-tenant quota; cleanup-loop через ``TaskRegistry``.

Контракты Platform (V22.4):

* :class:`AIGateway` (ADR-NEW-19) — единая точка входа в AI, 9-step pipeline
  (policy_resolve → sanitize → guards → render → invoke → guards →
  sanitize → audit → cost). Capability ``ai.invoke.<workflow>``.
* :class:`AIRequest` / :class:`AIResponse` — dataclasses пайплайна.
* :mod:`core.ai.policy` — декларативные :class:`AIPolicySpec` (ADR-NEW-20).

Запрещено:

* запись существующих файлов проекта;
* удаление файлов;
* прямой ``subprocess.run`` (только sandboxed e2b/pyodide);
* прямые вызовы ``litellm.completion()`` / ``agent.run()`` в обход
  :class:`AIGateway` (после S27 closure, проверяется
  ``tools/checks/check_ai_gateway_coverage.py``).
"""

from src.backend.core.ai.errors import (
    GuardrailViolationError,
    GuardResult,
    WorkspaceQuotaExceededError,
    WorkspaceTTLExpiredError,
)
from src.backend.core.ai.fs_facade import AIFsFacade
from src.backend.core.ai.gateway import AIGateway, AIRequest, AIResponse
from src.backend.core.ai.workspace_manager import AIWorkspaceManager, WorkspaceHandle

__all__ = (
    "AIFsFacade",
    "AIGateway",
    "AIRequest",
    "AIResponse",
    "AIWorkspaceManager",
    "WorkspaceHandle",
    "GuardResult",
    "GuardrailViolationError",
    "WorkspaceQuotaExceededError",
    "WorkspaceTTLExpiredError",
)
