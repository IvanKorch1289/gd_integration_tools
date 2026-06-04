"""Workflow versioning + Temporal patched-API integration.

Sprint 7 / K3 (``[wave:s7/k3-workflow-versioning]``):
    Реестр версий workflow с semver-парсингом + лёгкая обёртка над
    Temporal ``workflow.patched(patch_id)`` API для безопасной миграции
    между мажорными версиями.

Архитектура:
    * :class:`WorkflowVersion` — dataclass (semver MAJOR.MINOR.PATCH).
    * :class:`WorkflowVersionRegistry` — in-memory map ``workflow_id ->
      list[WorkflowVersion]``; lookup default-версии + register.
    * :func:`workflow_versioned` — декоратор для активити/workflow,
      привязывающий semver к функции.
    * :func:`patched` — обёртка над ``temporalio.workflow.patched`` с
      lazy-import (dev_light без temporalio SDK).

Strict-mode (под feature flag ``workflow_versioning_strict``):
    * register отклоняет конфликт мажор-версий, если новая версия имеет
      ``default_version=True`` и уже зарегистрирована несовместимая
      default-версия.

References:
    * temporalio Python SDK: https://docs.temporal.io/develop/python/versioning
    * Plan V15 R-V15-9 (AI-функции через Workflow DSL), Sprint 7 K3.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

__all__ = (
    "WorkflowVersion",
    "WorkflowVersionRegistry",
    "get_global_registry",
    "patched",
    "workflow_versioned",
)

_SEMVER_RE = re.compile(r"^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)$")

F = TypeVar("F", bound=Callable[..., Any])


@dataclass(frozen=True, slots=True)
class WorkflowVersion:
    """Декларация semver-версии workflow.

    Attributes:
        workflow_id: Уникальный идентификатор workflow (например
            ``credit.assessment_v2``).
        major: Мажорная версия (несовместимые API изменения).
        minor: Минорная версия (обратимо-совместимые фичи).
        patch: Patch-версия (bug-fix).
        default_version: Является ли версия default для workflow_id.
            При lookup без явного указания версии возвращается default.
    """

    workflow_id: str
    major: int
    minor: int
    patch: int = 0
    default_version: bool = True

    def __post_init__(self) -> None:
        """Валидация: компоненты semver должны быть >= 0."""
        if self.major < 0 or self.minor < 0 or self.patch < 0:
            raise ValueError(
                f"semver-компоненты должны быть >= 0, получено: "
                f"{self.major}.{self.minor}.{self.patch}"
            )

    @classmethod
    def parse(
        cls, workflow_id: str, version: str, *, default_version: bool = True
    ) -> WorkflowVersion:
        """Создать ``WorkflowVersion`` из строки ``MAJOR.MINOR.PATCH``.

        Args:
            workflow_id: ID workflow.
            version: Строка вида ``"1.2.3"``.
            default_version: Флаг default-версии.

        Returns:
            Заполненный ``WorkflowVersion``.

        Raises:
            ValueError: Если ``version`` не соответствует semver-формату.
        """
        m = _SEMVER_RE.match(version)
        if m is None:
            raise ValueError(
                f"некорректная semver-строка {version!r}; ожидается MAJOR.MINOR.PATCH"
            )
        return cls(
            workflow_id=workflow_id,
            major=int(m["major"]),
            minor=int(m["minor"]),
            patch=int(m["patch"]),
            default_version=default_version,
        )

    @property
    def semver(self) -> str:
        """Строковое представление semver (``"1.2.3"``)."""
        return f"{self.major}.{self.minor}.{self.patch}"

    def is_compatible_with(self, other: WorkflowVersion) -> bool:
        """Проверка совместимости: одинаковый workflow_id + major."""
        return self.workflow_id == other.workflow_id and self.major == other.major


@dataclass
class WorkflowVersionRegistry:
    """In-memory реестр версий workflow.

    Используется CLI (``manage.py workflow version``) и runtime для
    выбора default-версии при старте workflow без explicit version.

    Attributes:
        versions: Список всех зарегистрированных версий.
    """

    versions: list[WorkflowVersion] = field(default_factory=list)

    def register(self, version: WorkflowVersion) -> None:
        """Зарегистрировать версию workflow.

        В strict-mode (feature flag ``workflow_versioning_strict``)
        отклоняет регистрацию default-версии при наличии другой
        default-версии с несовместимым major.

        Args:
            version: Версия для регистрации.

        Raises:
            ValueError: В strict-mode при конфликте major-default.
        """
        if version.default_version:
            try:
                from src.backend.core.config.features import feature_flags

                strict = bool(
                    getattr(feature_flags, "workflow_versioning_strict", False)
                )
            except Exception as _:
                strict = False

            if strict:
                existing_default = next(
                    (
                        v
                        for v in self.versions
                        if v.workflow_id == version.workflow_id
                        and v.default_version
                        and v.major != version.major
                    ),
                    None,
                )
                if existing_default is not None:
                    raise ValueError(
                        f"strict-mode: конфликт default-version для "
                        f"{version.workflow_id!r}: уже зарегистрирована "
                        f"v{existing_default.semver} (major={existing_default.major}), "
                        f"новая v{version.semver} (major={version.major}) "
                        f"несовместима"
                    )

            # Снимаем флаг default с предыдущей default-версии того же major.
            self.versions = [
                v
                if not (
                    v.workflow_id == version.workflow_id
                    and v.major == version.major
                    and v.default_version
                )
                else WorkflowVersion(
                    workflow_id=v.workflow_id,
                    major=v.major,
                    minor=v.minor,
                    patch=v.patch,
                    default_version=False,
                )
                for v in self.versions
            ]

        self.versions.append(version)

    def get_default(self, workflow_id: str) -> WorkflowVersion | None:
        """Найти default-версию для workflow_id (если есть)."""
        return next(
            (
                v
                for v in self.versions
                if v.workflow_id == workflow_id and v.default_version
            ),
            None,
        )

    def history(self, workflow_id: str) -> list[WorkflowVersion]:
        """Все зарегистрированные версии workflow_id (сортировано по semver)."""
        items = [v for v in self.versions if v.workflow_id == workflow_id]
        return sorted(items, key=lambda v: (v.major, v.minor, v.patch))

    def all_workflow_ids(self) -> list[str]:
        """Список всех уникальных workflow_id в реестре."""
        return sorted({v.workflow_id for v in self.versions})

    def pin_default(self, workflow_id: str, *, semver: str) -> WorkflowVersion:
        """Sprint 12 K3 W8 — назначить указанную версию как default.

        Снимает default-флаг с других версий того же ``workflow_id``,
        ищет версию с ``semver`` в registry и помечает её default.

        Args:
            workflow_id: workflow ID.
            semver: версия (``X.Y.Z`` или ``X.Y``).

        Returns:
            Обновлённая :class:`WorkflowVersion` с ``default_version=True``.

        Raises:
            ValueError: если версия не найдена в registry.
        """
        history = self.history(workflow_id)
        target = next((v for v in history if v.semver == semver), None)
        if target is None:
            raise ValueError(
                f"Workflow {workflow_id!r}: версия {semver!r} не найдена. "
                f"Доступно: {[v.semver for v in history]}"
            )

        updated_target = WorkflowVersion(
            workflow_id=target.workflow_id,
            major=target.major,
            minor=target.minor,
            patch=target.patch,
            default_version=True,
        )

        new_versions: list[WorkflowVersion] = []
        for v in self.versions:
            if v.workflow_id != workflow_id:
                new_versions.append(v)
                continue
            if v.major != target.major:
                new_versions.append(v)
                continue
            if (v.major, v.minor, v.patch) == (
                target.major,
                target.minor,
                target.patch,
            ):
                new_versions.append(updated_target)
            else:
                new_versions.append(
                    WorkflowVersion(
                        workflow_id=v.workflow_id,
                        major=v.major,
                        minor=v.minor,
                        patch=v.patch,
                        default_version=False,
                    )
                )

        self.versions = new_versions
        return updated_target

    def rollback(self, workflow_id: str) -> WorkflowVersion | None:
        """Sprint 12 K3 W8 — откатить default на предыдущую версию.

        Ищет текущую default-версию + предыдущую (по semver). Если есть
        previous — устанавливает её default. Возвращает новую default-версию
        или ``None`` если предыдущей нет.
        """
        current = self.get_default(workflow_id)
        if current is None:
            return None

        history = self.history(workflow_id)
        try:
            idx = history.index(current)
        except ValueError:
            return None
        if idx == 0:
            return None

        previous = history[idx - 1]
        return self.pin_default(workflow_id, semver=previous.semver)


# Глобальный реестр процесса.
_REGISTRY = WorkflowVersionRegistry()


def get_global_registry() -> WorkflowVersionRegistry:
    """Доступ к глобальному WorkflowVersionRegistry процесса."""
    return _REGISTRY


def workflow_versioned(
    version: str, *, default_version: bool = True
) -> Callable[[F], F]:
    """Декоратор для пометки workflow-функции semver-версией.

    Регистрирует версию в глобальном :class:`WorkflowVersionRegistry`
    при импорте модуля. Имя workflow берётся из ``func.__name__``.

    Args:
        version: semver-строка ``MAJOR.MINOR.PATCH``.
        default_version: Является ли версия default.

    Example::

        @workflow_versioned(version="1.0.0")
        def credit_assessment(ctx):
            ...

    Returns:
        Декоратор, не модифицирующий поведение функции (только метаданные).
    """

    def decorator(func: F) -> F:
        workflow_id = func.__name__
        wv = WorkflowVersion.parse(
            workflow_id, version, default_version=default_version
        )
        _REGISTRY.register(wv)
        # Метаданные для интроспекции (manage.py / dashboards).
        func.__workflow_version__ = wv  # type: ignore[attr-defined]
        return func

    return decorator


def patched(patch_id: str) -> bool:
    """Lazy-обёртка над ``temporalio.workflow.patched(patch_id)``.

    Безопасна для dev_light (без temporalio SDK). Если SDK не
    установлен — возвращает False (новая версия кода).

    Использовать **только внутри** ``@workflow.defn``-функций для
    миграции между мажорными версиями workflow:

    .. code-block:: python

        @workflow.defn
        async def my_wf():
            if patched("v2-changes"):
                # новая логика
                ...
            else:
                # legacy
                ...

    Args:
        patch_id: Идентификатор патча (обычно семантический slug).

    Returns:
        ``True`` если Temporal-runtime знает этот патч (новая ветка
        кода), ``False`` если запущена legacy-версия (replay).
    """
    try:
        from temporalio import workflow as temporal_workflow
    except ImportError:
        return False

    try:
        return bool(temporal_workflow.patched(patch_id))
    except Exception as _:
        # Вызов вне workflow-контекста — Temporal бросает RuntimeError.
        # Для dryrun / unit-тестов возвращаем False (legacy ветка).
        return False
