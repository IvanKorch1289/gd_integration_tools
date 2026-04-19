"""Эндпоинты для просмотра gRPC proto-схем.

Предоставляет HTTP-доступ к содержимому .proto файлов
и структурированному описанию gRPC-сервисов.
"""

import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

__all__ = ("proto_viewer_router",)

proto_viewer_router = APIRouter(prefix="/grpc", tags=["gRPC"])

_PROTO_DIR = Path(__file__).parent / "protobuf"


def _parse_proto(content: str) -> dict[str, Any]:
    """Парсит .proto файл и возвращает структурированное описание."""
    services: list[dict[str, Any]] = []
    messages: list[dict[str, Any]] = []

    # Парсинг сервисов и RPC-методов
    for svc_match in re.finditer(
        r"service\s+(\w+)\s*\{([^}]+)\}", content, re.DOTALL
    ):
        svc_name = svc_match.group(1)
        svc_body = svc_match.group(2)
        methods = []
        for rpc_match in re.finditer(
            r"rpc\s+(\w+)\s*\(\s*(\w+)\s*\)\s*returns\s*\(\s*(\w+)\s*\)",
            svc_body,
        ):
            methods.append(
                {
                    "name": rpc_match.group(1),
                    "request": rpc_match.group(2),
                    "response": rpc_match.group(3),
                }
            )
        services.append({"name": svc_name, "methods": methods})

    # Парсинг сообщений
    for msg_match in re.finditer(
        r"message\s+(\w+)\s*\{([^}]+)\}", content, re.DOTALL
    ):
        msg_name = msg_match.group(1)
        msg_body = msg_match.group(2)
        fields = []
        for field_match in re.finditer(
            r"(\w+)\s+(\w+)\s*=\s*(\d+)", msg_body
        ):
            fields.append(
                {
                    "type": field_match.group(1),
                    "name": field_match.group(2),
                    "number": int(field_match.group(3)),
                }
            )
        messages.append({"name": msg_name, "fields": fields})

    return {"services": services, "messages": messages}


@proto_viewer_router.get(
    "/schema",
    response_class=PlainTextResponse,
    summary="Содержимое .proto файлов",
)
async def get_proto_schema() -> PlainTextResponse:
    """Возвращает объединённое содержимое всех .proto файлов."""
    parts: list[str] = []
    for proto_file in sorted(_PROTO_DIR.glob("*.proto")):
        parts.append(f"// === {proto_file.name} ===\n")
        parts.append(proto_file.read_text(encoding="utf-8"))
        parts.append("\n")
    return PlainTextResponse("".join(parts) if parts else "No .proto files found")


@proto_viewer_router.get(
    "/schema/json",
    summary="Структурированное описание gRPC-сервисов",
)
async def get_proto_schema_json() -> dict[str, Any]:
    """Возвращает JSON-описание всех сервисов, методов и сообщений."""
    result: dict[str, Any] = {"files": []}
    for proto_file in sorted(_PROTO_DIR.glob("*.proto")):
        content = proto_file.read_text(encoding="utf-8")
        parsed = _parse_proto(content)
        result["files"].append({"filename": proto_file.name, **parsed})
    return result
