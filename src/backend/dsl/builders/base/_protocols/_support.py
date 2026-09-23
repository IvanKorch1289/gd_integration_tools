"""Supporting RouteBuilder contracts (W9 P2-13 split).

Cross-cutting concerns семейство — format converters (to_*/from_*),
EIP content ops (enrich/wire_tap/multicast), Groovy-style collection helpers,
security (auth/JWT/webhook signing), config modifiers (with_*/set_header).

ADR-0320: вынесено из ``_protocols.py`` (1094 LOC god-module) в отдельный
sub-module ``_support.py`` как часть W9 P2-13 (god-object decomposition).
"""

from __future__ import annotations

from typing import Any
from typing import Protocol as _Protocol
from typing import runtime_checkable as _runtime_checkable


@_runtime_checkable
class _RouteConverterProtocol(_Protocol):
    """Contract: format converters (to_*/from_* — JSON/CSV/XML/YAML/Excel/etc)."""

    def to_json(self, *, indent: int | None = None) -> Any: ...
    def from_json(self, *, from_property: str = "body") -> Any: ...
    def to_csv(self, *, headers: list[str] | None = None) -> Any: ...
    def from_csv(self, csv_string: str | None = None) -> Any: ...
    def to_xml(self, *, root_tag: str = "root") -> Any: ...
    def from_xml(self, xml_string: str | None = None) -> Any: ...
    def to_yaml(self) -> Any: ...
    def from_yaml(self, yaml_string: str | None = None) -> Any: ...
    def to_excel(self, *, sheet_name: str = "Sheet1") -> Any: ...
    def from_excel(self, excel_bytes: bytes | None = None) -> Any: ...
    def to_parquet(self, *, compression: str = "snappy") -> Any: ...
    def from_parquet(self, parquet_bytes: bytes | None = None) -> Any: ...


@_runtime_checkable
class _RouteContentProtocol(_Protocol):
    """Contract: EIP content operations (enrich/wire_tap/multicast/recipient_list/filter/transform)."""

    def enrich(
        self,
        action: str,
        *,
        payload_factory: Any | None = None,
        result_property: str = "enrichment",
    ) -> Any: ...
    def wire_tap(self, tap_processors: list[Any]) -> Any: ...
    def multicast(
        self,
        branches: list[list[Any]],
        *,
        strategy: str = "all",
        stop_on_error: bool = False,
    ) -> Any: ...
    def recipient_list(
        self, recipients_expression: Any, *, parallel: bool = True
    ) -> Any: ...
    def content_filter(self, predicate: Any) -> Any: ...
    def content_transform(self, expression: str) -> Any: ...


@_runtime_checkable
class _RouteCollectionProtocol(_Protocol):
    """Contract: Groovy-style collection ops (9 pure-static helpers)."""

    @staticmethod
    def collect(items: Any, field: str | None = None) -> list[Any]: ...
    @staticmethod
    def find_all(
        items: Any,
        predicate: Any | None = None,
        *,
        field: str | None = None,
        value: Any = None,
    ) -> list[Any]: ...
    @staticmethod
    def find(
        items: Any,
        predicate: Any | None = None,
        *,
        field: str | None = None,
        value: Any = None,
    ) -> Any: ...
    @staticmethod
    def group_by(items: Any, field: str) -> dict[Any, list[Any]]: ...
    @staticmethod
    def sort(
        items: Any, field: str | None = None, *, reverse: bool = False
    ) -> list[Any]: ...
    @staticmethod
    def each(items: Any, action: Any) -> list[Any]: ...
    @staticmethod
    def flatten(items: Any, levels: int = 1) -> list[Any]: ...
    @staticmethod
    def unique(items: Any, field: str | None = None) -> list[Any]: ...
    @staticmethod
    def plus(items: Any, other: Any) -> list[Any]: ...


@_runtime_checkable
class _RouteSecurityProtocol(_Protocol):
    """Contract: auth / authn / webhook signing / PII masking."""

    def auth(
        self,
        methods: list[str] | str = "api_key",
        *,
        result_property: str = "auth",
        required: bool = True,
    ) -> Any: ...
    def require_header(self, name: str) -> Any: ...
    def require_bearer(self) -> Any: ...
    def require_auth(self) -> Any: ...
    def require_fields(self, *names: str) -> Any: ...
    def jwt_sign(
        self,
        *,
        secret_key: str,
        algorithm: str = "HS256",
        expires_in_seconds: int | None = 3600,
        output_property: str = "jwt",
    ) -> Any: ...
    def jwt_verify(
        self,
        *,
        secret_key: str,
        algorithm: str = "HS256",
        header: str = "Authorization",
        output_property: str = "jwt_claims",
    ) -> Any: ...
    def webhook_sign(
        self,
        *,
        secret: str,
        header: str = "X-Webhook-Signature",
        algorithm: str = "sha256",
    ) -> Any: ...


@_runtime_checkable
class _RouteConfigProtocol(_Protocol):
    """Contract: per-step modifiers (with_*) + route-level overrides."""

    def with_timeout(self, seconds: float) -> Any: ...
    def with_retries(
        self, max_attempts: int, *, backoff: str | float | None = None
    ) -> Any: ...
    def with_circuit_breaker(
        self, name: str, *, failure_threshold: int = 5, recovery_timeout: float = 30.0
    ) -> Any: ...
    def with_headers(self, headers: dict[str, str], *, mode: str = "merge") -> Any: ...
    def with_auth(
        self,
        *,
        token: str | None = None,
        api_key: str | None = None,
        mtls_cert: str | None = None,
    ) -> Any: ...
    def set_header(self, key: str, value: Any) -> Any: ...
    def with_pool_size(self, n: int) -> Any: ...
    def with_max_message_size(self, bytes_: int) -> Any: ...
    def with_message_timeout(self, seconds: float) -> Any: ...
    def with_connection_pool(
        self, min_size: int = 2, max_size: int = 20, timeout: float = 5.0
    ) -> Any: ...
    def with_reconnection(
        self, max_attempts: int = 3, delay: float = 1.0, backoff: float = 2.0
    ) -> Any: ...
