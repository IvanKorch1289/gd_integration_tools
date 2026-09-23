"""Integration-layer RouteBuilder contracts (W9 P2-13 split).

Proxy + sinks + sources + integration core семейство — все операции
взаимодействия с внешними системами: HTTP/GraphQL/LDAP proxy, 10 sink_*
(outbound), 7 source-* (inbound), action dispatch/invoke/call_function.

ADR-0320: вынесено из ``_protocols.py`` (1094 LOC god-module) в отдельный
sub-module ``_integration.py`` как часть W9 P2-13 (god-object decomposition).
"""

from __future__ import annotations

from typing import Any
from typing import Protocol as _Protocol
from typing import runtime_checkable as _runtime_checkable


@_runtime_checkable
class _RouteProxyProtocol(_Protocol):
    """Contract: proxy / redirect / external HTTP/GraphQL/LDAP."""

    def expose_proxy(
        self,
        src: str,
        *,
        methods: list[str] | None = None,
        header_map: dict[str, Any] | None = None,
    ) -> Any: ...
    def forward_to(
        self,
        dst: str,
        *,
        pass_headers: bool = True,
        header_map: dict[str, Any] | None = None,
        rewrite_path: str | None = None,
        timeout: float = 30.0,
    ) -> Any: ...
    def proxy(
        self,
        src: str,
        dst: str,
        *,
        methods: list[str] | None = None,
        pass_headers: bool = True,
        header_map: dict[str, Any] | None = None,
        rewrite_path: str | None = None,
        timeout: float = 30.0,
    ) -> Any: ...
    def redirect(
        self,
        target_url: str | None = None,
        *,
        status_code: int = 302,
        url_source: str | None = None,
        source_key: str | None = None,
        allowed_hosts: list[str] | None = None,
    ) -> Any: ...
    def http_call(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        auth_token: str | None = None,
        timeout: float = 30.0,
        result_property: str | None = None,
    ) -> Any: ...
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
    ) -> Any: ...
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
    ) -> Any: ...
    def geo(
        self,
        mode: str,
        *,
        address: str | None = None,
        point_a: tuple[float, float] | None = None,
        point_b: tuple[float, float] | None = None,
        to: str = "body.geo_result",
    ) -> Any: ...


@_runtime_checkable
class _RouteSinkProtocol(_Protocol):
    """Contract: outbound sinks (10 sink_* методов)."""

    def sink_http(
        self,
        *,
        url: str,
        method: str = "POST",
        headers: dict[str, str] | None = None,
        timeout: float = 10.0,
        payload_property: str | None = None,
        result_property: str = "sink_publish_result",
    ) -> Any: ...
    def sink_email(
        self,
        *,
        host: str,
        from_addr: str,
        port: int = 587,
        username: str | None = None,
        password: str | None = None,
        use_tls: bool = False,
        start_tls: bool = True,
        default_to: str | None = None,
        default_subject: str = "",
        payload_property: str | None = None,
        result_property: str = "sink_publish_result",
    ) -> Any: ...
    def sink_file(
        self,
        *,
        path: str,
        mode: str = "append",
        encoding: str = "utf-8",
        ensure_dir: bool = True,
        payload_property: str | None = None,
        result_property: str = "sink_publish_result",
    ) -> Any: ...
    def sink_grpc(
        self,
        *,
        target: str,
        full_method: str,
        secure: bool = True,
        timeout: float = 10.0,
        payload_property: str | None = None,
        result_property: str = "grpc_result",
    ) -> Any: ...
    def sink_mq(
        self,
        *,
        broker: str,
        url: str,
        topic: str,
        extra: dict[str, Any] | None = None,
        payload_property: str | None = None,
        result_property: str = "mq_publish_result",
    ) -> Any: ...
    def sink_mqtt(
        self,
        *,
        host: str,
        topic: str,
        port: int | None = None,
        qos: int = 0,
        retain: bool = False,
        username: str | None = None,
        password: str | None = None,
        payload_property: str | None = None,
        result_property: str = "mqtt_publish_result",
    ) -> Any: ...
    def sink_s3(
        self,
        *,
        bucket: str,
        key: str,
        content_type: str = "application/octet-stream",
        payload_property: str | None = None,
        result_property: str = "sink_publish_result",
    ) -> Any: ...
    def sink_soap(
        self,
        *,
        wsdl_url: str,
        operation: str,
        service_name: str | None = None,
        port_name: str | None = None,
        timeout: float = 30.0,
        payload_property: str | None = None,
        result_property: str = "soap_result",
    ) -> Any: ...
    def sink_webhook(
        self,
        *,
        url: str,
        event: str,
        secret: str | None = None,
        timeout: float = 10.0,
        extra_headers: dict[str, str] | None = None,
        payload_property: str | None = None,
        result_property: str = "sink_publish_result",
    ) -> Any: ...
    def sink_ws(
        self,
        *,
        url: str,
        extra_headers: dict[str, str] | None = None,
        timeout: float = 10.0,
        payload_property: str | None = None,
        result_property: str = "ws_publish_result",
    ) -> Any: ...


