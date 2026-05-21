"""YAML round-trip API для :class:`WorkflowDeclaration` (Sprint 4 K3 W2).

Назначение:
    Сериализация/десериализация workflow-деклараций в YAML с сохранением
    структуры (ruamel.yaml round-trip) и diff-сравнение двух деклараций
    для миграционного UI и audit-трейла.

Контракт V18.1:
    * Default-OFF под feature-flag ``workflow_yaml_round_trip``.
    * ``from_yaml()`` отказывается работать при выключенном флаге, чтобы
      исключить случайное ослабление контракта в проде до staging-smoke.
    * ``to_yaml()`` работает всегда — экспорт не меняет runtime-поведение.

Public API:
    * :func:`to_yaml` — :class:`WorkflowDeclaration` → YAML-строка.
    * :func:`from_yaml` — YAML-строка → :class:`WorkflowDeclaration`.
    * :class:`WorkflowDiff` — структура diff двух деклараций.
    * :func:`diff` — сравнение двух деклараций по шагам и версии.
    * :class:`FeatureDisabledError` — exception при выключенном флаге.

Зависимости:
    ruamel.yaml>=0.18.0 (round-trip preservation comments/formatting).
"""

from __future__ import annotations

import io
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from ruamel.yaml import YAML

from src.backend.dsl.workflow.spec import WorkflowDeclaration

__all__ = ("FeatureDisabledError", "WorkflowDiff", "diff", "from_yaml", "to_yaml")


class FeatureDisabledError(RuntimeError):
    """Выбрасывается при попытке использовать API под выключенным flag-ом.

    Используется ``from_yaml()`` для default-OFF контракта
    ``feature_flags.workflow_yaml_round_trip``.
    """


def _make_yaml() -> YAML:
    """Сконструировать round-trip ``YAML``-инстанс с проектными настройками.

    Returns:
        ``ruamel.yaml.YAML`` (``typ="rt"``), сохраняющий порядок ключей,
        с отключённым flow-style по умолчанию и шириной 120 для
        читаемости diff-снапшотов.
    """
    yaml = YAML(typ="rt")
    yaml.default_flow_style = False
    yaml.allow_unicode = True
    yaml.width = 120
    yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml


def to_yaml(decl: WorkflowDeclaration) -> str:
    """Сериализовать :class:`WorkflowDeclaration` в YAML-строку.

    Использует ``model_dump(mode="json")`` для JSON-совместимой
    презентации (Pydantic discriminator резолвится в строки), затем
    dump через ruamel.yaml round-trip parser.

    Args:
        decl: Декларация workflow для сериализации.

    Returns:
        YAML-строка с UTF-8 контентом, готовая к записи в
        ``workflows/<name>.workflow.yaml``.
    """
    payload = decl.model_dump(mode="json")
    yaml = _make_yaml()
    buffer = io.StringIO()
    yaml.dump(payload, buffer)
    return buffer.getvalue()


def from_yaml(yaml_text: str) -> WorkflowDeclaration:
    """Десериализовать YAML-текст в :class:`WorkflowDeclaration`.

    Lazy-проверяет feature-flag ``workflow_yaml_round_trip``: при выключенном
    флаге выбрасывает :class:`FeatureDisabledError` без чтения YAML — это
    защищает от случайной обвязки на disabled-API в проде.

    Args:
        yaml_text: YAML-строка с декларацией workflow.

    Returns:
        Валидированная :class:`WorkflowDeclaration`.

    Raises:
        FeatureDisabledError: Если ``workflow_yaml_round_trip`` выключен.
        pydantic.ValidationError: Если YAML не соответствует схеме
            декларации (неизвестный ``type``, пустой ``steps`` и т. п.).
    """
    from src.backend.core.config.features import feature_flags

    if not feature_flags.workflow_yaml_round_trip:
        raise FeatureDisabledError(
            "Feature workflow_yaml_round_trip disabled. "
            "Установите FEATURE_WORKFLOW_YAML_ROUND_TRIP=true для активации."
        )

    yaml = _make_yaml()
    data: Any = yaml.load(yaml_text)
    return WorkflowDeclaration.model_validate(data)


