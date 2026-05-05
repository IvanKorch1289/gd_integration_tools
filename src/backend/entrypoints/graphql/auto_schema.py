"""Динамическая генерация Strawberry Query/Mutation из ActionMetadata.

Wave 1.4 (Roadmap V10): для каждой :class:`ActionMetadata`
(``"graphql" in transports``) собираем Strawberry-резолвер.

Маппинг:

* ``side_effect == "read"`` → ``Query`` field;
* остальное (``"write"`` / ``"external"``) → ``Mutation`` field;
* имя поля = ``action_id`` с заменой ``.`` на ``_`` (GraphQL не любит точку);
* возвращаемый тип = JSON-обёртка ``ActionResult`` (унифицировано с
  существующим ``schema.py``);
* аргументы = ``payload: JSON | None``.

Auto-schema подключается рядом с существующим ``graphql_router`` через
:func:`auto_register_strawberry_schema`. Если actions-реестр пуст или
strawberry-pydantic не подключился — функция возвращает 0 без ошибок.
"""

# NOTE: ``from __future__ import annotations`` намеренно НЕ используется —
# Strawberry резолвит типы резолверов через ``typing.get_type_hints``,
# которому требуется eager-evaluated аннотация ``JSON`` (NewType-alias).
# При ``__future__.annotations`` тип превращается в строку и не находится
# в globals модуля резолвера → ``UnresolvedFieldTypeError``.

import logging
from collections.abc import Callable
from typing import Any

from strawberry.scalars import JSON

logger = logging.getLogger(__name__)

__all__ = (
    "AutoSchemaResult",
    "build_auto_strawberry_schema",
    "auto_register_strawberry_schema",
)


class AutoSchemaResult:
    """Результат сборки auto-schema.

    Attributes:
        schema: Готовая :class:`strawberry.Schema` или ``None``.
        query_count: Сколько Query-полей добавлено.
        mutation_count: Сколько Mutation-полей добавлено.
        skipped: Список (action, причина) — пропущенные actions.
    """

    __slots__ = ("schema", "query_count", "mutation_count", "skipped")

    def __init__(
        self,
        schema: Any | None,
        query_count: int,
        mutation_count: int,
        skipped: list[tuple[str, str]] | None = None,
    ) -> None:
        self.schema = schema
        self.query_count = query_count
        self.mutation_count = mutation_count
        self.skipped: list[tuple[str, str]] = skipped or []


def _action_to_field_name(action_id: str) -> str:
    """Превратить ``orders.list`` → ``orders_list`` (валидное имя поля GraphQL)."""
    return action_id.replace(".", "_").replace("-", "_")


def _build_resolver(action_id: str) -> Callable[..., Any]:
    """Построить async-резолвер, делегирующий в ``dispatch_action``.

    Резолвер принимает один аргумент ``payload`` (``JSON`` scalar — словарь
    произвольной формы) и возвращает ``JSON`` scalar (унифицированный
    envelope ``{action, success, data, error}``). Strawberry требует
    явные типизации — поэтому используем :class:`strawberry.scalars.JSON`,
    а не ``Any``.
    """

    async def resolver(payload: JSON | None = None) -> JSON:
        from src.entrypoints.base import dispatch_action

        try:
            data = await dispatch_action(
                action=action_id,
                payload=payload if isinstance(payload, dict) else {},
                source="graphql",
            )
        except KeyError:
            return {
                "action": action_id,
                "success": False,
                "error": f"Action {action_id!r} не зарегистрирован",
            }
        except Exception as exc:  # noqa: BLE001 — маппим в envelope
            logger.exception("auto-schema action %r упал", action_id)
            return {"action": action_id, "success": False, "error": str(exc)}

        if hasattr(data, "model_dump"):
            payload_out = data.model_dump(mode="json")
        elif isinstance(data, list):
            payload_out = data
        else:
            payload_out = data
        return {"action": action_id, "success": True, "data": payload_out}

    # Принудительно прописываем аннотации — Strawberry резолвит через
    # get_type_hints, и для closure-функций с from __future__-нет-аннотаций
    # это надёжный способ донести типы.
    resolver.__annotations__ = {"payload": JSON | None, "return": JSON}
    resolver.__name__ = f"auto_{_action_to_field_name(action_id)}"
    resolver.__doc__ = f"Авто-резолвер для action '{action_id}' (Wave 1.4)."
    return resolver


