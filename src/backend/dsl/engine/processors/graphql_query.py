"""DSL-шаг ``graphql_query`` — execute GraphQL queries/mutations from DSL pipeline.

Wave: ``[wave:net/graphql]``. Provides a Camel-style component for executing
GraphQL queries against any GraphQL endpoint.

Usage (Python builder)::

    builder.graphql_query(
        endpoint="https://api.example.com/graphql",
        query="{ user(id: $id) { name email } }",
        variables={"id": 123},
        auth_token="${secrets.graphql_token}",
        result_property="graphql_result",
    )

YAML::

    - graphql_query:
        endpoint: "https://api.example.com/graphql"
        query: "{ user(id: $id) { name email } }"
        variables:
          id: 123
        auth_token: "${secrets.graphql_token}"
        result_property: graphql_result
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import orjson

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import processor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = ("GraphQLQueryProcessor",)

_logger = get_logger(__name__)


@processor(
    "graphql_query",
    namespace="core",
    spec_schema={
        "type": "object",
        "properties": {
            "endpoint": {"type": "string"},
            "query": {"type": "string"},
            "variables": {"type": "object"},
            "operation_name": {"type": "string"},
            "headers": {"type": "object"},
            "auth_token": {"type": "string"},
            "auth_header": {"type": "string"},
            "timeout": {"type": "number"},
            "result_property": {"type": "string"},
        },
        "required": ["endpoint", "query"],
    },
    capabilities=("net.outbound.*:external",),
    meta={"tier": 1, "category": "transport"},
)
class GraphQLQueryProcessor(BaseProcessor):
    """Camel GraphQL Component — execute GraphQL queries/mutations from DSL pipeline.

    Supports POST requests with query, variables, operationName, and custom headers.
    Authentication via Bearer token or custom auth header.
    """

    def __init__(
        self,
        endpoint: str,
        query: str,
        *,
        variables: dict[str, Any] | None = None,
        operation_name: str | None = None,
        headers: dict[str, str] | None = None,
        auth_token: str | None = None,
        auth_header: str = "Authorization",
        timeout: float = 30.0,
        result_property: str | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"graphql:{endpoint[:40]}")
        self._endpoint = endpoint
        self._query = query
        self._variables = variables or {}
        self._operation_name = operation_name
        self._headers = headers or {}
        self._auth_token = auth_token
        self._auth_header = auth_header
        self._timeout = timeout
        self._result_property = result_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Выполняет GraphQL-запрос (POST) и записывает результат в exchange.

        Формирует GraphQL payload (query, variables, operationName), добавляет
        auth и content-type заголовки, отправляет POST через httpx. Проверяет
        HTTP-статус, парсит JSON, обнаруживает GraphQL-level errors.

        Args:
            exchange: Текущий exchange; результат (data) — в ``out_message``
                или свойстве ``result_property``.
            context: Контекст выполнения маршрута.
        """
        from src.backend.infrastructure.clients.transport.http_httpx import (
            get_httpx_client,
        )

        client = get_httpx_client()

        # Build GraphQL payload
        payload: dict[str, Any] = {"query": self._query}
        if self._variables:
            payload["variables"] = self._variables
        if self._operation_name:
            payload["operationName"] = self._operation_name

        # Build headers
        req_headers = dict(self._headers)
        if self._auth_token:
            req_headers[self._auth_header] = f"Bearer {self._auth_token}"
        req_headers.setdefault("content-type", "application/json")
        req_headers.setdefault("accept", "application/json")

        try:
            response = await client.request(
                method="POST", url=self._endpoint, headers=req_headers, json=payload
            )

            # Parse response
            if response.status_code >= 400:
                error_body = response.text
                exchange.fail(
                    f"GraphQL request failed with status {response.status_code}: {error_body}"
                )
                return

            try:
                result = orjson.loads(response.text)
            except orjson.JSONDecodeError as exc:
                exchange.fail(
                    f"GraphQL response is not valid JSON: {exc}\nResponse: {response.text[:500]}"
                )
                return

            # Check for GraphQL-level errors
            if isinstance(result, dict) and "errors" in result:
                errors = result["errors"]
                error_messages = [e.get("message", str(e)) for e in errors]
                exchange.fail(f"GraphQL errors: {'; '.join(error_messages)}")
                return

            # Write result
            if self._result_property:
                exchange.set_property(self._result_property, result)
            exchange.set_out(body=result, headers=dict(exchange.in_message.headers))

        except Exception as exc:
            exchange.fail(f"GraphQL query failed: {exc}")

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализация в YAML: endpoint + query + опц. variables/operation_name."""
        spec: dict[str, Any] = {"endpoint": self._endpoint, "query": self._query}
        if self._variables:
            spec["variables"] = self._variables
        if self._operation_name:
            spec["operation_name"] = self._operation_name
        if self._headers:
            spec["headers"] = self._headers
        if self._auth_token:
            spec["auth_token"] = "<redacted>"  # noqa: S105  # config field name, not a password
        if self._auth_header != "Authorization":
            spec["auth_header"] = self._auth_header
        if self._timeout != 30.0:
            spec["timeout"] = self._timeout
        if self._result_property:
            spec["result_property"] = self._result_property
        return {"graphql_query": spec}
