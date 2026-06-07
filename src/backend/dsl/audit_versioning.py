"""DSL-фасад для row-level history (обёртка над ``sqlalchemy-continuum``).

S58 W1: предоставляет высокоуровневый API для работы с историей записей,
делегируя всю работу библиотечному ``sqlalchemy-continuum``.

Архитектура:
    1. ``sqlalchemy-continuum`` уже настроен в
       ``src/backend/infrastructure/database/models/base.py``
       (``make_versioned(plugins=[ActivityPlugin, PropertyModTrackerPlugin])``).
    2. Version tables (``users_version``, ``files_version``,
       ``orderfiles_version``, ``orderkinds_version``, ``orders_version``,
       ``transaction``, ``activity``) уже созданы в init-миграции
       ``2025_03_10_1637-20036813ff7c_.py``.
    3. Этот модуль — тонкий DSL-фасад, НЕ замена continuum. Любая логика
       (versioning таблиц, transaction tracking, mod tracking) — в continuum.

Почему ФАСАД, а не custom:
    * "libraries > custom" (проектное правило);
    * continuum 1.6.0 уже работает (init migration доказывает, что
      version tables создавались при импорте моделей в 2025-03);
    * custom SQLAlchemy event listeners дублировали бы continuum API.

Использование::

    from src.backend.dsl.audit_versioning import Versioning

    history = Versioning.get_history(session, User, 42)
    Versioning.rollback(session, User, 42, transaction_id=2)
    diff = Versioning.diff(session, User, 42, tx_id_1=1, tx_id_2=3)

Контракт: все методы предполагают что ``session`` уже открыт и continuum
``configure_mappers()`` уже выполнен (в проекте — через lazy session
creation, см. ``infrastructure/database/session_manager.py``).
"""
from __future__ import annotations

from typing import Any, ClassVar

from sqlalchemy import inspect
from sqlalchemy_continuum import version_class
from sqlalchemy_continuum.exc import ClassNotVersioned

__all__ = (
    "OP_DELETE",
    "OP_INSERT",
    "OP_UPDATE",
    "Versioning",
    "VersioningError",
)

# Continuum operation types (sentinel ints из ``sqlalchemy_continuum.operation``).
# Явно пронумерованы для тестов и DSL-валидации (вместо магических чисел).
OP_INSERT = 0
OP_UPDATE = 1
OP_DELETE = 2


class VersioningError(Exception):
    """Raised when a Versioning operation fails (not found, bad input, etc.)."""


