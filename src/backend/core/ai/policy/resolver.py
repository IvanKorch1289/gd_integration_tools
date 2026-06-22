"""PolicyResolver — резолверы :class:`AIPolicySpec` по workflow + tenant.

Sprint 25 W2 (ADR-NEW-20). Полная реализация YAML-loader + per-tenant override
+ RAM-cache + glob-matcher. Hot-reload через :meth:`reload` (вызывается
из ``watchfiles.awatch``, Wave B).

См. docs/adr/0067-ai-policy-spec-dsl.md.
"""

from __future__ import annotations
from src.backend.core.logging import get_logger


import fnmatch
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from src.backend.core.ai.policy.spec import AIPolicySpec
from src.backend.core.ai.policy.specificity import find_specific_match

logger = get_logger(__name__)


if TYPE_CHECKING:
    from collections.abc import Iterator

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


class PolicyLoadError(ValueError):
    """Ошибка при загрузке YAML-файла политики.

    Поднимается, если файл `*.policy.yaml` повреждён (некорректный YAML)
    или не соответствует :class:`AIPolicySpec` Pydantic-схеме.

    Attributes:
        path: Путь к проблемному файлу.
        reason: Текст ошибки из yaml/pydantic.
    """

    def __init__(self, path: Path, reason: str) -> None:
        """Инициализация.

        Args:
            path: Путь к проблемному файлу.
            reason: Текст ошибки.
        """
        super().__init__(f"Не удалось загрузить {path}: {reason}")
        self.path = path
        self.reason = reason


