"""S107 W1 — ``core/tenancy/sqlalchemy_filter``: row-level tenant isolation.

Multi-tenancy mixin + SQLAlchemy event listener для auto-filter queries
по ``tenant_id``. Перемещено из
:mod:`src.backend.infrastructure.database.tenant_filter` (S107 W1,
TD-002 residual) для устранения layer violation: domain models
импортировали ``TenantMixin`` из ``infrastructure/``, что нарушает
V22 layer policy (extensions/core должны импортировать ТОЛЬКО
``core/`` + capability-checked фасады).

S88 W2 (V2 P0 #6): FIXED — wire на Session class (``do_orm_execute``
event), не на sessionmaker.

Wave 16 / X4 (ADR-0383): raw SQL (``text(...)``) больше не обходит
изоляцию. Для ``TextClause`` SQLAlchemy выставляет ``is_select`` /
``is_update`` / ``is_delete`` в ``False``, поэтому ORM-фильтр к нему не
применялся — ``text("SELECT * FROM docs")`` возвращал строки чужих
tenant'ов. Теперь такой запрос fail-closed: он обязан содержать явный
tenant-предикат (``tenant_id = :tenant_id`` со значением текущего
tenant'а), иначе — :class:`TenantIsolationError`.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import String, TextClause, event, inspect
from sqlalchemy.orm import Mapped, Mapper, Session, mapped_column

from src.backend.core.errors import BaseError
from src.backend.core.tenancy import get_tenant_id

__all__ = ("TenantIsolationError", "TenantMixin", "apply_tenant_filter")


class TenantIsolationError(BaseError):
    """Raw SQL нарушает tenant-изоляцию (fail-closed, ADR-0383).

    Возникает, когда raw SQL обращается к tenant-aware таблице, но не
    ограничивает выборку tenant'ом. HTTP 403 — запрос отклонён, данные
    чужого tenant'а не выдаются.
    """

    def __init__(self, *_: Any, message: str = "", sql: str = "") -> None:
        self.sql = sql
        super().__init__(
            message=message
            or (
                "Raw SQL over a tenant-aware table must be scoped by "
                "tenant_id (ADR-0383)"
            ),
            status_code=403,
        )


class TenantMixin:
    """Mixin для моделей, поддерживающих multi-tenancy.

    Добавляет колонку ``tenant_id`` + автоматическую фильтрацию
    (через ``apply_tenant_filter``).

    Usage::

        class Order(TenantMixin, BaseModel):
            ...
    """

    tenant_id: Mapped[str] = mapped_column(
        String(64), index=True, nullable=False, default="default"
    )

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Зарегистрировать subclass как tenant-aware (для raw-SQL guard).

        Таблица tenant-aware модели попадает в реестр
        ``_TENANT_AWARE_CLASSES`` уже на этапе объявления класса — raw-SQL
        guard узнаёт её, не дожидаясь конфигурации mapper'а.

        Args:
            kwargs: Аргументы, передаваемые в ``object.__init_subclass__``.
        """
        super().__init_subclass__(**kwargs)
        _TENANT_AWARE_CLASSES.add(cls)


_INSTALLED: bool = False

#: Классы tenant-aware моделей: подклассы ``TenantMixin`` + любой
#: mapped-класс с атрибутом ``tenant_id`` (тот же критерий, что у
#: ``_is_tenant_aware``). Используется raw-SQL guard'ом.
_TENANT_AWARE_CLASSES: set[type[Any]] = set()

#: Комментарии SQL (``-- ...`` и ``/* ... */``) — вырезаются перед
#: разбором, чтобы ``FROM`` в комментарии не считался таблицей.
_SQL_COMMENT_RE = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)

#: Строковые литералы SQL — вырезаются перед поиском таблиц.
_SQL_STRING_RE = re.compile(r"'(?:''|[^'])*'")

#: Ссылки на таблицы в raw SQL: ``FROM``/``JOIN``/``INTO``/``UPDATE``.
_TABLE_REF_RE = re.compile(r"\b(?:from|join|into|update)\s+([^\s(),;]+)", re.IGNORECASE)

#: Явный tenant-предикат: ``tenant_id = :param`` или ``tenant_id = 'lit'``.
_TENANT_PREDICATE_RE = re.compile(
    r"\btenant_id\b\s*(?:=|<>|!=)\s*(?::([A-Za-z_]\w*)|'([^']*)')",
    re.IGNORECASE,
)


def _is_tenant_aware(entity: Any) -> bool:
    """Check if mapped entity has ``tenant_id`` column (TenantMixin applied)."""
    return hasattr(entity, "tenant_id")


