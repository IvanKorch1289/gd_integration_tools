"""Control-flow RouteBuilder contracts (W9 P2-13 split).

Control-flow + concurrency + time/resilience семейство — все операции
управления потоком исполнения: choice/switch/try/retry/fallback/DLQ/saga,
parallel/fork-join/loop/for-each/throttle, circuit-breaker/timeout/expire/HITL.

ADR-0320: вынесено из ``_protocols.py`` (1094 LOC god-module) в отдельный
sub-module ``_flow.py`` как часть W9 P2-13 (god-object decomposition).
"""

from __future__ import annotations

from typing import Any
from typing import Protocol as _Protocol
from typing import runtime_checkable as _runtime_checkable


@_runtime_checkable
class _RouteControlFlowProtocol(_Protocol):
    """Contract: control-flow (choice/switch/try/retry/fallback/DLQ/saga)."""

    def choice(self, when: list[Any], otherwise: list[Any] | None = None) -> Any: ...
    def switch(
        self,
        field: str,
        cases: dict[str, list[Any]],
        *,
        default: list[Any] | None = None,
    ) -> Any: ...
    def do_try(
        self,
        try_processors: list[Any],
        catch_processors: list[Any] | None = None,
        finally_processors: list[Any] | None = None,
    ) -> Any: ...
    def retry(
        self,
        processors: list[Any],
        *,
        max_attempts: int = 3,
        delay_seconds: float = 1.0,
        backoff: str = "exponential",
    ) -> Any: ...
    def fallback(self, processors: list[Any]) -> Any: ...
    def dead_letter(
        self, processors: list[Any], *, dlq_stream: str = "dsl-dlq"
    ) -> Any: ...
    def on_error(
        self,
        *,
        action: str | None = None,
        processors: list[Any] | None = None,
        dlq_stream: str = "dsl-dlq",
    ) -> Any: ...
    def saga(self, steps: list[Any]) -> Any: ...


@_runtime_checkable
class _RouteConcurrencyProtocol(_Protocol):
    """Contract: parallel / fork-join / loop / for-each / throttling."""

    def parallel(
        self, branches: dict[str, list[Any]], *, strategy: str = "all"
    ) -> Any: ...
    def fork_join(
        self,
        branches: dict[str, list[Any]],
        *,
        aggregation: str = "collect",
        timeout_seconds: float | None = None,
    ) -> Any: ...
    def idempotent(self, key_expression: Any, *, ttl_seconds: int = 86400) -> Any: ...
    def throttle(self, rate: float, *, burst: int = 1) -> Any: ...
    def delay(
        self, delay_ms: int | None = None, *, scheduled_time_fn: Any | None = None
    ) -> Any: ...
    def loop(
        self,
        processors: list[Any],
        *,
        count: int | None = None,
        until: Any | None = None,
        max_iterations: int = 1000,
    ) -> Any: ...
    def for_each(
        self,
        items_path: str,
        processors: list[Any],
        *,
        copy_exchange: bool = True,
        max_iterations: int = 10000,
    ) -> Any: ...


@_runtime_checkable
class _RouteTimeResilienceProtocol(_Protocol):
    """Contract: time-control / circuit-breaker / expiration / HITL."""

    def circuit_breaker(
        self,
        processors: list[Any],
        *,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        fallback_processors: list[Any] | None = None,
        breaker_name: str | None = None,
    ) -> Any: ...
    def timeout(
        self,
        processors: list[Any],
        *,
        seconds: float = 30.0,
        fallback_processors: list[Any] | None = None,
    ) -> Any: ...
    def expire(
        self,
        ttl_seconds: float,
        *,
        header_name: str = "x-created-at",
        drop_action: str = "fail",
    ) -> Any: ...
    def correlation_id(self, *, header: str = "x-correlation-id") -> Any: ...
    def hitl_approval(
        self,
        hitl_service: Any,
        *,
        title: str,
        description: str = "",
        approvers: list[str] | None = None,
        timeout_seconds: float = 86_400.0,
        payload_path: str | None = None,
        request_info_processors: list[Any] | None = None,
    ) -> Any: ...
    def region_routing(
        self,
        primary: str,
        fallback: str | None = None,
        *,
        health_check_interval: float = 30.0,
    ) -> Any: ...
    def supervisor(
        self, *, max_restarts: int = 3, timeout: float = 60.0, backoff: float = 2.0
    ) -> Any: ...
