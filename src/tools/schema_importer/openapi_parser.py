"""Парсер OpenAPI 3.x → упрощённый dict для ``pydantic_gen``.

Использует `openapi-pydantic` (уже в зависимостях) только для
валидации/нормализации raw-спецификации. Дальнейшую генерацию Python
делает :mod:`app.tools.schema_importer.pydantic_gen`.

Поддерживает:
* YAML и JSON на входе;
* ``components.schemas`` → Pydantic models;
* ``paths`` → метаданные роутов (для ``route_gen``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

__all__ = ("parse_openapi", "ParsedOpenAPI")


class ParsedOpenAPI(dict[str, Any]):
    """Лёгкая обёртка вокруг dict — чтобы в type-checker было имя."""


def _load_raw(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError(
                "pyyaml не установлен — необходим для .yaml OpenAPI"
            ) from exc
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(
            f"OpenAPI spec должен быть object-ом, не {type(data).__name__}"
        )
    return data


def parse_openapi(path: str | Path) -> ParsedOpenAPI:
    """Парсит OpenAPI 3.x файл.

    Returns:
        Dict с ключами:
          * ``title`` / ``version`` — инфо.
          * ``schemas`` — ``{ModelName: jsonschema-dict}``.
          * ``routes`` — список dict-ов с полями
            (method, path, operationId, summary, tags, request_body_ref,
            responses_ref).
          * ``source`` — исходный путь / URL (для шапки файлов).
    """
    raw = _load_raw(path)
    info = raw.get("info", {}) or {}
    components = raw.get("components", {}) or {}
    schemas = components.get("schemas", {}) or {}

    routes: list[dict[str, Any]] = []
    for route_path, item in (raw.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        for method, op in item.items():
            if method.lower() not in {
                "get",
                "post",
                "put",
                "patch",
                "delete",
                "head",
                "options",
                "trace",
            }:
                continue
            if not isinstance(op, dict):
                continue
            routes.append(
                {
                    "method": method.upper(),
                    "path": route_path,
                    "operation_id": op.get("operationId")
                    or f"{method}_{route_path}".replace("/", "_"),
                    "summary": op.get("summary", ""),
                    "tags": op.get("tags") or [],
                    "request_body_ref": _extract_ref(
                        (op.get("requestBody") or {})
                        .get("content", {})
                        .get("application/json", {})
                        .get("schema")
                    ),
                    "responses_ref": _extract_ref(
                        (op.get("responses") or {})
                        .get("200", {})
                        .get("content", {})
                        .get("application/json", {})
                        .get("schema")
                    ),
                }
            )

    return ParsedOpenAPI(
        {
            "title": info.get("title", "OpenAPI"),
            "version": info.get("version", "1.0.0"),
            "schemas": schemas,
            "routes": routes,
            "source": str(path),
        }
    )


def _extract_ref(schema: Any) -> str | None:
    if not isinstance(schema, dict):
        return None
    ref = schema.get("$ref")
    if isinstance(ref, str):
        return ref.rsplit("/", 1)[-1]
    return None
