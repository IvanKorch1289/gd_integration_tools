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

Wave 17 / T1 (ADR-0386): ``Connection`` — привилегированный путь +
RLS-coverage.

* **``Connection`` — привилегированный путь (только инфраструктура).**
  Guard живёт в session-level событии ``do_orm_execute``; вызов
  ``Connection.execute(text(...))`` идёт на Core-уровень и этот guard
  не проходит. Поэтому ``Connection`` разрешён только инфраструктурным
  кодам (CDC со своим профилем БД, warmup ``SELECT 1``, внутренний
  retry-обход). Бизнес-слой (``dsl/``, ``services/``) его использовать
  не должен — это проверяет гейт
  ``tests/unit/core/tenancy/test_connection_execute_gate.py``.
* **RLS — defense-in-depth к ORM-фильтру.** PostgreSQL-политики читают
  ``current_setting('app.tenant_id', true)``, поэтому сессия выставляет
  ``app.tenant_id`` из tenant-контекста в том же месте, где ставится
  ORM-фильтр (:func:`_set_tenant_scope_on_begin`). Без этой настройки
  tenant-скоуп не обеспечен (ADR-0386).

Wave 18 (ADR-0393) — что изменилось:

* **Tenant-таблицы больше не зависят от ``configure_mappers()``.** Раньше
  реестр tenant-aware таблиц наполнялся событием ``mapper_configured``,
  поэтому ДО конфигурации mapper'ов (или для моделей с собственным
  ``DeclarativeBase`` — например ``rule_engine_rulesets``) запрос к
  tenant-таблице НЕ блокировался: на БД без RLS это кросс-tenant чтение.
  Теперь таблицы определяются по **колонке ``tenant_id`` в metadata**
  (все известные ``MetaData``) + реестр ``Table``-события
  ``after_parent_attach`` (ловит таблицы любого registry, включая
  расширения);
* **Канон разбора raw SQL расширен**: ``COPY … TO STDOUT``, ``TRUNCATE``
  и ``FROM ONLY <table>`` больше не обходят guard (раньше токен после
  ``FROM`` читался как ``ONLY``, а ``COPY``/``TRUNCATE`` не разбирались
  вовсе);
* **RLS-скоуп ставится и для raw-соединений**: ``after_begin`` покрывает
  только ORM-сессии, а ``Connection.execute`` (runner, инфраструктура)
  идёт мимо. Добавлен публичный хелпер
  :func:`set_tenant_scope`, которым пользуются вызывающие стороны, и
  fallback в ``before_flush`` (scope берётся из tenant'а сохраняемых
  объектов) — иначе ``INSERT`` в tenant-таблицу отклоняется ``FORCE RLS``.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import MetaData, String, Table, TextClause, event, inspect, text
from sqlalchemy.orm import Mapped, Mapper, Session, mapped_column

from src.backend.core.errors import BaseError
from src.backend.core.logging import get_logger
from src.backend.core.tenancy import get_tenant_id

__all__ = (
    "TenantIsolationError",
    "TenantMixin",
    "apply_tenant_filter",
    "ensure_domain_mappers_configured",
    "guard_raw_sql",
    "referenced_tables",
    "set_tenant_scope",
    "tenant_aware_tables",
)

db_logger = get_logger("database")


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

#: Имена tenant-aware таблиц, discovered по колонке ``tenant_id`` в
#: metadata (ADR-0393). Наполняется событием ``Table.after_parent_attach``
#: — срабатывает в момент создания таблицы, независимо от того,
#: сконфигурирован ли mapper.
_TENANT_AWARE_TABLES: set[str] = set()


@event.listens_for(Table, "after_parent_attach")
def _register_tenant_aware_table(table: Table, _metadata: MetaData) -> None:
    """Запомнить таблицу с колонкой ``tenant_id`` (ADR-0393).

    Событие срабатывает при привязке таблицы к ``MetaData`` — то есть
    **до** конфигурации mapper'ов. Поэтому guard знает о tenant-таблице
    даже тогда, когда mapper ещё не настроен (и когда модель объявлена
    в собственном ``DeclarativeBase``, как ``rule_engine_rulesets``).

    Args:
        table: Привязанная таблица.
        _metadata: Metadata-родитель (не используется).

    """
    if "tenant_id" in table.c:
        _TENANT_AWARE_TABLES.add(table.name.lower())