def _final_froms(stmt: Any) -> list[Any]:
    """Список FROM-элементов запроса с учётом перехода SQLAlchemy 1.4→2.0.

    ``Select.froms`` помечен deprecated (SADeprecationWarning, удаляется),
    ``Select.get_final_froms()`` — актуальный API.

    Args:
        stmt: SQLAlchemy statement.

    Returns:
        Список FROM-элементов (пустой для DML).
    """
    getter = getattr(stmt, "get_final_froms", None)
    if callable(getter):
        return list(getter())
    return list(getattr(stmt, "froms", []))


def _tenant_aware_entities(stmt: Any) -> list[Any]:
    """Найти tenant-aware сущности, участвующие в запросе.

    Две стратегии (аудит 2026-10-01, F-AM):

    1. ``statement.column_descriptions`` — точная сущность SELECT-запроса.
       Единственный надёжный источник для ``join``: у ``_ORMJoin`` атрибут
       ``entity_namespace`` — коллекция колонок, а не класс, поэтому прежний
       обход ``stmt.froms`` **молча не фильтровал join-запросы** (кросс-tenant
       чтение воспроизведено на ``select(Order, User.id).join(...)``);
    2. ``statement.entity_description`` — сущность ORM ``UPDATE``/``DELETE``
       (у DML нет ни ``column_descriptions``, ни ``froms``);
    3. откат на ``stmt.froms`` для запросов без column-описаний
       (например ``select(func.count()).select_from(Order)``).

    Args:
        stmt: SQLAlchemy statement.

    Returns:
        Список tenant-aware mapped-классов (может быть пустым).
    """
    entities: list[Any] = []
    for description in getattr(stmt, "column_descriptions", None) or []:
        entity = description.get("entity") if isinstance(description, dict) else None
        if entity is not None and _is_tenant_aware(entity):
            entities.append(entity)
    if entities:
        return entities

    dml_description = getattr(stmt, "entity_description", None)
    if isinstance(dml_description, dict):
        dml_entity = dml_description.get("entity")
        if dml_entity is not None and _is_tenant_aware(dml_entity):
            return [dml_entity]

    for frm in _final_froms(stmt):
        entity = getattr(frm, "entity_namespace", None)
        if entity and _is_tenant_aware(entity):
            entities.append(entity)
    return entities


def _table_name(cls: type[Any]) -> str | None:
    """Имя таблицы mapped-класса (без схемы).

    Args:
        cls: Mapped-класс.

    Returns:
        Имя таблицы или ``None``, если класс не mapped / таблица не задана.
    """
    try:
        table = inspect(cls).local_table
    except Exception:  # noqa: BLE001 — mapper ещё не сконфигурирован
        table = None
    if table is not None:
        return str(table.name)
    raw = getattr(cls, "__tablename__", None)
    return str(raw) if isinstance(raw, str) else None


def _tenant_aware_tables() -> frozenset[str]:
    """Имена tenant-aware таблиц (lowercase).

    Returns:
        Множество имён таблиц, у которых есть колонка ``tenant_id``.
    """
    names: set[str] = set()
    for cls in _TENANT_AWARE_CLASSES:
        name = _table_name(cls)
        if name:
            names.add(name.lower())
    return frozenset(names)


def _normalize_table_name(token: str) -> str:
    """Нормализовать имя таблицы из SQL-ссылки.

    Args:
        token: Токен после ``FROM``/``JOIN``/``INTO``/``UPDATE``.

    Returns:
        Имя таблицы в lowercase без схемы и кавычек.
    """
    last = token.split(".")[-1]
    return last.strip("\"`[]").lower()


def _referenced_tables(sql: str) -> set[str]:
    """Таблицы, на которые ссылается raw SQL.

    Args:
        sql: Текст запроса.

    Returns:
        Множество имён таблиц (lowercase, без схемы).
    """
    cleaned = _SQL_STRING_RE.sub(" ", _SQL_COMMENT_RE.sub(" ", sql))
    return {
        _normalize_table_name(match.group(1))
        for match in _TABLE_REF_RE.finditer(cleaned)
    }


def _param_is_tenant(parameters: Any, name: str, tenant_id: str) -> bool:
    """Совпадает ли bind-параметр ``name`` с текущим tenant'ом.

    Args:
        parameters: Параметры выполнения (``dict`` или список ``dict``).
        name: Имя bind-параметра.
        tenant_id: Активный tenant.

    Returns:
        ``True``, если значение параметра равно tenant'у.
    """
    if isinstance(parameters, dict):
        value = parameters.get(name)
        return isinstance(value, str) and value == tenant_id
    if isinstance(parameters, (list, tuple)):
        return all(_param_is_tenant(item, name, tenant_id) for item in parameters)
    return False