class PolicyResolver:
    """Резолверы :class:`AIPolicySpec` по ``workflow_id`` + ``tenant_id``.

    Lookup-порядок (приоритет от высокого к низкому):

    1. Per-plugin overrides (если ``roots`` содержит
       ``extensions/<plugin>/ai_policies/``).
    2. Global ``ai_policies/<name>.policy.yaml``.
    3. Fallback: ``None`` (caller — :class:`AIGateway` — решает что делать).

    Алгоритм :meth:`resolve`:

    * Сначала проверяется RAM-cache по ключу ``(workflow_id, tenant_id)``.
    * Если нет — итерация по загруженным policies в порядке `_roots`:
      первый match по `workflow_pattern` + `tenant_pattern` побеждает.
    * Match через :func:`fnmatch.fnmatchcase` (case-sensitive glob).

    Args:
        roots: Список путей-корней (директорий) с ``*.policy.yaml``.
            Порядок ВАЖЕН: первый match побеждает (используется для
            per-tenant override через extensions/).

    Пример::

        resolver = PolicyResolver(
            roots=[Path("extensions/credit/ai_policies"), Path("ai_policies")]
        )
        policy = await resolver.resolve("credit_check", "credit_premium")
    """

    def __init__(self, roots: list[Path] | None = None) -> None:
        """Инициализация.

        Args:
            roots: Список корней для сканирования ``*.policy.yaml``.
                Default: пустой; реальные пути инжектируются composition root'ом.
        """
        self._roots: list[Path] = roots or []
        self._cache: dict[tuple[str, str], AIPolicySpec] = {}
        self._policies: list[AIPolicySpec] | None = None
        self._specific_cache: dict[tuple[str, str], AIPolicySpec | None] = {}

    async def resolve(self, workflow_id: str, tenant_id: str) -> AIPolicySpec | None:
        """Резолвер :class:`AIPolicySpec` по ``workflow_id`` + ``tenant_id``.

        Args:
            workflow_id: Идентификатор workflow (``"credit_check"``).
            tenant_id: Идентификатор tenant (``"credit_premium"``).

        Returns:
            Resolved :class:`AIPolicySpec` или ``None``, если подходящая
            политика не найдена. Caller (обычно :class:`AIGateway`) при
            ``ai_policy_enforce=True`` поднимает
            :class:`PolicyNotResolvedError`.
        """
        cache_key = (workflow_id, tenant_id)
        if cache_key in self._cache:
            return self._cache[cache_key]

        if self._policies is None:
            self._policies = list(self._load_all())

        for policy in self._policies:
            if self._matches(policy.workflow_pattern, workflow_id) and self._matches(
                policy.tenant_pattern, tenant_id
            ):
                self._cache[cache_key] = policy
                return policy
        return None

    async def resolve_specific(
        self, workflow_id: str, tenant_id: str
    ) -> AIPolicySpec | None:
        """S77 W3 — specificity-based resolver (P0-C improvement).

        В отличие от :meth:`resolve` (first match wins), этот method
        выбирает MOST specific match по pattern specificity:

        * tenant_pattern более specific (напр. ``"premium_*"`` vs
          ``"*"``) → wins
        * workflow_pattern более specific (напр.
          ``"credit_check_v2"`` vs ``"credit_*"``) → wins
        * Ties → list order (stable)

        Use case: multi-tenant deployments с policy override layers
        (global → premium → specific user).

        Args:
            workflow_id: Идентификатор workflow.
            tenant_id: Идентификатор tenant.

        Returns:
            Most specific :class:`AIPolicySpec` или ``None``.

        Note:
            Uses SEPARATE cache (``_specific_cache``) чтобы не
            conflict с :meth:`resolve` cache (callers могут
            использовать оба в разных contexts).
        """
        cache_key = (workflow_id, tenant_id)
        if hasattr(self, "_specific_cache") and cache_key in self._specific_cache:
            return self._specific_cache[cache_key]

        if self._policies is None:
            self._policies = list(self._load_all())

        result = find_specific_match(self._policies, workflow_id, tenant_id)
        if not hasattr(self, "_specific_cache"):
            self._specific_cache = {}
        self._specific_cache[cache_key] = result
        return result

    def reload(self) -> None:
        """Сбросить кэш и пометить policies для повторной загрузки.

        Используется hot-reload через ``watchfiles.awatch`` (Wave B)
        или административным endpoint'ом.
        """
        self._cache.clear()
        if hasattr(self, "_specific_cache"):
            self._specific_cache.clear()
        self._policies = None

    def list_policies(self) -> list[AIPolicySpec]:
        """Список всех загруженных policies (для admin UI / debug).

        Returns:
            Snapshot загруженных :class:`AIPolicySpec` в порядке roots.
        """
        if self._policies is None:
            self._policies = list(self._load_all())
        return list(self._policies)

    def _matches(self, pattern: str, value: str) -> bool:
        """Glob-сопоставление pattern → value через :func:`fnmatch.fnmatchcase`.

        Args:
            pattern: glob-pattern (``"credit_check*"``, ``"premium*"``,
                ``"*"``).
            value: Конкретное значение.

        Returns:
            ``True`` если ``value`` подходит под ``pattern``.
        """
        return fnmatch.fnmatchcase(value, pattern)

    def _load_all(self) -> Iterator[AIPolicySpec]:
        """Сканирует все roots и yields загруженные политики.

        Yields:
            :class:`AIPolicySpec` в порядке roots (приоритет высокий → низкий).

        Raises:
            PolicyLoadError: При невалидном YAML или несоответствии схеме.
        """
        for root in self._roots:
            if not root.exists() or not root.is_dir():
                continue
            for yaml_path in sorted(root.glob("*.policy.yaml")):
                yield self._load_one(yaml_path)

    def _load_one(self, path: Path) -> AIPolicySpec:
        """Загружает и валидирует одну :class:`AIPolicySpec` из YAML.

        Args:
            path: Путь к файлу ``<name>.policy.yaml``.

        Returns:
            Validated :class:`AIPolicySpec`.

        Raises:
            PolicyLoadError: При ошибке парсинга YAML или Pydantic validation.
        """
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError) as exc:
            raise PolicyLoadError(path, f"YAML parse error: {exc}") from exc
        try:
            return AIPolicySpec.model_validate(raw)
        except (TypeError, ValueError) as exc:
            raise PolicyLoadError(
                path, f"AIPolicySpec validation error: {exc}"
            ) from exc