#: Комментарии SQL (``-- ...`` и ``/* ... */``) — вырезаются перед
#: разбором, чтобы ``FROM`` в комментарии не считался таблицей.
_SQL_COMMENT_RE = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)

#: Строковые литералы SQL — вырезаются перед поиском таблиц.
_SQL_STRING_RE = re.compile(r"'(?:''|[^'])*'")

#: Ссылки на таблицы в raw SQL: ``FROM``/``JOIN``/``INTO``/``UPDATE``/
#: ``TRUNCATE``/``COPY``. ADR-0393: ``TRUNCATE`` и ``COPY`` добавлены
#: потому, что ``TRUNCATE t`` / ``COPY t TO STDOUT`` обходили guard
#: (кросс-tenant чтение/очистка), а ``FROM ONLY t`` давал токен
#: ``ONLY`` вместо имени таблицы.
_TABLE_REF_RE = re.compile(
    r"\b(?:from|join|into|update(?![\s(]*set\b)|truncate|copy)\s+"
    r"(?:only\s+)?([^\s(),;]+)",
    re.IGNORECASE,
)

#: Явный tenant-предикат: ``tenant_id = :param`` или ``tenant_id = 'lit'``.
_TENANT_PREDICATE_RE = re.compile(
    r"\btenant_id\b\s*(?:=|<>|!=)\s*(?::([A-Za-z_]\w*)|'([^']*)')", re.IGNORECASE
)

#: Установка tenant-скоупа для RLS-политик PostgreSQL (ADR-0386).
#: ``set_config(..., true)`` — transaction-local: значение сбрасывается
#: вместе с транзакцией, поэтому чужой tenant не наследуется.
_SET_TENANT_SCOPE_SQL = "SELECT set_config('app.tenant_id', :tenant_id, true)"


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


def _known_metadatas() -> tuple[MetaData, ...]:
    """Metadata-источники, в которых живут tenant-aware таблицы.

    Основной источник — ``core.domain.models.base.metadata`` (все модели
    ядра и расширений, наследующие ``BaseModel``). Отдельно учитывается
    metadata rule-engine: ``RuleEngineRulesetORM`` объявлен в собственном
    ``DeclarativeBase`` (чтобы не подключать SQLAlchemy-Continuum), поэтому
    его таблица ``rule_engine_rulesets`` не попадает в общий metadata.

    Returns:
        Кортеж metadata (пустой, если импорт моделей не удался).

    """
    metas: list[MetaData] = []
    try:
        from src.backend.core.domain.models.base import metadata as core_metadata

        metas.append(core_metadata)
    except Exception as exc:  # noqa: BLE001 — metadata недоступна → пустой набор
        db_logger.debug("tenant_metadata_unavailable: %s", exc)
    try:
        from src.backend.core.domain.models.rule_engine import RuleEngineBase

        metas.append(RuleEngineBase.metadata)
    except Exception as exc:  # noqa: BLE001 — модель не импортируется → пропуск
        db_logger.debug("rule_engine_metadata_unavailable: %s", exc)
    return tuple(metas)


def tenant_aware_tables() -> frozenset[str]:
    """Имена tenant-aware таблиц (lowercase).

    ADR-0393: набор больше не зависит от ``configure_mappers()``. Три
    источника складываются:

    1. реестр ``Table.after_parent_attach`` — таблицы с колонкой
       ``tenant_id`` из **любого** registry (ядро, расширения, rule-engine);
    2. metadata ядра и rule-engine — таблицы, созданные до регистрации
       слушателя (порядок импорта не важен);
    3. реестр tenant-aware классов (``TenantMixin`` + ``mapper_configured``).

    Returns:
        Множество имён таблиц, у которых есть колонка ``tenant_id``.

    """
    names: set[str] = set(_TENANT_AWARE_TABLES)
    for metadata in _known_metadatas():
        for table in metadata.tables.values():
            if "tenant_id" in table.c:
                names.add(table.name.lower())
    for cls in _TENANT_AWARE_CLASSES:
        name = _table_name(cls)
        if name:
            names.add(name.lower())
    return frozenset(names)


