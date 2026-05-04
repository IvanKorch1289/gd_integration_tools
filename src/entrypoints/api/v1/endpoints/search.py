"""Единый поисковый API поверх Elasticsearch (Wave 9.3.3).

W26.5: маршруты регистрируются декларативно через ActionSpec.

Эндпоинты ``/api/v1/search/*`` — полнотекст по audit-логам, заказам,
notebooks. Если индекс отсутствует или ES недоступен — возвращается
пустой массив (а не 5xx), чтобы UI оставался работоспособным.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from src.entrypoints.api.generator.actions import ActionRouterBuilder, ActionSpec
from src.services.io.search import get_search_service

__all__ = ("router",)

logger = logging.getLogger(__name__)


# --- Query schemas ---------------------------------------------------------


class _RangeQuery(BaseModel):
    """Базовые поля для range-фильтра."""

    from_: datetime | None = Field(default=None, alias="from")
    to_: datetime | None = Field(default=None, alias="to")
    limit: int = Field(default=20, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class LogsSearchQuery(_RangeQuery):
    """Query-параметры /logs."""

    q: str | None = Field(default=None, description="Полнотекстовый запрос.")
    entity_type: str | None = Field(default=None, description="Фильтр по entity_type.")
    tenant_id: str | None = Field(default=None, description="Фильтр по tenant_id.")


class OrdersSearchQuery(_RangeQuery):
    """Query-параметры /orders."""

    q: str | None = Field(default=None, description="Полнотекстовый запрос.")
    status: str | None = Field(default=None, description="Фильтр по статусу.")


class NotebooksSearchQuery(BaseModel):
    """Query-параметры /notebooks."""

    q: str | None = Field(default=None, description="Полнотекстовый запрос.")
    tag: str | None = Field(default=None, description="Фильтр по тегу.")
    limit: int = Field(default=20, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class AggregationsQuery(BaseModel):
    """Query-параметры /aggregations."""

    index: str = Field(..., description="Имя индекса (без префикса gd_).")
    field: str = Field(..., description="Поле для terms-агрегации.")
    q: str | None = Field(default=None, description="Опциональный фильтр.")
    size: int = Field(default=10, ge=1, le=100)


class FacetsPath(BaseModel):
    """Path-параметр /facets/{index}."""

    index: str = Field(..., description="Имя индекса (без префикса gd_).")


class FacetsQuery(BaseModel):
    """Query-параметры /facets."""

    field: str = Field(..., description="Поле для terms-агрегации.")
    filter: str | None = Field(
        default=None,
        description='JSON-объект term-фильтров, например {"status":"OPEN"}.',
    )
    size: int = Field(default=20, ge=1, le=200)


# --- ES query builders -----------------------------------------------------


def _build_text_query(
    q: str | None,
    *,
    fields: list[str] | None = None,
    filters: dict[str, Any] | None = None,
    range_filter: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Собирает bool-query для ES."""
    must: list[dict[str, Any]] = []
    if q:
        if fields:
            must.append({"multi_match": {"query": q, "fields": fields}})
        else:
            must.append({"query_string": {"query": q}})
    filter_clauses: list[dict[str, Any]] = []
    for key, value in (filters or {}).items():
        if value is None:
            continue
        filter_clauses.append({"term": {key: value}})
    for field_name, range_spec in (range_filter or {}).items():
        if range_spec:
            filter_clauses.append({"range": {field_name: range_spec}})
    if not must and not filter_clauses:
        return {"match_all": {}}
    bool_query: dict[str, Any] = {}
    if must:
        bool_query["must"] = must
    if filter_clauses:
        bool_query["filter"] = filter_clauses
    return {"bool": bool_query}