class Versioning:
    """DSL-фасад для операций с историей записей.

    Stateless namespace. Все методы принимают открытую ``Session`` и
    делегируют в ``sqlalchemy_continuum.version_class(model)``.
    """

    # Columns которые НЕ копируются при rollback (managed by continuum / ORM).
    _SKIP_COLUMNS: ClassVar[frozenset[str]] = frozenset(
        {
            "id",
            "transaction_id",
            "end_transaction_id",
            "operation_type",
            "created_at",
            "updated_at",
        }
    )

    # Columns которые ВСЕГДА показываются в diff (audit context).
    _CONTEXT_COLUMNS: ClassVar[frozenset[str]] = frozenset(
        {"id", "transaction_id", "operation_type", "end_transaction_id"}
    )

    @staticmethod
    def _version_model_or_raise(model: type):
        """Возвращает version_class(model), или VersioningError если model не versioned.

        Continuum raises ``ClassNotVersioned`` для моделей без ``__versioned__``
        (или с ``__versioned__ = {"versioning": False}``). DSL-фасад конвертирует
        это в свой собственный exception type для consistency.
        """
        try:
            return version_class(model)
        except ClassNotVersioned as e:
            raise VersioningError(
                f"{model.__name__} is not a versioned model "
                f"(set __versioned__ = {{}} on the class to enable)"
            ) from e

    @staticmethod
    def get_history(session: Any, model: type, entity_id: int | str) -> list:
        """Возвращает все версии сущности, ordered by transaction_id ASC.

        Args:
            session: Открытая SQLAlchemy session.
            model: Versioned-модель (наследник BaseModel с ``__versioned__ = {}``).
            entity_id: PK значение.

        Returns:
            list[VersionModel]: Версии (INSERT op=0, UPDATE op=1, DELETE op=2).

        Raises:
            VersioningError: Если ``model`` не versioned (``ClassNotVersioned``
                от continuum → re-raised как ``VersioningError``).
        """
        VersionModel = Versioning._version_model_or_raise(model)
        return list(
            session.query(VersionModel)
            .filter(VersionModel.id == entity_id)
            .order_by(VersionModel.transaction_id)
            .all()
        )

    @staticmethod
    def get_version(
        session: Any, model: type, entity_id: int | str, transaction_id: int
    ):
        """Возвращает конкретную версию или None.

        Args:
            session: Открытая session.
            model: Versioned-модель.
            entity_id: PK значение.
            transaction_id: Continuum transaction ID (per-INSERT/UPDATE/DELETE).
        """
        VersionModel = Versioning._version_model_or_raise(model)
        return (
            session.query(VersionModel)
            .filter_by(id=entity_id, transaction_id=transaction_id)
            .first()
        )

    @staticmethod
    def rollback(
        session: Any, model: type, entity_id: int | str, transaction_id: int
    ) -> Any:
        """Восстанавливает сущность до состояния из конкретной версии.

        ВНИМАНИЕ: rollback — это UPDATE, который continuum auto-tracks
        → создаётся НОВАЯ version row с последними значениями. Оригинальные
        "будущие" версии (после target transaction_id) остаются в истории.

        Args:
            session: Открытая session.
            model: Versioned-модель.
            entity_id: PK значение.
            transaction_id: Continuum transaction ID, к которому восстанавливаем.

        Returns:
            model instance (mutated, НЕ flushed). Caller обязан ``session.commit()``.

        Raises:
            VersioningError: Если ``entity_id`` не найден или ``transaction_id``
                не существует.
        """
        original = session.get(model, entity_id)
        if original is None:
            raise VersioningError(
                f"{model.__name__}#{entity_id} not found in current session"
            )
        target = Versioning.get_version(session, model, entity_id, transaction_id)
        if target is None:
            raise VersioningError(
                f"Version tx={transaction_id} not found for {model.__name__}#{entity_id}"
            )
        for col in inspect(model).columns:
            if col.key in Versioning._SKIP_COLUMNS:
                continue
            setattr(original, col.key, getattr(target, col.key))
        return original

    @staticmethod
    def diff(
        session: Any,
        model: type,
        entity_id: int | str,
        tx_id_1: int,
        tx_id_2: int,
    ) -> dict[str, Any]:
        """Возвращает diff между двумя версиями.

        Output format::

            {
                "entity": "User#42",
                "from_transaction": 1,
                "to_transaction": 3,
                "from_operation": "INSERT",  # OP_* → string
                "to_operation": "UPDATE",
                "changes": {
                    "username": {"old": "alice", "new": "alice2"},
                    "email": {"old": "a@x.com", "new": "a2@x.com"},
                },
            }

        Args:
            session: Открытая session.
            model: Versioned-модель.
            entity_id: PK значение.
            tx_id_1: "from" transaction_id.
            tx_id_2: "to" transaction_id.

        Returns:
            dict с entity, transactions, operation names и per-column changes.

        Raises:
            VersioningError: Если любая из версий не найдена.
        """
        v1 = Versioning.get_version(session, model, entity_id, tx_id_1)
        v2 = Versioning.get_version(session, model, entity_id, tx_id_2)
        if v1 is None or v2 is None:
            raise VersioningError(
                f"Version tx={tx_id_1 if v1 is None else tx_id_2} not found "
                f"for {model.__name__}#{entity_id}"
            )

        changes: dict[str, dict[str, Any]] = {}
        for col in inspect(model).columns:
            if col.key in Versioning._CONTEXT_COLUMNS:
                continue
            old_val = getattr(v1, col.key, None)
            new_val = getattr(v2, col.key, None)
            if old_val != new_val:
                changes[col.key] = {"old": old_val, "new": new_val}

        return {
            "entity": f"{model.__name__}#{entity_id}",
            "from_transaction": tx_id_1,
            "to_transaction": tx_id_2,
            "from_operation": Versioning._operation_name(v1.operation_type),
            "to_operation": Versioning._operation_name(v2.operation_type),
            "changes": changes,
        }

    @staticmethod
    def _operation_name(op_type: int) -> str:
        """Возвращает строковое имя операции для DSL output (вместо int sentinel)."""
        return {OP_INSERT: "INSERT", OP_UPDATE: "UPDATE", OP_DELETE: "DELETE"}.get(
            op_type, f"UNKNOWN({op_type})"
        )
