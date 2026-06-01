"""Unit tests for GraphQLQueryProcessor."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.engine.processors.graphql_query import GraphQLQueryProcessor


# --------------------------------------------------------------------------- #
# Stubs
# --------------------------------------------------------------------------- #

class _Message:
    """Minimal Message stub matching the Message interface used by processors."""

    def __init__(self, body: Any = None) -> None:
        self.body = body
        self.headers: dict[str, Any] = {}

    def set_body(self, value: Any) -> None:
        self.body = value


class _Exchange:
    """Minimal exchange stub: only properties dict + in_message body."""

    def __init__(self, properties: dict[str, Any] | None = None) -> None:
        self.properties = properties or {}
        self.in_message = _Message()
        self.out_message: _Message | None = None
        self.error: str | None = None

    def set_property(self, key: str, value: Any) -> None:
        self.properties[key] = value

    def set_out(self, body: Any = None, headers: dict[str, Any] | None = None) -> None:
        self.out_message = _Message(body=body)
        if headers:
            self.out_message.headers = headers

    def fail(self, message: str) -> None:
        self.error = message


class _Context:
    """Stub ExecutionContext — processors don't use it directly in these tests."""


# --------------------------------------------------------------------------- #
# GraphQLQueryProcessor
# --------------------------------------------------------------------------- #

