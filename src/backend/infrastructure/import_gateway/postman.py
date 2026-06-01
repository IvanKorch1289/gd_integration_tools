"""W24 — Postman Collection v2.1 → ``ConnectorSpec``.

Заменяет legacy ``src/dsl/importers/postman_parser.py`` и
``src/tools/schema_importer/postman_parser.py`` (унификация).

Поддерживается v2.1.0 формат (``info.schema`` ≈
``https://schema.getpostman.com/json/collection/v2.1.0/collection.json``).
Folders → tags + dot-prefix в operation_id. Auth (Bearer/Basic/API-key)
из ``request.auth`` собирается в ``AuthSpec`` с ``SecretRef``-ами.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

import orjson

from src.backend.core.interfaces.import_gateway import ImportSource, ImportSourceKind
from src.backend.core.models.connector_spec import (
    AuthSchemeKind,
    AuthSpec,
    ConnectorSpec,
    EndpointSpec,
    SecretRef,
)

__all__ = ("PostmanImportGateway",)

logger = logging.getLogger("infrastructure.import_gateway.postman")

_ID_PATTERN = re.compile(r"[^a-zA-Z0-9]+")


def _sanitize_id(name: str) -> str:
    return _ID_PATTERN.sub("_", name.strip().lower()).strip("_") or "unnamed"


class PostmanImportGateway:
    """Backend для импорта Postman Collection v2.1."""

    kind: ImportSourceKind = ImportSourceKind.POSTMAN

    async def import_spec(self, source: ImportSource) -> ConnectorSpec:
        """Распарсить Postman collection → ConnectorSpec."""
        raw = (
            source.content
            if isinstance(source.content, bytes)
            else source.content.encode()
        )
        try:
            data = orjson.loads(raw)
        except orjson.JSONDecodeError as exc:
            raise ImportError(f"Postman: невалидный JSON: {exc}") from exc

        if not isinstance(data, dict) or "info" not in data:
            raise ValueError(
                "Postman: отсутствует поле 'info' (некорректная коллекция)"
            )

        info = data.get("info", {})
        schema = info.get("schema", "")
        if "v2.1" not in schema:
            logger.warning(
                "Postman schema not v2.1: %r — продолжаем best-effort", schema
            )

        title = info.get("name") or "postman_collection"
        version = info.get("version") or info.get("_postman_id") or ""
        connector_name = _sanitize_id(title)

        # Auth на уровне коллекции (можно переопределять в request).
        connector_auth = self._parse_auth(data.get("auth"))

        endpoints: list[EndpointSpec] = []
        items = data.get("item", []) or []
        self._walk_items(items, source.prefix, endpoints, folder_path="")

        if not endpoints:
            raise ValueError("Postman: в коллекции нет ни одного запроса")

        spec_hash = hashlib.sha256(raw).hexdigest()

        return ConnectorSpec(
            name=connector_name,
            title=title,
            version=str(version),
            base_url=self._guess_base_url(endpoints),
            endpoints=endpoints,
            auth=connector_auth,
            schemas={},
            source_kind=self.kind.value,
            source_hash=spec_hash,
            source_url=source.source_url,
            metadata=dict(source.metadata),
        )

    def _walk_items(
        self,
        items: list[dict[str, Any]],
        prefix: str,
        out: list[EndpointSpec],
        folder_path: str,
    ) -> None:
        for item in items:
            if "item" in item:
                folder = _sanitize_id(item.get("name", ""))
                new_path = f"{folder_path}.{folder}" if folder_path else folder
                self._walk_items(item["item"], prefix, out, new_path)
                continue
            ep = self._parse_request(item, prefix, folder_path)
            if ep:
                out.append(ep)

    def _parse_request(
        self, item: dict[str, Any], prefix: str, folder_path: str
    ) -> EndpointSpec | None:
        request = item.get("request")
        if not request:
            return None

        raw_name = item.get("name", "request")
        name = _sanitize_id(raw_name)
        op_parts = [prefix]
        if folder_path:
            op_parts.append(folder_path)
        op_parts.append(name)
        operation_id = ".".join(op_parts)

        method = (request.get("method") or "GET").upper()
        url_obj = request.get("url", "")
        if isinstance(url_obj, dict):
            url = url_obj.get("raw", "")
        else:
            url = str(url_obj)

        headers = [
            {"name": h["key"], "in": "header", "default": h.get("value", "")}
            for h in request.get("header", []) or []
            if h.get("key") and not h.get("disabled")
        ]

        body_obj = request.get("body") or {}
        request_schema = self._extract_body_schema(body_obj)

        tags: list[str] = list(folder_path.split(".")) if folder_path else []

        return EndpointSpec(
            operation_id=operation_id,
            method=method,
            path=url,
            summary=item.get("description") or raw_name,
            parameters=headers,
            request_schema=request_schema,
            response_schema=None,
            tags=tags,
        )

    @staticmethod
    def _extract_body_schema(body_obj: dict[str, Any]) -> dict[str, Any] | None:
        mode = body_obj.get("mode")
        if mode == "raw":
            raw = body_obj.get("raw")
            if not raw:
                return None
            try:
                parsed = orjson.loads(raw)
            except orjson.JSONDecodeError:
                return {"type": "string", "example": raw}
            return {"type": "object", "example": parsed}
        if mode == "urlencoded":
            return {
                "type": "object",
                "properties": {
                    p["key"]: {"type": "string"}
                    for p in body_obj.get("urlencoded", [])
                    if p.get("key")
                },
            }
        return None

    @staticmethod
    def _parse_auth(auth_obj: dict[str, Any] | None) -> AuthSpec | None:
        if not auth_obj:
            return None
        auth_type = auth_obj.get("type", "")
        if auth_type == "bearer":
            return AuthSpec(
                kind=AuthSchemeKind.BEARER,
                location="header",
                param_name="Authorization",
                secret_refs={
                    "token": SecretRef(
                        ref="${POSTMAN_BEARER_TOKEN}",
                        hint="Bearer-токен из Postman environment",
                    )
                },
            )
        if auth_type == "basic":
            return AuthSpec(
                kind=AuthSchemeKind.BASIC,
                secret_refs={
                    "username": SecretRef(
                        ref="${POSTMAN_BASIC_USERNAME}", hint="Basic auth user"
                    ),
                    "password": SecretRef(
                        ref="${POSTMAN_BASIC_PASSWORD}", hint="Basic auth pass"
                    ),
                },
            )
        if auth_type == "apikey":
            params = {
                p["key"]: p.get("value", "")
                for p in auth_obj.get("apikey", [])
                if p.get("key")
            }
            return AuthSpec(
                kind=AuthSchemeKind.API_KEY,
                location=params.get("in", "header"),
                param_name=params.get("key", "X-API-Key"),
                secret_refs={
                    "value": SecretRef(ref="${POSTMAN_API_KEY}", hint="API-key value")
                },
            )
        if auth_type == "oauth2":
            return AuthSpec(
                kind=AuthSchemeKind.OAUTH2,
                secret_refs={
                    "access_token": SecretRef(
                        ref="${POSTMAN_OAUTH2_TOKEN}", hint="OAuth2 access token"
                    )
                },
            )
        return None

    @staticmethod
    def _guess_base_url(endpoints: list[EndpointSpec]) -> str:
        """Извлекает общий префикс URL из endpoint-ов (best-effort)."""
        if not endpoints:
            return ""
        urls = [ep.path for ep in endpoints if ep.path]
        if not urls:
            return ""
        prefix = urls[0]
        for url in urls[1:]:
            i = 0
            while i < min(len(prefix), len(url)) and prefix[i] == url[i]:
                i += 1
            prefix = prefix[:i]
        return prefix.rstrip("/?&")
