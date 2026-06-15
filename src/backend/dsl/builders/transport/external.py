"""Mixin for transport external service methods (S50 W2 extraction, ADR-0107 B3-B5).

Extracted from ``transport.py`` god-file (S84 B1).
MRO composition: TransportMixin → SourcesMixin → ExternalMixin → ProxyMixin → PersistenceMixin → SinksMixin.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder


class ExternalMixin:
    """Stateless mixin. Uses self._add / self._add_lazy via MRO."""

    __slots__ = ()

    # --- external service methods ---
    def graphql_query(
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
    ) -> RouteBuilder:
        """GraphQL query/mutation executor.

        Выполняет GraphQL-запрос к указанному endpoint с поддержкой:
        - query string и variables;
        - operation name для batched queries;
        - Bearer token authentication;
        - custom headers;
        - result writing в property или body.

        Args:
            endpoint: GraphQL endpoint URL.
            query: GraphQL query или mutation string.
            variables: Опциональные variables для query.
            operation_name: Имя операции (для batched/named operations).
            headers: Дополнительные HTTP headers.
            auth_token: Bearer token для authentication.
            auth_header: Имя auth header (default ``Authorization``).
            timeout: Request timeout в секундах (default 30.0).
            result_property: Имя property для записи результата.
                Если ``None`` — результат пишется в ``out_message.body``.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.graphql_query",
            "GraphQLQueryProcessor",
            endpoint=endpoint,
            query=query,
            variables=variables,
            operation_name=operation_name,
            headers=headers,
            auth_token=auth_token,
            auth_header=auth_header,
            timeout=timeout,
            result_property=result_property,
        )

    def http_call(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        auth_token: str | None = None,
        timeout: float = 30.0,
        result_property: str | None = None,
    ) -> RouteBuilder:
        """HTTP client: GET/POST/PUT/DELETE с таймаутом и headers."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.components",
            "HttpCallProcessor",
            url=url,
            method=method,
            headers=headers,
            auth_token=auth_token,
            timeout=timeout,
            result_property=result_property,
        )

    def web_search(
        self,
        engine: str = "auto",
        *,
        query: str | None = None,
        query_source: str | None = None,
        max_results: int = 10,
        to: str = "body.search_results",
        deep_research: bool = False,
    ) -> RouteBuilder:
        """K3 S5 W9 — web-поиск через WebSearchService (Tavily/Perplexity/SearXNG).

        Args:
            engine: ``tavily`` / ``perplexity`` / ``searxng`` / ``auto`` (fallback).
            query: Прямой query (если задан).
            query_source: ``body.<field>`` / ``properties.<name>`` для query.
            max_results: Максимум результатов.
            to: Куда положить результат.
            deep_research: Использовать deep_research().

        Returns:
            ``RouteBuilder`` для chain-продолжения.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.web_search",
            "WebSearchProcessor",
            engine=engine,
            query=query,
            query_source=query_source,
            max_results=max_results,
            to=to,
            deep_research=deep_research,
        )

    def ldap_query(
        self,
        server: str,
        base_dn: str,
        filter: str = "(objectClass=*)",
        *,
        attributes: list[str] | None = None,
        username: str | None = None,
        password: str | None = None,
        use_ssl: bool = False,
        timeout: float = 30.0,
        result_property: str = "ldap_result",
    ) -> RouteBuilder:
        """LDAP query executor.

        Args:
            server: LDAP server URI (e.g. ``ldap://ldap.example.com``).
            base_dn: Base DN for search.
            filter: LDAP filter string.
            attributes: Attributes to retrieve (None = all).
            username: Bind DN for authentication.
            password: Bind password.
            use_ssl: Use LDAPS.
            timeout: Query timeout in seconds.
            result_property: Property name for search results.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.ldap_query",
            "LdapQueryProcessor",
            server=server,
            base_dn=base_dn,
            filter=filter,
            attributes=attributes,
            username=username,
            password=password,
            use_ssl=use_ssl,
            timeout=timeout,
            result_property=result_property,
        )

    def geo(
        self,
        mode: str,
        *,
        address: str | None = None,
        point_a: tuple[float, float] | None = None,
        point_b: tuple[float, float] | None = None,
        to: str = "body.geo_result",
    ) -> RouteBuilder:
        """Geocoding, reverse geocoding, or distance calculation.

        Args:
            mode: ``"geocode"`` (address → coords), ``"reverse"`` (coords → address),
                ``"distance"`` (two points → km).
            address: Address string for geocode mode.
            point_a: First coordinate ``(lat, lon)`` for distance mode.
            point_b: Second coordinate ``(lat, lon)`` for distance mode.
            to: Destination dotted-path.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.geo",
            "GeoProcessor",
            mode=mode,
            address=address,
            point_a=point_a,
            point_b=point_b,
            to=to,
        )
