"""Парсер Postman Collection v2.1 → упрощённый dict для ``pydantic_gen``.

Postman-коллекции не несут строгих JSON Schema, поэтому извлекаем
модели из полей ``request.body.raw`` / ``response.body`` (если есть
``example``) через эвристическое определение типов.

Ограничения первой итерации (Wave 3.4):
* поддерживается только ``body.mode = 'raw'`` с JSON-телом;
* вложенные схемы в ``urlencoded`` / ``form-data`` — TODO;
* массивы-примитивы → ``list[<type>]``, массивы dict-ов →
  inline ``dict[str, Any]`` (можно углубить позже).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

__all__ = ("parse_postman", "ParsedPostman")


class ParsedPostman(dict[str, Any]):
    """Лёгкая обёртка вокруг dict."""


def parse_postman(path: str | Path) -> ParsedPostman:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    info = raw.get("info", {}) or {}
    routes: list[dict[str, Any]] = []
    schemas: dict[str, dict[str, Any]] = {}
    _walk_items(raw.get("item", []) or [], prefix=[], routes=routes, schemas=schemas)
    return ParsedPostman(
        {
            "title": info.get("name", "Postman Collection"),
            "version": info.get("version", "1.0.0"),
            "schemas": schemas,
            "routes": routes,
            "source": str(path),
        }
    )


def _walk_items(
    items: list[dict[str, Any]],
    *,
    prefix: list[str],
    routes: list[dict[str, Any]],
    schemas: dict[str, dict[str, Any]],
) -> None:
    for item in items:
        if "item" in item and isinstance(item["item"], list):
            _walk_items(
                item["item"],
                prefix=[*prefix, str(item.get("name", ""))],
                routes=routes,
                schemas=schemas,
            )
            continue
        request = item.get("request")
        if not isinstance(request, dict):
            continue
        name = _slug([*prefix, str(item.get("name", "Request"))])
        method = str(request.get("method", "GET")).upper()
        url = _url_to_path(request.get("url"))

        body_model = None
        body = request.get("body") or {}
        if body.get("mode") == "raw" and body.get("raw"):
            try:
                parsed = json.loads(body["raw"])
                schema = _infer_schema(parsed)
                if schema.get("type") == "object":
                    body_model = f"{name}Request"
                    schemas[body_model] = schema
            except json.JSONDecodeError:
                pass

        response_model = None
        for resp in item.get("response") or []:
            raw_body = resp.get("body")
            if not raw_body:
                continue
            try:
                parsed = json.loads(raw_body)
                schema = _infer_schema(parsed)
                if schema.get("type") == "object":
                    response_model = f"{name}Response"
                    schemas[response_model] = schema
                    break
            except (json.JSONDecodeError, TypeError):
                continue

        routes.append(
            {
                "method": method,
                "path": url,
                "operation_id": name,
                "summary": item.get("name", ""),
                "tags": prefix,
                "request_body_ref": body_model,
                "responses_ref": response_model,
            }
        )


def _url_to_path(url: Any) -> str:
    if isinstance(url, dict):
        parts = url.get("path") or []
        return "/" + "/".join(str(p) for p in parts)
    if isinstance(url, str):
        return url
    return "/"


def _slug(parts: list[str]) -> str:
    raw = " ".join(p for p in parts if p).strip()
    if not raw:
        return "Anon"
    chunks: list[str] = []
    buf = ""
    for c in raw:
        if c.isalnum():
            buf += c
        else:
            if buf:
                chunks.append(buf)
                buf = ""
    if buf:
        chunks.append(buf)
    pascal = "".join(c[:1].upper() + c[1:] for c in chunks)
    return pascal or "Anon"


def _infer_schema(value: Any) -> dict[str, Any]:
    """Эвристика: JSON-значение → approximate JSON Schema dict."""
    if isinstance(value, dict):
        props = {k: _infer_schema(v) for k, v in value.items()}
        return {"type": "object", "properties": props, "required": list(props.keys())}
    if isinstance(value, list):
        if not value:
            return {"type": "array", "items": {"type": "string"}}
        return {"type": "array", "items": _infer_schema(value[0])}
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if value is None:
        return {"type": "null"}
    return {"type": "string"}
