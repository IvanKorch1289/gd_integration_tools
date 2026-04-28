"""Единый поисковый API поверх Elasticsearch (Wave 9.3.3).

Эндпоинты ``/api/v1/search/*`` — полнотекст по audit-логам, заказам,
notebooks. Если индекс отсутствует или ES недоступен — возвращается
пустой массив (а не 5xx), чтобы UI оставался работоспособным.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query

from src.services.io.search import get_search_service

__all__ = ("router",)

logger = logging.getLogger(__name__)

router = APIRouter()


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


@router.get("/logs")
async def search_logs(
    q: str | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    tenant_id: str | None = Query(default=None),
    from_: datetime | None = Query(default=None, alias="from"),
    to_: datetime | None = Query(default=None, alias="to"),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    """Полнотекстовый поиск по audit-логам (индекс ``gd_audit_logs``)."""
    range_filter: dict[str, dict[str, Any]] = {}
    if from_ is not None or to_ is not None:
        when_range: dict[str, Any] = {}
        if from_ is not None:
            when_range["gte"] = from_.isoformat()
        if to_ is not None:
            when_range["lte"] = to_.isoformat()
        range_filter["when"] = when_range

    query = _build_text_query(
        q,
        fields=["who", "what", "entity_id", "action"],
        filters={"entity_type": entity_type, "tenant_id": tenant_id},
        range_filter=range_filter,
    )
    return await _safe_search(
        "audit_logs", query, limit=limit, offset=offset, sort=[{"when": "desc"}]
    )


@router.get("/orders")
async def search_orders(
    q: str | None = Query(default=None),
    status: str | None = Query(default=None),
    from_: datetime | None = Query(default=None, alias="from"),
    to_: datetime | None = Query(default=None, alias="to"),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    """Поиск по заказам (индекс ``gd_orders``)."""
    range_filter: dict[str, dict[str, Any]] = {}
    if from_ is not None or to_ is not None:
        created_range: dict[str, Any] = {}
        if from_ is not None:
            created_range["gte"] = from_.isoformat()
        if to_ is not None:
            created_range["lte"] = to_.isoformat()
        range_filter["created_at"] = created_range

    query = _build_text_query(
        q,
        fields=["pledge_gd_id", "order_kind_id"],
        filters={"status": status},
        range_filter=range_filter,
    )
    return await _safe_search(
        "orders", query, limit=limit, offset=offset, sort=[{"created_at": "desc"}]
    )


@router.get("/notebooks")
async def search_notebooks(
    q: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    """Поиск по notebooks (индекс ``gd_notebooks``)."""
    query = _build_text_query(q, fields=["title", "content"], filters={"tags": tag})
    return await _safe_search(
        "notebooks", query, limit=limit, offset=offset, sort=[{"updated_at": "desc"}]
    )


@router.get("/aggregations")
async def aggregations(
    index: str = Query(...),
    field: str = Query(...),
    q: str | None = Query(default=None),
    size: int = Query(default=10, ge=1, le=100),
) -> dict[str, Any]:
    """Простая terms-агрегация по указанному полю."""
    try:
        service = get_search_service()
        aggs = {"by_field": {"terms": {"field": field, "size": size}}}
        es_query = _build_text_query(q) if q else None
        return await service.aggregate(index, aggs, query=es_query)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Aggregation failed for %s: %s", index, exc)
        return {}