class TestGraphQLQueryProcessor:
    """Tests for GraphQLQueryProcessor."""

    def test_init_sets_attributes(self) -> None:
        """Constructor stores all parameters correctly."""
        processor = GraphQLQueryProcessor(
            endpoint="https://api.example.com/graphql",
            query="{ user { name } }",
            variables={"id": 1},
            operation_name="GetUser",
            headers={"X-Custom": "header"},
            auth_token="secret-token",
            auth_header="X-Auth",
            timeout=60.0,
            result_property="gql_result",
        )
        assert processor._endpoint == "https://api.example.com/graphql"
        assert processor._query == "{ user { name } }"
        assert processor._variables == {"id": 1}
        assert processor._operation_name == "GetUser"
        assert processor._headers == {"X-Custom": "header"}
        assert processor._auth_token == "secret-token"
        assert processor._auth_header == "X-Auth"
        assert processor._timeout == 60.0
        assert processor._result_property == "gql_result"

    def test_init_defaults(self) -> None:
        """Optional parameters have correct defaults."""
        processor = GraphQLQueryProcessor(
            endpoint="https://api.example.com/graphql",
            query="{ users { id } }",
        )
        assert processor._variables == {}
        assert processor._operation_name is None
        assert processor._headers == {}
        assert processor._auth_token is None
        assert processor._auth_header == "Authorization"
        assert processor._timeout == 30.0
        assert processor._result_property is None

    @pytest.mark.asyncio
    async def test_successful_query_sets_body(self) -> None:
        """On success, result is written to out_message.body."""
        exchange = _Exchange()
        exchange.in_message.body = {"id": 123}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"data": {"user": {"name": "Alice"}}}'

        with patch(
            "src.backend.infrastructure.clients.transport.http_httpx.get_httpx_client"
        ) as mock_get_client:
            mock_client = MagicMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            processor = GraphQLQueryProcessor(
                endpoint="https://api.example.com/graphql",
                query="{ user(id: $id) { name } }",
                variables={"id": 123},
            )
            await processor.process(exchange, _Context())

        assert exchange.out_message is not None
        assert exchange.out_message.body == {"data": {"user": {"name": "Alice"}}}
        assert exchange.error is None

    @pytest.mark.asyncio
    async def test_successful_query_with_result_property(self) -> None:
        """When result_property is set, result is also written to that property."""
        exchange = _Exchange()
        exchange.in_message.body = {}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"data": {"products": [{"id": 1}, {"id": 2}]}}'

        with patch(
            "src.backend.infrastructure.clients.transport.http_httpx.get_httpx_client"
        ) as mock_get_client:
            mock_client = MagicMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            processor = GraphQLQueryProcessor(
                endpoint="https://api.example.com/graphql",
                query="{ products { id } }",
                result_property="graphql_data",
            )
            await processor.process(exchange, _Context())

        assert exchange.properties["graphql_data"] == {"data": {"products": [{"id": 1}, {"id": 2}]}}
        assert exchange.out_message.body == {"data": {"products": [{"id": 1}, {"id": 2}]}}

    @pytest.mark.asyncio
    async def test_graphql_errors_set_exchange_error(self) -> None:
        """When GraphQL returns errors array, exchange is failed."""
        exchange = _Exchange()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"errors": [{"message": "User not found"}]}'

        with patch(
            "src.backend.infrastructure.clients.transport.http_httpx.get_httpx_client"
        ) as mock_get_client:
            mock_client = MagicMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            processor = GraphQLQueryProcessor(
                endpoint="https://api.example.com/graphql",
                query="{ user(id: 999) { name } }",
            )
            await processor.process(exchange, _Context())

        assert exchange.error is not None
        assert "User not found" in exchange.error

    @pytest.mark.asyncio
    async def test_http_error_sets_exchange_error(self) -> None:
        """When HTTP status >= 400, exchange is failed."""
        exchange = _Exchange()

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch(
            "src.backend.infrastructure.clients.transport.http_httpx.get_httpx_client"
        ) as mock_get_client:
            mock_client = MagicMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            processor = GraphQLQueryProcessor(
                endpoint="https://api.example.com/graphql",
                query="{ users { id } }",
            )
            await processor.process(exchange, _Context())

        assert exchange.error is not None
        assert "500" in exchange.error

    @pytest.mark.asyncio
    async def test_invalid_json_response_sets_exchange_error(self) -> None:
        """When response is not valid JSON, exchange is failed."""
        exchange = _Exchange()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "not json at all"

        with patch(
            "src.backend.infrastructure.clients.transport.http_httpx.get_httpx_client"
        ) as mock_get_client:
            mock_client = MagicMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            processor = GraphQLQueryProcessor(
                endpoint="https://api.example.com/graphql",
                query="{ users { id } }",
            )
            await processor.process(exchange, _Context())

        assert exchange.error is not None
        assert "not valid JSON" in exchange.error

    @pytest.mark.asyncio
    async def test_network_error_sets_exchange_error(self) -> None:
        """When client.request raises, exchange is failed with message."""
        exchange = _Exchange()

        with patch(
            "src.backend.infrastructure.clients.transport.http_httpx.get_httpx_client"
        ) as mock_get_client:
            mock_client = MagicMock()
            mock_client.request = AsyncMock(side_effect=ConnectionError("network failure"))
            mock_get_client.return_value = mock_client

            processor = GraphQLQueryProcessor(
                endpoint="https://api.example.com/graphql",
                query="{ users { id } }",
            )
            await processor.process(exchange, _Context())

        assert exchange.error is not None
        assert "GraphQL query failed" in exchange.error

    @pytest.mark.asyncio
    async def test_auth_header_added_when_token_provided(self) -> None:
        """When auth_token is set, Authorization header is added to request."""
        exchange = _Exchange()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"data": {}}'

        with patch(
            "src.backend.infrastructure.clients.transport.http_httpx.get_httpx_client"
        ) as mock_get_client:
            mock_client = MagicMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            processor = GraphQLQueryProcessor(
                endpoint="https://api.example.com/graphql",
                query="{ users { id } }",
                auth_token="my-secret-token",
            )
            await processor.process(exchange, _Context())

            call_kwargs = mock_client.request.call_args.kwargs
            assert "Authorization" in call_kwargs["headers"]
            assert call_kwargs["headers"]["Authorization"] == "Bearer my-secret-token"

    @pytest.mark.asyncio
    async def test_custom_auth_header_used(self) -> None:
        """When auth_header is customized, it is used instead of Authorization."""
        exchange = _Exchange()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"data": {}}'

        with patch(
            "src.backend.infrastructure.clients.transport.http_httpx.get_httpx_client"
        ) as mock_get_client:
            mock_client = MagicMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            processor = GraphQLQueryProcessor(
                endpoint="https://api.example.com/graphql",
                query="{ users { id } }",
                auth_token="api-key-123",
                auth_header="X-API-Key",
            )
            await processor.process(exchange, _Context())

            call_kwargs = mock_client.request.call_args.kwargs
            assert "X-API-Key" in call_kwargs["headers"]
            assert call_kwargs["headers"]["X-API-Key"] == "Bearer api-key-123"

    @pytest.mark.asyncio
    async def test_headers_are_sent_in_request(self) -> None:
        """Custom headers are included in the request."""
        exchange = _Exchange()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"data": {}}'

        with patch(
            "src.backend.infrastructure.clients.transport.http_httpx.get_httpx_client"
        ) as mock_get_client:
            mock_client = MagicMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            processor = GraphQLQueryProcessor(
                endpoint="https://api.example.com/graphql",
                query="{ users { id } }",
                headers={"X-Request-Id": "req-123", "X-Custom": "value"},
            )
            await processor.process(exchange, _Context())

            call_kwargs = mock_client.request.call_args.kwargs
            assert call_kwargs["headers"]["X-Request-Id"] == "req-123"
            assert call_kwargs["headers"]["X-Custom"] == "value"

    @pytest.mark.asyncio
    async def test_graphql_payload_structure(self) -> None:
        """Request payload contains query, variables, and operationName when set."""
        exchange = _Exchange()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"data": {}}'

        with patch(
            "src.backend.infrastructure.clients.transport.http_httpx.get_httpx_client"
        ) as mock_get_client:
            mock_client = MagicMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            processor = GraphQLQueryProcessor(
                endpoint="https://api.example.com/graphql",
                query="query GetUser($id: ID!) { user(id: $id) { name } }",
                variables={"id": 42},
                operation_name="GetUser",
            )
            await processor.process(exchange, _Context())

            call_kwargs = mock_client.request.call_args.kwargs
            payload = call_kwargs["json"]
            assert payload["query"] == "query GetUser($id: ID!) { user(id: $id) { name } }"
            assert payload["variables"] == {"id": 42}
            assert payload["operationName"] == "GetUser"

    @pytest.mark.asyncio
    async def test_mutation_with_variables(self) -> None:
        """Mutation queries work with variables."""
        exchange = _Exchange()
        exchange.in_message.body = {"name": "Bob", "email": "bob@example.com"}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"data": {"createUser": {"id": 999, "name": "Bob"}}}'

        with patch(
            "src.backend.infrastructure.clients.transport.http_httpx.get_httpx_client"
        ) as mock_get_client:
            mock_client = MagicMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            processor = GraphQLQueryProcessor(
                endpoint="https://api.example.com/graphql",
                query="mutation CreateUser($name: String!, $email: String!) { createUser(name: $name, email: $email) { id name } }",
                variables={"name": "Bob", "email": "bob@example.com"},
            )
            await processor.process(exchange, _Context())

            assert exchange.out_message is not None
            assert exchange.out_message.body == {
                "data": {"createUser": {"id": 999, "name": "Bob"}}
            }

    def test_to_spec_returns_graphql_query_dict(self) -> None:
        """to_spec returns a dict with graphql_query key."""
        processor = GraphQLQueryProcessor(
            endpoint="https://api.example.com/graphql",
            query="{ user { name } }",
            variables={"id": 1},
            operation_name="GetUser",
            auth_header="X-Token",
            timeout=45.0,
            result_property="gql",
        )
        spec = processor.to_spec()

        assert "graphql_query" in spec
        gql_spec = spec["graphql_query"]
        assert gql_spec["endpoint"] == "https://api.example.com/graphql"
        assert gql_spec["query"] == "{ user { name } }"
        assert gql_spec["variables"] == {"id": 1}
        assert gql_spec["operation_name"] == "GetUser"
        assert gql_spec["auth_header"] == "X-Token"
        assert gql_spec["timeout"] == 45.0
        assert gql_spec["result_property"] == "gql"
        assert gql_spec["auth_token"] == "<redacted>"

    def test_to_spec_omits_optional_defaults(self) -> None:
        """to_spec omits parameters that are at default values."""
        processor = GraphQLQueryProcessor(
            endpoint="https://api.example.com/graphql",
            query="{ users { id } }",
        )
        spec = processor.to_spec()
        gql_spec = spec["graphql_query"]

        # Required fields should be present
        assert gql_spec["endpoint"] == "https://api.example.com/graphql"
        assert gql_spec["query"] == "{ users { id } }"
        # Non-set optional fields should not be present
        assert "variables" not in gql_spec
        assert "operation_name" not in gql_spec
        assert "headers" not in gql_spec
        assert "auth_token" not in gql_spec
        # Default values that differ from implicit defaults should not be present
        assert "auth_header" not in gql_spec  # default is "Authorization"
        assert "timeout" not in gql_spec  # default is 30.0
        assert "result_property" not in gql_spec  # default is None