def _tenant_aware_tables() -> frozenset[str]:
    """Совместимая обёртка над :func:`tenant_aware_tables`."""
    return tenant_aware_tables()


def _normalize_table_name(token: str) -> str:
    """Нормализовать имя таблицы из SQL-ссылки.

    Args:
        token: Токен после ``FROM``/``JOIN``/``INTO``/``UPDATE``.

    Returns:
        Имя таблицы в lowercase без схемы и кавычек.
    """
    last = token.split(".")[-1]
    return last.strip('"`[]').lower()


def referenced_tables(sql: str) -> frozenset[str]:
    """Таблицы, на которые ссылается raw SQL (ADR-0393 — расширенный канон).

    Разбираются ``FROM`` / ``JOIN`` / ``INTO`` / ``UPDATE`` / ``TRUNCATE`` /
    ``COPY``; модификатор ``ONLY`` (``FROM ONLY t``) отбрасывается.
    Строковые литералы и комментарии вырезаются до разбора.

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


def _referenced_tables(sql: str) -> set[str]:
    """Совместимая обёртка над :func:`referenced_tables`."""
    return set(referenced_tables(sql))


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


def guard_raw_sql(
    sql: str, parameters: Any, tenant_id: str | None, *, connection: Any = None
) -> None:
    """Fail-closed guard для raw SQL (ADR-0383/ADR-0393).

    Raw SQL по tenant-aware таблице обязан содержать явный
    ``tenant_id = <tenant>``-предикат. Иначе — :class:`TenantIsolationError`:
    молча пропустить чужого tenant'а нельзя, а автоматически переписать
    произвольный SQL (CTE/UNION/subquery) безопасно невозможно.

    Если tenant-контекста нет вовсе — запрос к tenant-aware таблице
    отклоняется тоже (fail-closed): без tenant'а «текущий tenant» неизвестен,
    а значит не ограничен.

    Args:
        sql: Текст запроса.
        parameters: Параметры выполнения.
        tenant_id: Активный tenant (``None`` — tenant не привязан).
        connection: Соединение — на него выставляется RLS-скоуп
            (``app.tenant_id``), если соединение передано.

    Raises:
        TenantIsolationError: Если запрос не ограничен tenant'ом.

    """
    if not referenced_tables(sql) & tenant_aware_tables():
        if connection is not None and tenant_id:
            set_tenant_scope(connection, tenant_id)
        return
    if tenant_id and _has_tenant_predicate(sql, parameters, tenant_id):
        if connection is not None:
            set_tenant_scope(connection, tenant_id)
        return
    if not tenant_id:
        raise TenantIsolationError(
            message=(
                "Raw SQL обращается к tenant-aware таблице, но tenant-контекст "
                "не привязан (ADR-0393). Запрос отклонён: tenant-скоуп "
                "неизвестен."
            ),
            sql=sql,
        )
    raise TenantIsolationError(
        message=(
            "Raw SQL обращается к tenant-aware таблице без явного "
            "tenant_id-предиката (ADR-0383). Добавьте условие "
            "'WHERE tenant_id = :tenant_id' и передайте tenant_id "
            "текущего контекста — либо используйте ORM."
        ),
        sql=sql,
    )


def _guard_raw_sql(statement: TextClause, parameters: Any, tenant_id: str) -> None:
    """Совместимая обёртка над :func:`guard_raw_sql` (ADR-0383).

    Args:
        statement: Выполняемый ``TextClause``.
        parameters: Параметры выполнения.
        tenant_id: Активный tenant.

    Raises:
        TenantIsolationError: Если запрос не ограничен tenant'ом.

    """
    guard_raw_sql(statement.text, parameters, tenant_id)


def set_tenant_scope(connection: Any, tenant_id: str | None) -> bool:
    """Выставить ``app.tenant_id`` на указанном соединении (ADR-0386/0393).

    Session-level событие ``after_begin`` покрывает только ORM-сессии.
    Raw-вызовы (``Connection.execute``) — инфраструктурный runner,
    фоновые задачи, DSL-шаг «сырой SQL» — идут мимо него, поэтому
    PostgreSQL-политики RLS видели пустой ``current_setting('app.tenant_id')``:
    strict-политики не пропускали ни одной строки, ``FORCE RLS`` отклонял
    ``INSERT``.

    Настройка transaction-local (``set_config(..., true)``) — значение
    сбрасывается вместе с транзакцией, чужой tenant не наследуется.
    Значение подставляется bind-параметром — SQL-инъекция невозможна.

    Args:
        connection: Соединение SQLAlchemy (sync ``Connection`` или его
            async-аналог).
        tenant_id: Идентификатор tenant'а (пустой — scope не выставляется).

    Returns:
        ``True``, если scope выставлен; ``False`` — если tenant не задан,
        диалект не PostgreSQL или SET не удался.

    """
    if not tenant_id:
        return False
    if getattr(getattr(connection, "dialect", None), "name", "") != "postgresql":
        return False
    try:
        connection.execute(text(_SET_TENANT_SCOPE_SQL), {"tenant_id": tenant_id})
    except Exception as exc:  # noqa: BLE001 — SET не должен ронять запрос
        db_logger.warning(
            "RLS SET LOCAL app.tenant_id не применён: %s", exc, exc_info=True
        )
        return False
    return True


def _set_tenant_scope_on_begin(
    _session: Session, _transaction: Any, connection: Any
) -> None:
    """Выставить ``app.tenant_id`` в сессии для RLS-политик (ADR-0386).

    PostgreSQL-политика ``USING (tenant_id = current_setting('app.tenant_id',
    true))`` читает GUC-параметр сессии. Если его не выставить, tenant-скоуп
    не обеспечен: strict-политики не пропустят ни одной строки, а
    global-политики (``tenant_id IS NULL OR ...``) — пропустят глобальные
    строки. Поэтому значение ставится там же, где ставится ORM-фильтр, —
    в session-level событии.

    Настройка transaction-local (``set_config(..., true)``) и выполняется
    один раз на транзакцию (событие ``after_begin`` не срабатывает на
    вложенных savepoint'ах). Значение подставляется bind-параметром —
    SQL-инъекция через ``tenant_id`` невозможна.

    Args:
        _session: Сессия SQLAlchemy (не используется).
        _transaction: Транзакция сессии (не используется).
        connection: Соединение с БД.

    """
    set_tenant_scope(connection, get_tenant_id())


def apply_tenant_filter(_target: Any = None) -> None:
    """Регистрирует SQLAlchemy event listeners для tenant isolation.

    * ``do_orm_execute`` → auto-filter **SELECT, UPDATE и DELETE** по ``tenant_id``
      (S88 W2: це Session event). До F-AM DML отсекался условием
      ``if not is_select: return``, из-за чего ``repository.update()`` и
      ``repository.delete()`` меняли чужой tenant (воспроизведено: 1 строка).
    * ``do_orm_execute`` → fail-closed guard для raw SQL (``text(...)``):
      запрос по tenant-aware таблице обязан содержать явный
      ``tenant_id``-предикат, иначе — ``TenantIsolationError`` (ADR-0383).
    * ``after_begin`` → установка ``app.tenant_id`` из tenant-контекста
      (PostgreSQL-only): RLS-политики читают
      ``current_setting('app.tenant_id', true)`` (ADR-0386).
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
    # ADR-0393: конфигурация mapper'ов доменных моделей выполняется
    # **до** early-return: глобальный listener SQLAlchemy-Continuum
    # (``Mapper.after_configured``) падает, если доменные модели
    # импортированы, но не сконфигурированы, а конфигурируется mapper
    # другого registry. Раньше это давало order-dependent падение
    # ``test_tenant_filter_orm_dml.py`` в общем сеансе с
    # ``tests/unit/infrastructure/database``.
    ensure_domain_mappers_configured()
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
        """Проставить ``tenant_id`` новым объектам и выставить RLS-скоуп.

        Две обязанности в одном listener'е (ADR-0393):

        1. ``tenant_id`` пустого объекта заполняется tenant'ом контекста;
        2. если tenant-контекста **нет** (фоновые/служебные пути — pg-runner,
           worker не биндят tenant в ContextVar), scope для RLS берётся из
           tenant'а самих сохраняемых объектов. Иначе на PostgreSQL с
           ``FORCE RLS`` ``INSERT`` в tenant-таблицу отклоняется, а
           ``SELECT`` возвращает 0 строк. Если tenant'ов в flush несколько
           (или неизвестен) — scope не выставляется (fail-closed: решение
           остаётся за явным bind'ом tenant-контекста).

        Args:
            session: Сессия SQLAlchemy.
            _flush_context: Контекст flush (не используется).
            _instances: Инстансы flush (не используются).

        """
        tenant_id = get_tenant_id()
        if not tenant_id:
            _ensure_rls_scope_for_flush(session)
            return

        for obj in session.new:
            if hasattr(obj, "tenant_id") and not obj.tenant_id:
                obj.tenant_id = tenant_id

    # RLS scope: тот же session-event, что и ORM-фильтр (ADR-0386).
    event.listen(Session, "after_begin", _set_tenant_scope_on_begin)


def _ensure_rls_scope_for_flush(session: Session) -> None:
    """Выставить RLS-скоуп из tenant'а сохраняемых объектов (ADR-0393).

    Используется, когда tenant-контекст не привязан: scope берётся из
    tenant'а объектов flush'а. Если tenant'ов несколько — scope не
    выставляется (fail-closed).

    Args:
        session: Сессия SQLAlchemy.

    """
    tenants = {obj.tenant_id for obj in session.new if getattr(obj, "tenant_id", None)}
    if len(tenants) != 1:
        return
    tenant_id = next(iter(tenants))
    try:
        connection = session.connection()
    except Exception as exc:  # noqa: BLE001 — соединения может не быть
        db_logger.debug("rls_scope_flush_skipped: %s", exc)
        return
    if set_tenant_scope(connection, tenant_id):
        db_logger.debug("rls_scope_taken_from_flush_tenant: %s", tenant_id)


def ensure_domain_mappers_configured() -> None:
    """Сконфигурировать mapper'ы доменных моделей (ADR-0393, дефект регрессии).

    ``sqlalchemy_continuum.make_versioned`` (вызывается при импорте
    :mod:`src.backend.core.domain.models.base`) регистрирует **глобальный**
    listener ``Mapper.after_configured``. Его обработчик конфигурирует
    versioned-классы и падает с ``AttributeError: 'NoneType' object has no
    attribute 'active_history'``, если в момент срабатывания атрибуты
    ещё не сконфигурированы (``impl is None``).

    Это происходит, когда доменные модели импортированы, но их mapper'ы
    не настроены, а затем конфигурируется mapper **другого** registry
    (типичный сценарий — тест с собственным ``DeclarativeBase``). Раньше
    это ломало ``tests/unit/core/tenancy/test_tenant_filter_orm_dml.py``
    в общем сеансе с ``tests/unit/infrastructure/database`` (зависимость
    от порядка тестов).

    Здесь mapper'ы конфигурируются **до** регистрации tenant-listener'ов:
    обработчик continuum'а получает уже готовые классы, и глобальное
    состояние не загрязняется.

    Ошибки конфигурации mapper'ов не роняют процесс — они логируются
    (fail-closed на уровне проверок, а не на уровне импорта).
    """
    try:
        from sqlalchemy.orm import configure_mappers

        configure_mappers()
    except Exception as exc:  # noqa: BLE001 — конфигурация не критична
        db_logger.warning("domain_mappers_configure_failed: %s", exc)