@_runtime_checkable
class _RouteSourceProtocol(_Protocol):
    """Contract: source-points (NATS/WebDAV/Mongo/FS polling)."""

    def directory_scan(
        self,
        path: str,
        pattern: str = "*",
        *,
        recursive: bool = False,
        max_files: int = 1000,
        sort_by: str = "name",
        result_property: str = "directory_scan_result",
    ) -> Any: ...
    def poll(
        self,
        source_action: str,
        *,
        payload: dict[str, Any] | None = None,
        result_property: str = "polled_data",
    ) -> Any: ...
    def to_nats_js(
        self,
        subject: str,
        *,
        nats_url: str = "nats://localhost:4222",
        headers: dict[str, str] | None = None,
        payload_property: str | None = None,
        result_property: str = "nats_js_publish_result",
    ) -> Any: ...
    @classmethod
    def from_nats_js(
        cls,
        route_id: str,
        subject: str,
        stream: str,
        durable: str,
        *,
        nats_url: str = "nats://localhost:4222",
        description: str | None = None,
    ) -> Any: ...
    @classmethod
    def from_webdav(
        cls,
        route_id: str,
        url: str,
        *,
        watch_path: str = "/",
        poll_interval_seconds: int = 60,
        file_pattern: str = "*",
        username: str | None = None,
        password: str | None = None,
        processed_marker_path: str | None = None,
        marker_dedup: bool = True,
        description: str | None = None,
    ) -> Any: ...
    @classmethod
    def from_nats(
        cls,
        route_id: str,
        subject: str,
        *,
        nats_url: str = "nats://localhost:4222",
        description: str | None = None,
    ) -> Any: ...
    @classmethod
    def from_mongo(
        cls,
        route_id: str,
        connection_url: str,
        database: str,
        collection: str = "",
        *,
        full_document_lookup: bool = False,
        pipeline: list[dict[str, Any]] | None = None,
        description: str | None = None,
    ) -> Any: ...


@_runtime_checkable
class _RouteIntegrationCoreProtocol(_Protocol):
    """Contract: action dispatch + invoke + to_route + util (call_function/get_setting/validate_response)."""

    def dispatch_action(
        self,
        action: str,
        *,
        payload_factory: Any | None = None,
        result_property: str = "action_result",
    ) -> Any: ...
    def invoke(
        self,
        action: str,
        *,
        mode: str = "sync",
        payload_factory: Any | None = None,
        reply_channel: str | None = None,
        result_property: str = "invoke_result",
        invocation_id_property: str = "invocation_id",
        timeout: float | None = None,
        correlation_id: str | None = None,
    ) -> Any: ...
    def to_route(
        self, route_id: str, *, result_property: str = "sub_result"
    ) -> Any: ...
    def call_function(
        self,
        ref: str,
        *,
        payload_from: str = "body",
        result_property: str = "function_result",
        inject: list[str] | None = None,
    ) -> Any: ...
    def get_setting(
        self, path: str, *, to: str = "body.setting", default: Any = None
    ) -> Any: ...
    def validate_response(
        self,
        *,
        schema: Any | None = None,
        on_error: str = "fail",
        source: str = "out_body",
    ) -> Any: ...
    def facade_get_health(self, name: str, *, to: str = "body.health") -> Any: ...
