"""W24 — OpenAPI 3.x → ``ConnectorSpec`` через openapi-pydantic.

Заменяет legacy ``src/dsl/importers/openapi_parser.py`` и
``src/tools/schema_importer/openapi_parser.py`` (унификация).

Используется ``openapi-pydantic`` (v3.0 + v3.1 модели). $ref резолвится
встроенно через Pydantic-валидацию. Security schemes (Bearer/Basic/
ApiKey/OAuth2) маппятся в :class:`AuthSpec` с :class:`SecretRef`-ами;
сами значения секретов в spec'е НЕ хранятся.
"""

from __future__ import annotations

import hashlib
import logging
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

__all__ = ("OpenAPIImportGateway",)

logger = logging.getLogger("infrastructure.import_gateway.openapi")


class OpenAPIImportGateway:
    """Backend для импорта OpenAPI 3.0 / 3.1 spec'ов."""

    kind: ImportSourceKind = ImportSourceKind.OPENAPI

    async def import_spec(self, source: ImportSource) -> ConnectorSpec:
        raw = (
            source.content
            if isinstance(source.content, bytes)
            else source.content.encode()
        )
        data = self._parse_text(raw)

        version_str = str(data.get("openapi", ""))
        if version_str.startswith("3.1"):
            from openapi_pydantic.v3.v3_1 import OpenAPI as OpenAPIModel
        elif version_str.startswith("3.0") or not version_str:
            from openapi_pydantic.v3.v3_0 import OpenAPI as OpenAPIModel
        else:
            raise ValueError(
                f"OpenAPI: неподдерживаемая версия {version_str!r} "
                "(ожидается 3.0.x или 3.1.x)"
            )

        try:
            spec = OpenAPIModel.model_validate(data)
        except Exception as exc:
            raise ImportError(f"OpenAPI: не удалось валидировать spec: {exc}") from exc

        info = spec.info
        title = info.title or "openapi_connector"
        version = info.version or ""
        connector_name = self._sanitize_name(title)

        servers = spec.servers or []
        base_url = servers[0].url if servers else ""

        endpoints: list[EndpointSpec] = []
        for path, path_item in (spec.paths or {}).items():
            for http_method in (
                "get",
                "post",
                "put",
                "patch",
                "delete",
                "head",
                "options",
            ):
                operation = getattr(path_item, http_method, None)
                if operation is None:
                    continue
                ep = self._build_endpoint(
                    prefix=source.prefix,
                    method=http_method,
                    path=path,
                    operation=operation,
                )
                endpoints.append(ep)

        if not endpoints:
            raise ValueError("OpenAPI: spec не содержит ни одного operation")

        components = spec.components
        schemas = self._extract_schemas(components)

        auth = self._extract_auth(components, spec.security)

        spec_hash = hashlib.sha256(raw).hexdigest()

        return ConnectorSpec(
            name=connector_name,
            title=title,
            version=version,
            base_url=base_url,
            endpoints=endpoints,
            auth=auth,
            schemas=schemas,
            source_kind=self.kind.value,
            source_hash=spec_hash,
            source_url=source.source_url,
            metadata={"openapi_version": version_str, **dict(source.metadata)},
        )

    @staticmethod
    def _parse_text(raw: bytes) -> dict[str, Any]:
        try:
            return orjson.loads(raw)
        except orjson.JSONDecodeError:
            try:
                import yaml

                parsed = yaml.safe_load(raw)
            except Exception as exc:
                raise ImportError(f"OpenAPI: невалидный JSON/YAML: {exc}") from exc
            if not isinstance(parsed, dict):
                raise ImportError("OpenAPI: распарсенный документ не является dict")
            return parsed

    @staticmethod
    def _sanitize_name(title: str) -> str:
        import re

        return (
            re.sub(r"[^a-zA-Z0-9_]+", "_", title.strip().lower()).strip("_")
            or "openapi"
        )

    def _build_endpoint(
        self, *, prefix: str, method: str, path: str, operation: Any
    ) -> EndpointSpec:
        op_id = operation.operationId or f"{method}_{path.replace('/', '_').strip('_')}"
        operation_id = f"{prefix}.{op_id}"

        params: list[dict[str, Any]] = []
        for p in operation.parameters or []:
            try:
                params.append(p.model_dump(mode="json", exclude_none=True))
            except AttributeError:
                continue

        request_schema: dict[str, Any] | None = None
        if operation.requestBody is not None:
            try:
                rb = operation.requestBody.model_dump(mode="json", exclude_none=True)
                content = rb.get("content", {})
                json_content = content.get("application/json", {})
                request_schema = json_content.get("schema")
            except AttributeError:
                request_schema = None

        response_schema: dict[str, Any] | None = None
        for code in ("200", "201", "default"):
            resp = (operation.responses or {}).get(code)
            if resp is None:
                continue
            try:
                resp_dump = resp.model_dump(mode="json", exclude_none=True)
                content = resp_dump.get("content", {})
                json_content = content.get("application/json", {})
                response_schema = json_content.get("schema")
                if response_schema:
                    break
            except AttributeError:
                continue

        return EndpointSpec(
            operation_id=operation_id,
            method=method.upper(),
            path=path,
            summary=operation.summary or "",
            parameters=params,
            request_schema=request_schema,
            response_schema=response_schema,
            tags=list(operation.tags or []),
        )

    @staticmethod
    def _extract_schemas(components: Any) -> dict[str, Any]:
        if components is None or components.schemas is None:
            return {}
        result: dict[str, Any] = {}
        for name, schema in components.schemas.items():
            try:
                result[name] = schema.model_dump(mode="json", exclude_none=True)
            except AttributeError:
                result[name] = schema
        return result

    @staticmethod
    def _extract_auth(components: Any, security: Any) -> AuthSpec | None:
        """Маппинг первой security-scheme в AuthSpec.

        Если security-схем несколько — берём первую (первая в global security
        переопределяет alphabet-order). Сами значения секретов идут в
        SecretRef-ы для последующей загрузки через SecretsBackend.
        """
        if components is None or not components.securitySchemes:
            return None

        # Если есть global security — берём имя первой схемы оттуда.
        scheme_name: str | None = None
        if security:
            first = security[0]
            if hasattr(first, "model_dump"):
                first = first.model_dump(mode="json")
            if isinstance(first, dict) and first:
                scheme_name = next(iter(first.keys()))

        scheme_name = scheme_name or next(iter(components.securitySchemes))
        scheme = components.securitySchemes[scheme_name]

        scheme_type = (getattr(scheme, "type", "") or "").lower()
        if scheme_type == "http":
            http_scheme = (getattr(scheme, "scheme", "") or "").lower()
            if http_scheme == "bearer":
                return AuthSpec(
                    kind=AuthSchemeKind.BEARER,
                    location="header",
                    param_name="Authorization",
                    secret_refs={
                        "token": SecretRef(
                            ref=f"${{OPENAPI_{scheme_name.upper()}_TOKEN}}",
                            hint=f"Bearer-токен для security scheme '{scheme_name}'",
                        )
                    },
                )
            if http_scheme == "basic":
                return AuthSpec(
                    kind=AuthSchemeKind.BASIC,
                    secret_refs={
                        "username": SecretRef(
                            ref=f"${{OPENAPI_{scheme_name.upper()}_USERNAME}}",
                            hint="Basic auth username",
                        ),
                        "password": SecretRef(
                            ref=f"${{OPENAPI_{scheme_name.upper()}_PASSWORD}}",
                            hint="Basic auth password",
                        ),
                    },
                )
        if scheme_type == "apikey":
            return AuthSpec(
                kind=AuthSchemeKind.API_KEY,
                location=getattr(scheme, "security_scheme_in", "header") or "header",
                param_name=getattr(scheme, "name", "X-API-Key") or "X-API-Key",
                secret_refs={
                    "value": SecretRef(
                        ref=f"${{OPENAPI_{scheme_name.upper()}_VALUE}}",
                        hint=f"API-key value для '{scheme_name}'",
                    )
                },
            )
        if scheme_type == "oauth2":
            scopes: list[str] = []
            flows = getattr(scheme, "flows", None)
            if flows is not None:
                for flow_name in (
                    "implicit",
                    "password",
                    "clientCredentials",
                    "authorizationCode",
                ):
                    flow = getattr(flows, flow_name, None)
                    if flow and getattr(flow, "scopes", None):
                        scopes.extend(flow.scopes.keys())
                        break
            return AuthSpec(
                kind=AuthSchemeKind.OAUTH2,
                secret_refs={
                    "access_token": SecretRef(
                        ref=f"${{OPENAPI_{scheme_name.upper()}_ACCESS_TOKEN}}",
                        hint=f"OAuth2 access token для '{scheme_name}'",
                    )
                },
                scopes=scopes,
            )
        return None
