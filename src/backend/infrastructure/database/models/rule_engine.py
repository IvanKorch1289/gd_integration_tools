"""ORM-модель таблицы ``rule_engine_rulesets`` (Wave [wave:s8/k3-rule-engine-finale]).

Хранит YAML-тело ruleset'а для DSL-шага ``evaluate_rules`` с поддержкой
версионирования и tenant-scope. Загружается через
:class:`SQLRuleEngineRepository` (см.
``src/backend/infrastructure/repositories/rule_engine_repository.py``)
и кэшируется в :class:`RuleEngineRegistry`.

Использует собственный :class:`DeclarativeBase` (а не общий
:class:`BaseModel`), чтобы избежать включения SQLAlchemy-Continuum
versioning для конфигурационной таблицы — версионирование ruleset'а
обеспечивается явной колонкой ``version`` в составном ключе.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

__all__ = ("RuleEngineBase", "RuleEngineRulesetORM")


class RuleEngineBase(DeclarativeBase):
    """Изолированный DeclarativeBase для таблиц rule-engine.

    Не пересекается с :class:`BaseModel` и не подключает
    SQLAlchemy-Continuum: персистентность ruleset'ов не нуждается в
    транзакционном версионировании на уровне БД.
    """


class RuleEngineRulesetORM(RuleEngineBase):
    """Запись ruleset'а rule-engine.

    Колонки:
        id: PK serial.
        name: Имя ruleset'а; уникально вместе с ``version`` и ``tenant_id``.
        version: Версионная метка (произвольная строка).
        yaml_body: Сырое YAML-тело ruleset'а.
        enabled: Флаг активности (``False`` исключает запись из
            :meth:`RuleEngineRepository.list_active`).
        tenant_id: Опц. tenant scope; ``None`` — глобальный ruleset.
        created_at: Время создания (UTC).
        updated_at: Время последнего обновления (UTC).
    """

    __tablename__ = "rule_engine_rulesets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(length=128), nullable=False)
    version: Mapped[str] = mapped_column(
        String(length=64), nullable=False, default="1"
    )
    yaml_body: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    tenant_id: Mapped[str | None] = mapped_column(
        String(length=128), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "name",
            "version",
            "tenant_id",
            name="uq_rule_engine_rulesets_name_version_tenant",
        ),
    )