def _has_tenant_predicate(sql: str, parameters: Any, tenant_id: str) -> bool:
    """Есть ли в raw SQL явный предикат по текущему tenant'у.

    Args:
        sql: Текст запроса.
        parameters: Параметры выполнения.
        tenant_id: Активный tenant.

    Returns:
        ``True``, если запрос ограничен ``tenant_id`` текущего tenant'а.
    """
    cleaned = _SQL_COMMENT_RE.sub(" ", sql)
    for match in _TENANT_PREDICATE_RE.finditer(cleaned):
        param_name, literal = match.group(1), match.group(2)
        if param_name is not None:
            if _param_is_tenant(parameters, param_name, tenant_id):
                return True
        elif literal is not None and literal == tenant_id:
            return True
    return False


def _guard_raw_sql(statement: TextClause, parameters: Any, tenant_id: str) -> None:
    """Fail-closed guard для raw SQL (ADR-0383).

    Raw SQL по tenant-aware таблице обязан содержать явный
    ``tenant_id = <tenant>``-предикат. Иначе — :class:`TenantIsolationError`:
    молча пропустить чужого tenant'а нельзя, а автоматически переписать
    произвольный SQL (CTE/UNION/subquery) безопасно невозможно.

    Args:
        statement: Выполняемый ``TextClause``.
        parameters: Параметры выполнения.
        tenant_id: Активный tenant.

    Raises:
        TenantIsolationError: Если запрос не ограничен tenant'ом.
    """
    sql = statement.text
    if not _referenced_tables(sql) & _tenant_aware_tables():
        return
    if _has_tenant_predicate(sql, parameters, tenant_id):
        return
    raise TenantIsolationError(
        message=(
            "Raw SQL обращается к tenant-aware таблице без явного "
            "tenant_id-предиката (ADR-0383). Добавьте условие "
            "'WHERE tenant_id = :tenant_id' и передайте tenant_id "
            "текущего контекста — либо используйте ORM."
        ),
        sql=sql,
    )


def apply_tenant_filter(_target: Any = None) -> None:
    """Регистрирует SQLAlchemy event listeners для tenant isolation.

    * ``do_orm_execute`` → auto-filter **SELECT, UPDATE и DELETE** по ``tenant_id``
      (S88 W2: це Session event). До F-AM DML отсекался условием
      ``if not is_select: return``, из-за чего ``repository.update()`` и
      ``repository.delete()`` меняли чужой tenant (воспроизведено: 1 строка).
    * ``do_orm_execute`` → fail-closed guard для raw SQL (``text(...)``):
      запрос по tenant-aware таблице обязан содержать явный
      ``tenant_id``-предикат, иначе — ``TenantIsolationError`` (ADR-0383).
    * ``before_flush`` → auto-set ``tenant_id`` на new objects.

    Фильтруются **все** tenant-aware сущности запроса, а не только первая:
    join двух tenant-aware таблиц иначе оставлял вторую неограниченной.

    Ідемпотентно: повторний виклик — no-op.

    NOTE: аргумент ``_target`` збережено для backward compat с
    оригінальним API, но фактически listeners реєструються на класі
    ``Session`` (SessionEvents), оскільки ``do_orm_execute`` не існує
    ні на Engine, ні на sessionmaker.
    """
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    @event.listens_for(Mapper, "mapper_configured")
    def _register_tenant_aware_mapper(_mapper: Any, class_: type[Any]) -> None:
        """Запомнить mapped-класс с ``tenant_id`` (критерий ``_is_tenant_aware``)."""
        if hasattr(class_, "tenant_id"):
            _TENANT_AWARE_CLASSES.add(class_)

    @event.listens_for(Session, "do_orm_execute")
    def _filter_by_tenant(orm_execute_state: Any) -> None:
        stmt = orm_execute_state.statement
        tenant_id = get_tenant_id()

        # Raw SQL: ORM-фильтр к нему неприменим — fail-closed (ADR-0383).
        if isinstance(stmt, TextClause):
            if tenant_id:
                _guard_raw_sql(
                    stmt, getattr(orm_execute_state, "parameters", None), tenant_id
                )
            return

        if not (
            orm_execute_state.is_select
            or orm_execute_state.is_update
            or orm_execute_state.is_delete
        ):
            return

        if not tenant_id:
            return

        for entity in _tenant_aware_entities(stmt):
            stmt = stmt.where(entity.tenant_id == tenant_id)
        orm_execute_state.statement = stmt

    @event.listens_for(Session, "before_flush")
    def _set_tenant_on_new(
        session: Session, _flush_context: Any, _instances: Any
    ) -> None:
        tenant_id = get_tenant_id()
        if not tenant_id:
            return

        for obj in session.new:
            if hasattr(obj, "tenant_id") and not obj.tenant_id:
                obj.tenant_id = tenant_id