class WorkflowDiff(BaseModel):
    """Структурный diff двух :class:`WorkflowDeclaration` по шагам и версии.

    Используется в migration-UI и audit-трейле для отображения изменений
    между ревизиями workflow. Шаги идентифицируются по ``name`` для
    activity и по ``signal_name``/``predicate`` для прочих шагов
    (см. :func:`_step_identity`).

    Attributes:
        added_steps: Идентификаторы шагов, появившихся в ``decl_b``.
        removed_steps: Идентификаторы шагов, удалённых из ``decl_a``.
        modified_steps: Идентификаторы шагов с одинаковым ``identity``,
            но различающимся содержимым (args/timeout/retry/etc).
        version_changed: ``(old_version, new_version)`` либо ``None``,
            если ``decl_a.version == decl_b.version``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    added_steps: tuple[str, ...] = Field(
        default=(), description="Идентификаторы шагов, добавленных в decl_b."
    )
    removed_steps: tuple[str, ...] = Field(
        default=(), description="Идентификаторы шагов, удалённых из decl_a."
    )
    modified_steps: tuple[str, ...] = Field(
        default=(), description="Идентификаторы изменённых шагов."
    )
    version_changed: tuple[str, str] | None = Field(
        default=None,
        description="(version_a, version_b) либо None если версии совпадают.",
    )


def _step_identity(step: Any) -> str:
    """Получить уникальный идентификатор шага для diff-сравнения.

    Идентификатор включает префикс типа, чтобы шаги разных типов с
    совпадающими именами (например ``activity:approve`` vs
    ``wait_signal:approve``) не схлопывались.

    Args:
        step: Любой шаг workflow (ActivityDeclaration, SagaDeclaration,
            SignalWaitDeclaration, SleepDeclaration, SensorDeclaration).

    Returns:
        Строковый идентификатор формата ``<type>:<name>``.
    """
    step_type = step.type
    match step_type:
        case "activity":
            return f"activity:{step.name}"
        case "saga":
            forward_names = ",".join(a.name for a in step.forward)
            return f"saga:[{forward_names}]"
        case "wait_signal":
            return f"wait_signal:{step.signal_name}"
        case "sleep":
            return f"sleep:{step.duration_s}"
        case "sensor":
            return f"sensor:{step.predicate}"
        case _:
            return f"{step_type}:unknown"


def diff(decl_a: WorkflowDeclaration, decl_b: WorkflowDeclaration) -> WorkflowDiff:
    """Сравнить две декларации workflow и вернуть структурный :class:`WorkflowDiff`.

    Алгоритм:
        1. Построить идентификаторы шагов через :func:`_step_identity`.
        2. ``added`` = identities в B, отсутствующие в A.
        3. ``removed`` = identities в A, отсутствующие в B.
        4. ``modified`` = identities в пересечении, но содержимое шага
           (``model_dump``) различается.
        5. ``version_changed`` = ``(a.version, b.version)`` при отличии.

    Args:
        decl_a: Базовая (старая) декларация.
        decl_b: Сравниваемая (новая) декларация.

    Returns:
        Иммутабельный :class:`WorkflowDiff` с tuple-полями.
    """
    a_ids = {_step_identity(s): s for s in decl_a.steps}
    b_ids = {_step_identity(s): s for s in decl_b.steps}

    added = tuple(sorted(set(b_ids) - set(a_ids)))
    removed = tuple(sorted(set(a_ids) - set(b_ids)))

    modified: list[str] = []
    for ident in sorted(set(a_ids) & set(b_ids)):
        if a_ids[ident].model_dump() != b_ids[ident].model_dump():
            modified.append(ident)

    version_changed: tuple[str, str] | None = None
    if decl_a.version != decl_b.version:
        version_changed = (decl_a.version, decl_b.version)

    return WorkflowDiff(
        added_steps=added,
        removed_steps=removed,
        modified_steps=tuple(modified),
        version_changed=version_changed,
    )