async def _safe_search(
    index: str,
    query: dict[str, Any],
    *,
    limit: int,
    offset: int,
    sort: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Выполняет поиск с graceful-fallback при недоступности ES."""
    try:
        service = get_search_service()
        return await service.search(index, query, size=limit, from_=offset, sort=sort)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Search failed for index %s: %s", index, exc)
        return []


def _date_range(
    from_: datetime | None, to_: datetime | None, key: str
) -> dict[str, dict[str, Any]]:
    """Строит range-фильтр по датам, опуская пустые границы."""
    if from_ is None and to_ is None:
        return {}
    body: dict[str, Any] = {}
    if from_ is not None:
        body["gte"] = from_.isoformat()
    if to_ is not None:
        body["lte"] = to_.isoformat()
    return {key: body}


# --- Service facade --------------------------------------------------------


class _SearchFacade:
    """Адаптер над ``SearchService`` для action-маршрутов."""

    async def search_logs(
        self,
        *,
        q: str | None = None,
        entity_type: str | None = None,
        tenant_id: str | None = None,
        from_: datetime | None = None,
        to_: datetime | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        query = _build_text_query(
            q,
            fields=["who", "what", "entity_id", "action"],
            filters={"entity_type": entity_type, "tenant_id": tenant_id},
            range_filter=_date_range(from_, to_, "when"),
        )
        return await _safe_search(
            "audit_logs", query, limit=limit, offset=offset, sort=[{"when": "desc"}]
        )

    async def search_orders(
        self,
        *,
        q: str | None = None,
        status: str | None = None,
        from_: datetime | None = None,
        to_: datetime | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        query = _build_text_query(
            q,
            fields=["pledge_gd_id", "order_kind_id"],
            filters={"status": status},
            range_filter=_date_range(from_, to_, "created_at"),
        )
        return await _safe_search(
            "orders", query, limit=limit, offset=offset, sort=[{"created_at": "desc"}]
        )

    async def search_notebooks(
        self,
        *,
        q: str | None = None,
        tag: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        query = _build_text_query(q, fields=["title", "content"], filters={"tags": tag})
        return await _safe_search(
            "notebooks",
            query,
            limit=limit,
            offset=offset,
            sort=[{"updated_at": "desc"}],
        )

    async def aggregate(
        self, *, index: str, field: str, q: str | None = None, size: int = 10
    ) -> dict[str, Any]:
        try:
            service = get_search_service()
            aggs = {"by_field": {"terms": {"field": field, "size": size}}}
            es_query = _build_text_query(q) if q else None
            return await service.aggregate(index, aggs, query=es_query)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Aggregation failed for %s: %s", index, exc)
            return {}

    async def facets(
        self, *, index: str, field: str, filter: str | None = None, size: int = 20
    ) -> dict[str, Any]:
        """Возвращает terms-агрегацию для UI-faceting.

        ``filter`` — JSON ``{"field": value}``. SQLite-FTS5 fallback
        возвращает пустой dict. Никогда не пробрасывает 5xx — UI должен
        получить 200 + пустые buckets.
        """
        import json

        filters: dict[str, Any] = {}
        if filter:
            try:
                parsed = json.loads(filter)
                if isinstance(parsed, dict):
                    filters = parsed
            except json.JSONDecodeError:
                logger.warning("facets: invalid filter JSON, ignored")

        try:
            from src.infrastructure.clients.storage.elasticsearch import (
                get_elasticsearch_client,
            )

            client = get_elasticsearch_client()
            return await client.aggregate_terms(
                index, field, filters=filters or None, size=size
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("facets failed for %s.%s: %s", index, field, exc)
            return {}


_FACADE = _SearchFacade()


def _get_facade() -> _SearchFacade:
    return _FACADE


# --- Router ----------------------------------------------------------------


router = APIRouter()
builder = ActionRouterBuilder(router)

common_tags = ("Search",)


builder.add_actions(
    [
        ActionSpec(
            name="search_logs",
            method="GET",
            path="/logs",
            summary="Полнотекстовый поиск по audit-логам",
            service_getter=_get_facade,
            service_method="search_logs",
            query_model=LogsSearchQuery,
            argument_aliases={"from": "from_", "to": "to_"},
            tags=common_tags,
        ),
        ActionSpec(
            name="search_orders",
            method="GET",
            path="/orders",
            summary="Поиск по заказам",
            service_getter=_get_facade,
            service_method="search_orders",
            query_model=OrdersSearchQuery,
            argument_aliases={"from": "from_", "to": "to_"},
            tags=common_tags,
        ),
        ActionSpec(
            name="search_notebooks",
            method="GET",
            path="/notebooks",
            summary="Поиск по notebooks",
            service_getter=_get_facade,
            service_method="search_notebooks",
            query_model=NotebooksSearchQuery,
            tags=common_tags,
        ),
        ActionSpec(
            name="search_aggregations",
            method="GET",
            path="/aggregations",
            summary="Terms-агрегация по полю",
            service_getter=_get_facade,
            service_method="aggregate",
            query_model=AggregationsQuery,
            tags=common_tags,
        ),
        ActionSpec(
            name="search_facets",
            method="GET",
            path="/facets/{index}",
            summary="Facets/aggregations для UI-faceting",
            service_getter=_get_facade,
            service_method="facets",
            path_model=FacetsPath,
            query_model=FacetsQuery,
            tags=common_tags,
        ),
    ]
)
