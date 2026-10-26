"""Репозиторий SQLAlchemy — точка входа для работы с БД.

Cycle 172 (MEDIUM-13): класс был God-object'ом — 491 LOC и 11 публичных
методов (порог проекта: >300 строк, >10 методов). Он разбит на семейные
модули:

* ``helpers.py`` — ``RepositoryHelper`` (прежний вложенный ``HelperMethods``);
* ``crud_mixin.py`` — ``CRUDMixin`` (get / get_paginated / count /
  first_or_last / add / bulk_create / update / delete);
* ``versioning_mixin.py`` — ``VersioningMixin`` (get_all_versions /
  get_latest_version / restore_to_version).

**Публичное имя ``SQLAlchemyRepository`` сохранено**, а вложенный атрибут
``SQLAlchemyRepository.HelperMethods`` остаётся доступен — его наследует
``OrderRepository``
(``extensions/core_entities/orders/repositories/orders.py``).
"""

from __future__ import annotations

from src.backend.core.domain.models.base import BaseModel
from src.backend.infrastructure.repositories.base.crud_mixin import CRUDMixin
from src.backend.infrastructure.repositories.base.helpers import RepositoryHelper
from src.backend.infrastructure.repositories.base.versioning_mixin import (
    VersioningMixin,
)

__all__ = ("SQLAlchemyRepository",)


class SQLAlchemyRepository[ConcreteTable: BaseModel](
    CRUDMixin[ConcreteTable],
    VersioningMixin[ConcreteTable],
):
    """Базовый класс для взаимодействия с БД с использованием SQLAlchemy.

    Реализует методы для работы с конкретной моделью таблицы.

    ``AbstractRepository`` наследуется через оба миксина, поэтому класс
    остаётся полноценным ABC-репозиторием: все абстрактные методы
    реализованы (CRUD — в ``CRUDMixin``, versioning — в ``VersioningMixin``).
    """

    #: Backward-compat alias: прежний вложенный ``HelperMethods``.
    #: Подклассы (например ``OrderRepository.HelperMethods``) наследуют
    #: его и подменяют поведение отдельных методов.
    HelperMethods = RepositoryHelper

    def __init__(self, model: type[ConcreteTable], load_joined_models: bool = False):
        self.model = model
        self.load_joined_models = load_joined_models
        self.helper = self.HelperMethods(
            model=model,
            load_joined_models=load_joined_models,
            main_class=self,
        )