def build_auto_strawberry_schema(metadatas: Any | None = None) -> AutoSchemaResult:
    """Собрать Strawberry-Schema из реестра action-обработчиков.

    Args:
        metadatas: Iterable[ActionMetadata] (если задан) или ``None``
            (тогда берётся ``action_handler_registry.list_metadata("graphql")``).

    Returns:
        :class:`AutoSchemaResult` с готовой ``schema`` или ``None``,
        если нет ни одного action.
    """
    import strawberry

    if metadatas is None:
        from src.dsl.commands.action_registry import action_handler_registry

        metadatas = action_handler_registry.list_metadata("graphql")

    metas = tuple(metadatas)
    if not metas:
        return AutoSchemaResult(schema=None, query_count=0, mutation_count=0)

    @strawberry.type
    class AutoActionResult:
        """Унифицированный результат auto-action (Wave 1.4)."""

        action: str
        success: bool
        data: JSON | None = None
        error: str | None = None

    query_attrs: dict[str, Any] = {
        "__doc__": "Авто-сгенерированный Query (Wave 1.4 Roadmap V10)."
    }
    mutation_attrs: dict[str, Any] = {
        "__doc__": "Авто-сгенерированный Mutation (Wave 1.4 Roadmap V10)."
    }
    query_count = 0
    mutation_count = 0
    skipped: list[tuple[str, str]] = []

    for meta in metas:
        try:
            field_name = _action_to_field_name(meta.action)
            resolver = _build_resolver(meta.action)
            description = meta.description or f"Auto-action {meta.action}"

            if meta.side_effect == "read":
                query_attrs[field_name] = strawberry.field(
                    resolver=resolver, description=description
                )
                query_count += 1
            else:
                mutation_attrs[field_name] = strawberry.mutation(
                    resolver=resolver, description=description
                )
                mutation_count += 1
        except Exception as exc:  # noqa: BLE001 — не валим сборку из-за одного action
            skipped.append((meta.action, str(exc)))
            logger.warning("auto-schema: action %r пропущен (%s)", meta.action, exc)

    if query_count == 0:
        # Нужно хотя бы одно поле, чтобы Strawberry не ругался.
        def _auto_health() -> str:
            return "ok"

        _auto_health.__annotations__ = {"return": str}
        query_attrs["_auto_health"] = strawberry.field(
            resolver=_auto_health, description="Health-check авто-схемы (заглушка)."
        )

    Query = strawberry.type(name="AutoQuery")(type("AutoQuery", (), query_attrs))
    if mutation_count > 0:
        Mutation = strawberry.type(name="AutoMutation")(
            type("AutoMutation", (), mutation_attrs)
        )
        schema = strawberry.Schema(query=Query, mutation=Mutation)
    else:
        schema = strawberry.Schema(query=Query)

    # Используем AutoActionResult, чтобы Strawberry зарегистрировал тип
    # (даже если ни один резолвер ещё не возвращает его явно).
    _ = AutoActionResult

    return AutoSchemaResult(
        schema=schema,
        query_count=query_count,
        mutation_count=mutation_count,
        skipped=skipped,
    )


def auto_register_strawberry_schema(
    app: Any, *, path: str = "/api/v1/graphql"
) -> AutoSchemaResult:
    """Подключить auto-schema к FastAPI-приложению на отдельном пути.

    Существующий ``graphql_router`` (``/graphql``) не трогаем — auto-schema
    живёт на ``/api/v1/graphql`` (per ADR-008 версионирование).

    Args:
        app: Экземпляр :class:`FastAPI`.
        path: Path для GraphQL-endpoint.

    Returns:
        :class:`AutoSchemaResult` — готовая схема и счётчики.
    """
    result = build_auto_strawberry_schema()
    if result.schema is None:
        logger.info(
            "auto_register_strawberry_schema: нет actions с 'graphql' в transports"
        )
        return result

    try:
        from strawberry.fastapi import GraphQLRouter

        router = GraphQLRouter(result.schema, path=path)
        app.include_router(router)
        logger.info(
            "Wave 1.4: auto-schema подключена на %s (queries=%d, mutations=%d)",
            path,
            result.query_count,
            result.mutation_count,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("auto_register_strawberry_schema упал: %s", exc)
    return result
