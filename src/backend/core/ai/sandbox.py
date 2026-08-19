"""CodeSandbox protocol — изолированное выполнение AI-сгенерированного кода.

V15 R-V15-4: прямой ``subprocess.run`` в плагинах запрещён; код
исполняется в e2b/pyodide-sandbox через :class:`CodeSandbox`. Capability
``code.execute`` (см. ``capabilities/vocabulary.py``) проверяется на
runtime через capability_check callback.

При отсутствии настроенного провайдера (``E2B_API_KEY`` не задан, либо
e2b-code-interpreter не установлен) регистрируется :class:`NoOpSandbox`,
который явно отказывается выполнять код — это предпочтительнее, чем
fallback на subprocess.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from src.backend.core.ai.workspace_manager import WorkspaceHandle


class BudgetExceededError(Exception):
    """Raised when agent token/cost budget is exhausted.

    Attributes:
        budget_type: Type of budget exceeded (``token`` or ``cost``).
        limit: The budget limit that was exceeded.
        consumed: Actual consumption that triggered the error.

    """

    def __init__(self, *, budget_type: str, limit: float, consumed: float) -> None:
        self.budget_type = budget_type
        self.limit = limit
        self.consumed = consumed
        super().__init__(
            f"{budget_type} budget exceeded: consumed {consumed} > limit {limit}"
        )


__all__ = ("BudgetExceededError", "CodeSandbox", "NoOpSandbox", "SandboxResult")


@dataclass(frozen=True, slots=True)
class SandboxResult:
    """Итог исполнения кода в sandbox.

    Attributes:
        stdout: STDOUT процесса.
        stderr: STDERR процесса.
        exit_code: 0 — успех; иной код — ошибка исполнения.
        artifacts: Сгенерированные файлы как ``{relative_path: bytes}``.
            Caller ответственен за их сохранение через
            :class:`AIFsFacade.create_new` в выданный workspace.

    """

    stdout: str
    stderr: str
    exit_code: int
    artifacts: Mapping[str, bytes] = field(default_factory=dict)


class CodeSandbox(Protocol):
    """Контракт sandbox для AI-сгенерированного кода."""

    async def run(
        self,
        code: str,
        *,
        timeout_s: float = 30.0,
        token_budget: int = 4096,
        cost_budget_usd: float = 0.10,
        files: Mapping[str, bytes] | None = None,
        workspace: WorkspaceHandle | None = None,
    ) -> SandboxResult:
        """Выполнить ``code`` в изолированной среде.

        Args:
            code: Тело Python-скрипта.
            timeout_s: Жёсткий лимит времени исполнения (секунды).
            token_budget: Максимальное количество токенов для агента.
                При превышении выбрасывается ``BudgetExceededError``.
            cost_budget_usd: Максимальная стоимость исполнения (USD).
                При превышении выбрасывается ``BudgetExceededError``.
            files: Опц. дополнительные файлы для пробрасывания внутрь
                sandbox'а в момент старта (``{relative_path: bytes}``).
            workspace: Опц. handle, в который sandbox обязан сохранить
                итоговые artifacts через ``AIFsFacade.create_new``.

        Returns:
            :class:`SandboxResult`.

        Raises:
            BudgetExceededError: Превышен token или cost budget.
            CapabilityDeniedError: Caller не задекларировал ``code.execute``.
            RuntimeError: Sandbox-провайдер недоступен (NoOp).

        """
        ...


class NoOpSandbox:
    """Явный отказ исполнять код — используется при отсутствии E2B/pyodide.

    Защита от ситуации, когда AI-плагин полагает, что sandbox присутствует,
    и пытается запустить код. Без этого NoOp код выполнялся бы прямым
    ``subprocess.run`` — что нарушает V15 R-V15-4.
    """

    async def run(
        self,
        code: str,
        *,
        timeout_s: float = 30.0,
        token_budget: int = 4096,
        cost_budget_usd: float = 0.10,
        files: Mapping[str, bytes] | None = None,
        workspace: WorkspaceHandle | None = None,
    ) -> SandboxResult:
        """Заглушка sandbox-провайдера.

        Всегда выбрасывает ``RuntimeError`` с инструкцией по установке
        e2b-code-interpreter. Используется по умолчанию, если ни один
        провайдер не сконфигурирован — гарантирует, что код НЕ будет
        исполняться через ``subprocess.run`` (V15 R-V15-4).

        Args:
            code: Исходный код Python для исполнения (игнорируется).
            timeout_s: Максимальное время исполнения (игнорируется).
            token_budget: Лимит токенов (игнорируется).
            cost_budget_usd: Лимит стоимости (игнорируется).
            files: Дополнительные файлы для контекста (игнорируется).
            workspace: Handle на workspace для AI Safety (игнорируется).

        Raises:
            RuntimeError: Всегда, если не подключён реальный провайдер.

        """
        raise RuntimeError(
            "CodeSandbox не сконфигурирован: установите e2b-code-interpreter "
            "и задайте E2B_API_KEY (или подключите альтернативный sandbox-провайдер)."
        )
