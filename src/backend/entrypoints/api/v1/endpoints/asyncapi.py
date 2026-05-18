"""REST endpoint: ``GET /api/v1/asyncapi.{yaml,json}``.

Возвращает AsyncAPI 3.0 спецификацию FastStream-источников
(Redis / RabbitMQ / Kafka). Используется внешними клиентами
(studio.asyncapi.com, кодогенерация) и developer portal.
"""

from __future__ import annotations

from fastapi import APIRouter, Response

from src.backend.entrypoints.asyncapi import (
    build_asyncapi_json,
    build_asyncapi_yaml,
)

__all__ = ("router",)


router = APIRouter()


@router.get(
    "/asyncapi.yaml",
    summary="AsyncAPI 3.0 (YAML)",
    description=(
        "Возвращает спецификацию AsyncAPI 3.0 для FastStream-источников. "
        "Импортируется в studio.asyncapi.com и используется кодогенерацией."
    ),
    response_class=Response,
    responses={
        200: {
            "content": {"application/yaml": {}},
            "description": "AsyncAPI 3.0 YAML",
        }
    },
)
async def get_asyncapi_yaml() -> Response:
    """Эндпоинт YAML."""
    payload = build_asyncapi_yaml()
    return Response(content=payload, media_type="application/yaml")


@router.get(
    "/asyncapi.json",
    summary="AsyncAPI 3.0 (JSON)",
    description="JSON-вариант AsyncAPI 3.0 спецификации.",
    response_class=Response,
    responses={
        200: {
            "content": {"application/json": {}},
            "description": "AsyncAPI 3.0 JSON",
        }
    },
)
async def get_asyncapi_json() -> Response:
    """Эндпоинт JSON."""
    payload = build_asyncapi_json()
    return Response(content=payload, media_type="application/json")
