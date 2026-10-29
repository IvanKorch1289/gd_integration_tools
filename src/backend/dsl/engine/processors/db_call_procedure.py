"""K3 S5 W8 — DSL-процессор ``db_call_procedure``: вызов stored procedure.

Wave ``[wave:s5/k3-w8-db-call-procedure]``.

Выполняет stored procedure в БД через профиль из ``ExternalDatabaseRegistry``
(asyncpg-совместимый). Поддерживает:

* любую СУБД, в которой Procedure вызывается через ``CALL <schema>.<name>(...)``
  (PostgreSQL 11+, MS SQL ``EXEC``, Oracle ``BEGIN .. END``);
* передачу параметров из body / properties / headers (как в
  :class:`ExternalDbQueryProcessor`);
* возврат result-set через RETURNS / OUT-параметры.

Контракт DSL (схема опциональна — по умолчанию берётся из профиля БД)::

    .db_call_procedure(
        profile="oracle_prod",
        name="recalc_credit_score",
        params_from="body",
        result_property="sp_result",
    )

Безопасность (ADR-0380):

* ``schema``/``name`` (из YAML-роута) — allowlist-идентификаторы
  (``validate_identifier``, канон ``core/utils/sql_identifiers.py``);
* ключи bind-параметров (из runtime-body) — только allowlist-идентификаторы;
  значения уходят bind-параметрами SQLAlchemy и в SQL не подставляются;
* собранный вызов проходит общий SQL-guard ``validate_sql``
  (``dsl/engine/processors/_sql_validation.py``): multi-statement и
  DDL/privilege-команды запрещены. Для Oracle валидируется **тело** вызова,
  а не PL/SQL-обёртка ``BEGIN ... END;``;
* feature-flag fail-closed: недоступный ``feature_flags`` → ``exchange.fail``,
  шаг **не** исполняется;
* схема по умолчанию берётся из профиля внешней БД (``db_schema``), а не из
  hardcoded ``public`` (для Oracle-профиля это ``REPORTING`` и т. п.).

Feature flag: ``feature_flags.db_call_procedure_enabled`` (default-OFF).

Семантика флага (ADR-0389):

* флаг **выключен** (default) → шаг пропускается (``skipped``), причина — в
  ``exchange.properties["db_call_procedure_skip_reason"]`` и в WARNING-логе;
* флаг **недоступен** (ошибка чтения) → ``exchange.fail(...)`` (fail-closed);
* включение — только явно: ``features.db_call_procedure_enabled: true`` в
  overlay'е профиля либо env ``FEATURE_DB_CALL_PROCEDURE_ENABLED=true``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Final

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.core.utils.sql_identifiers import validate_identifier
from src.backend.dsl.engine.processors._sql_validation import validate_sql
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error
from src.backend.dsl.registry import processor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = ("DbCallProcedureProcessor",)


_logger = get_logger("dsl.processors.db_call_procedure")

_ALLOWED_PARAM_SOURCES = frozenset({"body", "properties", "headers", "none"})

#: Имя feature-флага, включающего шаг (default-OFF, ADR-0380/ADR-0389).
_FEATURE_FLAG: Final = "db_call_procedure_enabled"

#: Единая подсказка «как включить» — используется и в тексте ошибки, и в
#: причине пропуска шага, чтобы оператор видел один и тот же способ включения
#: (ADR-0389: отключение должно быть явным и полезным, а не «выключенной
#: фичей» без указания, что делать).
_ENABLE_HINT: Final = (
    "enable it in the profile (features.db_call_procedure_enabled: true) "
    "or via env FEATURE_DB_CALL_PROCEDURE_ENABLED=true"
)

#: Допустимые диалекты вызова stored procedure. ``None`` (не указан) означает
#: «вывести из типа СУБД профиля» — см. ``_resolve_dialect``.
_ALLOWED_DIALECTS = frozenset({"postgres", "mssql", "oracle", "mysql", "db2"})

#: Схема по умолчанию — только если профиль внешней БД недоступен и схема не
#: задана явно (профиль внешней БД всегда имеет ``db_schema`` в конфиге).
_FALLBACK_SCHEMA: Final = "public"


@processor(
    "db_call_procedure",
    namespace="core",
    spec_schema={
        "type": "object",
        "properties": {
            "profile": {"type": "string"},
            "name": {"type": "string"},
            "schema": {"type": ["string", "null"]},
            "params_from": {"type": "string", "enum": sorted(_ALLOWED_PARAM_SOURCES)},
            "result_property": {"type": "string"},
            "dialect": {
                "type": ["string", "null"],
                "enum": ["postgres", "mssql", "oracle", "mysql", "db2", None],
            },
        },
        "required": ["profile", "name"],
    },
    capabilities=("db.execute_procedure.*",),
    meta={"tier": 1, "category": "integration"},
    tags=("db", "stored-procedure", "execute"),
)
class DbCallProcedureProcessor(BaseProcessor):
    """Вызов stored procedure через профиль ExternalDatabase.

    Args:
        profile: Имя профиля внешней БД.
        name: Имя процедуры (без schema-префикса; schema передаётся отдельно).
        schema: Schema-префикс. ``None`` (default) — схема берётся из
            профиля внешней БД (``db_schema``).
        params_from: Источник параметров — ``body`` / ``properties`` / ``headers`` / ``none``.
        result_property: Куда положить результат.
        dialect: Диалект CALL: ``postgres`` (CALL), ``mssql`` (EXEC), ``oracle`` (BEGIN..END).

    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.SIDE_EFFECTING
    compensatable: ClassVar[bool] = False

    def __init__(
        self,
        profile: str,
        name: str,
        *,
        schema: str | None = None,
        params_from: str = "body",
        result_property: str = "sp_result",
        dialect: str | None = None,
        proc_name: str | None = None,
    ) -> None:
        super().__init__(
            name=proc_name or f"db_call_procedure:{schema or 'auto'}.{name}"
        )
        if not profile:
            raise ValueError("db_call_procedure: profile must be non-empty")
        if not name:
            raise ValueError("db_call_procedure: name must be non-empty")
        if params_from not in _ALLOWED_PARAM_SOURCES:
            raise ValueError(
                f"db_call_procedure: params_from must be one of {sorted(_ALLOWED_PARAM_SOURCES)}"
            )
        if dialect is not None and dialect not in _ALLOWED_DIALECTS:
            raise ValueError(
                "db_call_procedure: dialect must be one of "
                f"{sorted(_ALLOWED_DIALECTS)} or None (auto)"
            )
        self._profile = profile
        self._sp_name = name
        # ADR-0380: ``None`` — «взять схему из профиля внешней БД».
        self._schema = schema
        self._params_from = params_from
        self._result_property = result_property
        # Cycle 172 (HIGH-14): ``None`` означает «вывести диалект из типа СУБД
        # профиля». Раньше дефолт был ``"postgres"`` для любого профиля, и
        # Oracle-профиль получал невалидный ``CALL``.
        self._dialect = dialect

    def _profile_settings(self) -> Any | None:
        """Возвращает настройки профиля внешней БД (или ``None``).

        Профиль может быть не зарегистрирован (изолированный тест, не
        поднятый registry) — тогда возвращается ``None``, а вызывающий код
        переходит на fallback.
        """
        try:
            from src.backend.infrastructure.database.database import (
                get_external_db_registry,
            )

            initializer = get_external_db_registry().get_initializer(self._profile)
        except Exception as exc:  # noqa: BLE001 — профиль может отсутствовать
            _logger.debug("db_call_procedure.profile_unavailable: %s", exc)
            return None
        return getattr(initializer, "settings", None)

    def _resolve_schema(self) -> str:
        """Возвращает эффективную схему вызова процедуры.

        Приоритет: явно заданная схема шага → схема профиля внешней БД
        (``db_schema``) → ``public`` (профиль недоступен).
        """
        if self._schema is not None:
            return self._schema
        profile_schema = getattr(self._profile_settings(), "db_schema", None)
        if isinstance(profile_schema, str) and profile_schema:
            return profile_schema
        return _FALLBACK_SCHEMA

    def _resolve_dialect(self) -> str:
        """Возвращает эффективный диалект вызова процедуры.

        Явный ``dialect`` имеет приоритет. Если он не задан, диалект
        выводится из типа СУБД профиля внешней БД.
        """
        if self._dialect is not None:
            return self._dialect

        from src.backend.core.enums.database import DatabaseTypeChoices

        db_type = getattr(self._profile_settings(), "type", None)
        mapping = {
            DatabaseTypeChoices.postgresql: "postgres",
            DatabaseTypeChoices.mssql: "mssql",
            DatabaseTypeChoices.oracle: "oracle",
            DatabaseTypeChoices.mysql: "mysql",
            DatabaseTypeChoices.db2: "db2",
        }
        return mapping.get(db_type, "postgres")

    def _build_call_sql(self, params: dict[str, Any]) -> str:
        """Строит валидированный SQL вызова процедуры с bind-параметрами ``:name``.

        Args:
            params: Bind-параметры (ключ → значение); значения в SQL не
                подставляются, ключи используются как имена плейсхолдеров.

        Returns:
            Текст SQL-вызова (для Oracle — PL/SQL-обёртка ``BEGIN ... END;``).

        Raises:
            ValueError: если ``schema``/``name``/ключи bind-параметров не
                проходят allowlist-идентификаторов либо вызов не прошёл
                SQL-guard ``validate_sql``.

        """
        schema = self._resolve_schema()
        validate_identifier(schema, context="db_call_procedure.schema")
        validate_identifier(self._sp_name, context="db_call_procedure.name")
        for key in params:
            validate_identifier(key, context="db_call_procedure.bind_parameter")

        full_name = f"{schema}.{self._sp_name}"
        binds = ", ".join(f":{key}" for key in params) if params else ""
        dialect = self._resolve_dialect()
        if dialect == "mssql":
            call = f"EXEC {full_name} {binds}".rstrip()
        elif dialect == "oracle":
            call = f"{full_name}({binds})"
        else:
            call = f"CALL {full_name}({binds})"

        # SQL-guard применяется к телу вызова: для Oracle PL/SQL-обёртка
        # ``BEGIN ... END;`` содержит ``;`` и guard'ом не проверяется.
        validate_sql(call)

        if dialect == "oracle":
            return f"BEGIN {call}; END;"
        return call

    def _collect_params(self, exchange: Exchange[Any]) -> dict[str, Any]:
        match self._params_from:
            case "body":
                body = exchange.in_message.body
                return dict(body) if isinstance(body, dict) else {}
            case "properties":
                return dict(exchange.properties)
            case "headers":
                return dict(exchange.in_message.headers)
            case "none":
                return {}
            case _:
                return {}

    @staticmethod
    def _materialize_payload(result: Any) -> Any:
        """Материализует result-set процедуры.

        ``EXEC``/``BEGIN`` (mssql/oracle) result-set не возвращают: cursor
        закрыт, и ``mappings().all()`` бросил бы ``ResourceClosedError``,
        из-за чего не выполнялся бы ``commit()`` — эффекты процедуры
        откатывались бы. Поэтому ветка выбирается по ``result.returns_rows``.
        """
        if not getattr(result, "returns_rows", False):
            return None
        if getattr(result, "closed", False):
            return None
        try:
            return [dict(row) for row in result.mappings().all()]
        except (AttributeError, TypeError) as exc:
            # D-AUDIT-14101 fix (cycle 141): narrow от bare
            # 'except Exception: _' (swallow'ил SystemExit/KeyboardInterrupt
            # + unexpected exceptions) до конкретных AttributeError/
            # TypeError. Soft-fail behavior сохранён (payload=None →
            # caller обработает как 'no result').
            _logger.debug(
                "DBCallProcedure: result mappings conversion failed "
                "(exc_type=%s exc_msg=%s) — payload=None",
                type(exc).__name__,
                exc,
            )
            return None

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Вызывает хранимую SQL-процедуру через внешний session manager."""
        try:
            from src.backend.core.config.features import feature_flags

            enabled = bool(feature_flags.db_call_procedure_enabled)
        except (ImportError, AttributeError, RuntimeError) as ff_exc:
            # ADR-0380: fail-closed. Раньше ошибка чтения флага логировалась
            # в debug и шаг продолжал исполняться (fail-open).
            _logger.error("db_call_procedure.flag_unavailable: %s", ff_exc)
            exchange.fail(
                f"db_call_procedure is disabled: feature flag '{_FEATURE_FLAG}' "
                f"is unavailable (fail-closed) — {_ENABLE_HINT}"
            )
            return

        if not enabled:
            # ADR-0389: выключенный флаг — не молчаливый skip. Причина
            # пропуска попадает в exchange (property) и в лог (WARNING),
            # чтобы отключение было явным и подсказывало, как включить флаг.
            # Контроль потока не меняется (ADR-0380): шаг пропускается,
            # маршрут не падает.
            reason = (
                f"db_call_procedure is skipped: feature flag '{_FEATURE_FLAG}' "
                f"is OFF (default-OFF, ADR-0380/ADR-0389) — {_ENABLE_HINT}"
            )
            _logger.warning("db_call_procedure.disabled: %s", reason)
            exchange.set_property("db_call_procedure_status", "skipped")
            exchange.set_property("db_call_procedure_skip_reason", reason)
            return

        params = self._collect_params(exchange)
        try:
            sql = self._build_call_sql(params)
        except ValueError as exc:
            # ADR-0380: SQL/идентификаторы не прошли валидацию — шаг не
            # исполняется (fail-closed).
            _logger.error("db_call_procedure.sql_rejected: %s", exc)
            exchange.fail(f"db_call_procedure SQL rejected: {exc}")
            return

        from sqlalchemy import text

        from src.backend.core.di.providers import get_external_session_manager_provider

        session_manager = get_external_session_manager_provider()(self._profile)
        async with session_manager.create_session() as session:
            result = await session.execute(text(sql), params)
            payload: Any = self._materialize_payload(result)
            await session.commit()

        exchange.set_property(self._result_property, payload)
        exchange.set_out(body=payload, headers=dict(exchange.in_message.headers))

    def to_spec(self) -> dict[str, Any] | None:
        """Метод to_spec (см. signature)."""
        spec: dict[str, Any] = {"profile": self._profile, "name": self._sp_name}
        if self._schema is not None:
            spec["schema"] = self._schema
        if self._params_from != "body":
            spec["params_from"] = self._params_from
        if self._result_property != "sp_result":
            spec["result_property"] = self._result_property
        if self._dialect is not None:
            spec["dialect"] = self._dialect
        return {"db_call_procedure": spec}
