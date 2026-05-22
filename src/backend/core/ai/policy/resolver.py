"""PolicyResolver — резолверы :class:`AIPolicySpec` по workflow + tenant.

Scaffold S25 W2 (ADR-NEW-20). Полная реализация (YAML-loader,
per-tenant override, hot-reload через watchfiles, RAM-cache + Redis pub/sub
invalidation) — в Wave S25 W2.

См. docs/adr/0067-ai-policy-spec-dsl.md.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backend.core.ai.policy.spec import AIPolicySpec

__all__ = ("PolicyNotResolvedError", "PolicyResolver")


class PolicyNotResolvedError(LookupError):
    """:class:`AIGateway` поднимает при ``ai_policy_enforce=True`` и
    отсутствии подходящей :class:`AIPolicySpec` с ``required=True``.

    Attributes:
        workflow_id: workflow для которого не нашли policy.
        tenant_id: tenant_id.
    """

    def __init__(self, workflow_id: str, tenant_id: str) -> None:
        """Инициализация.

        Args:
            workflow_id: Запрошенный workflow_id.
            tenant_id: Запрошенный tenant_id.
        """
        super().__init__(
            f"AIPolicySpec не найден для workflow_id={workflow_id!r}, "
            f"tenant_id={tenant_id!r}"
        )
        self.workflow_id = workflow_id
        self.tenant_id = tenant_id


class PolicyResolver:
    """Резолверы :class:`AIPolicySpec` по ``workflow_id`` + ``tenant_id``.

    Lookup-порядок:

    1. ``extensions/<plugin>/ai_policies/<name>.policy.yaml`` —
       per-plugin override (если ``tenant_pattern`` matches);
    2. ``ai_policies/<name>.policy.yaml`` — global default;
    3. fallback: :class:`AIPolicySpec` с ``name="default"`` и ``required=False``
       (no-op pipeline).

    Scaffold S25 W2: метод :meth:`resolve` возвращает ``None`` (no policy)
    до полной реализации YAML-loader'а.

    Args:
        roots: Список путей-корней для поиска ``*.policy.yaml`` (порядок
            определяет приоритет).
    """

    def __init__(self, roots: list[Path] | None = None) -> None:
        """Инициализация.

        Args:
            roots: Список корней (default: пустой; реальные пути инжектируются
                composition root'ом в Wave S25 W2).
        """
        self._roots: list[Path] = roots or []
        self._cache: dict[tuple[str, str], "AIPolicySpec"] = {}

    async def resolve(
        self, workflow_id: str, tenant_id: str
    ) -> "AIPolicySpec | None":
        """Резолвер :class:`AIPolicySpec` по ``workflow_id`` + ``tenant_id``.

        Args:
            workflow_id: Идентификатор workflow (``"credit_check"``).
            tenant_id: Идентификатор tenant (``"credit_premium"``).

        Returns:
            Resolved :class:`AIPolicySpec` или ``None``, если подходящая
            политика не найдена (caller сам решает что делать — :class:`AIGateway`
            при ``ai_policy_enforce=True`` поднимает :class:`PolicyNotResolvedError`).

        Notes:
            Scaffold S25 W2 — всегда возвращает ``None``. Полная реализация
            (YAML loader + per-tenant override + cache) — Wave S25 W2.
        """
        del workflow_id, tenant_id
        return None

    def _matches(self, pattern: str, value: str) -> bool:
        """Glob-сопоставление pattern → value.

        Args:
            pattern: ``fnmatch``-pattern (``"credit_check*"``, ``"premium*"``).
            value: Конкретное значение (``"credit_check_v2"``,
                ``"credit_premium"``).

        Returns:
            ``True`` если ``value`` подходит под ``pattern``.
        """
        return fnmatch.fnmatchcase(value, pattern)

    def reload(self) -> None:
        """Сбросить кэш и перечитать ``*.policy.yaml``.

        Используется hot-reload через ``watchfiles.awatch`` (Wave B).
        Scaffold-реализация: только очистка cache.
        """
        self._cache.clear()
