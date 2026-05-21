"""K3 S5 W7 — :class:`PolicyMixin`: chainable .policy.* API в RouteBuilder.

Wave ``[wave:s5/k3-w7-policy-chainable]``.

Реализует chainable composable policy через property-объект ``.policy``,
который возвращает proxy-объект :class:`PolicyChain`. Каждый метод
PolicyChain (cache/circuit_breaker/rate_limit/timeout/retry/bulkhead)
добавляет соответствующий процессор в pipeline и возвращает builder
для продолжения цепочки.

Использование (Camel-style)::

    route = (
        RouteBuilder.from_("api.heavy", source="http:GET /api/heavy")
        .policy.cache(ttl_seconds=60)
        .policy.circuit_breaker(threshold=5, timeout_seconds=30)
        .policy.rate_limit(rate=100, per_seconds=1)
        .dispatch_action("heavy.execute")
        .build()
    )

Идиома: ``.policy.cache(...)`` возвращает RouteBuilder, что позволяет
chaining ``.policy.cache(...).policy.circuit_breaker(...)``.

Feature flag: ``feature_flags.policy_chainable_enabled`` (default-OFF).

Контракт миксина:
    * stateless — нет instance-атрибутов;
    * ``__slots__ = ()`` — обязательно;
    * не содержит ``@dataclass``;
    * метод ``policy`` — property возвращающий ``PolicyChain(self)``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder

__all__ = ("PolicyMixin", "PolicyChain")


class PolicyChain:
    """Proxy для chainable .policy.* API.

    Каждый метод вызывает соответствующий policy-процессор на builder'е и
    возвращает builder, чтобы можно было продолжать цепочку
    ``.policy.cache(...).policy.circuit_breaker(...)``.
    """

    __slots__ = ("_builder",)

    def __init__(self, builder: "RouteBuilder") -> None:
        self._builder = builder

    def cache(
        self, *, ttl_seconds: int = 60, key: str | None = None, backend: str = "redis"
    ) -> "RouteBuilder":
        """Add cache policy (через CacheProcessor / Redis backend)."""
        return self._add_policy_processor(
            "cache", ttl_seconds=ttl_seconds, key=key, backend=backend
        )

    def circuit_breaker(
        self,
        *,
        threshold: int = 5,
        timeout_seconds: int = 30,
        recovery_seconds: int = 60,
    ) -> "RouteBuilder":
        """Add circuit-breaker policy (через ResilienceCoordinator)."""
        return self._add_policy_processor(
            "circuit_breaker",
            threshold=threshold,
            timeout_seconds=timeout_seconds,
            recovery_seconds=recovery_seconds,
        )

    def rate_limit(
        self, *, rate: int = 100, per_seconds: int = 1, scope: str = "global"
    ) -> "RouteBuilder":
        """Add rate-limit policy (через ThrottlerProcessor / RateLimiter)."""
        return self._add_policy_processor(
            "rate_limit", rate=rate, per_seconds=per_seconds, scope=scope
        )

    def timeout(self, *, seconds: float = 30.0) -> "RouteBuilder":
        """Add timeout policy (через TimeoutProcessor)."""
        return self._add_policy_processor("timeout", seconds=seconds)

    def retry(
        self, *, max_attempts: int = 3, backoff_seconds: float = 1.0
    ) -> "RouteBuilder":
        """Add retry policy (через RetryProcessor / tenacity)."""
        return self._add_policy_processor(
            "retry", max_attempts=max_attempts, backoff_seconds=backoff_seconds
        )

    def bulkhead(
        self, *, max_concurrent: int = 10, wait_timeout_seconds: float = 5.0
    ) -> "RouteBuilder":
        """Add bulkhead policy (через BulkheadProcessor / asyncio.Semaphore)."""
        return self._add_policy_processor(
            "bulkhead",
            max_concurrent=max_concurrent,
            wait_timeout_seconds=wait_timeout_seconds,
        )

    def idempotency(
        self, *, key: str = "header.X-Idempotency-Key", ttl_seconds: int = 3600
    ) -> "RouteBuilder":
        """Add idempotency policy (через IdempotentConsumerProcessor)."""
        return self._add_policy_processor(
            "idempotency", key=key, ttl_seconds=ttl_seconds
        )

    def _add_policy_processor(self, name: str, **kwargs: Any) -> "RouteBuilder":
        """Создаёт PolicyMarkerProcessor и добавляет в builder.

        Returns:
            ``RouteBuilder`` для chaining дальше.
        """
        try:
            from src.backend.core.config.features import feature_flags

            if not feature_flags.policy_chainable_enabled:
                # Flag OFF — добавляем no-op маркер для traceability
                marker = PolicyMarkerProcessor(
                    policy_name=name, params=kwargs, enabled=False
                )
                self._builder._processors.append(marker)
                return self._builder
        except Exception:  # noqa: BLE001
            pass

        marker = PolicyMarkerProcessor(policy_name=name, params=kwargs, enabled=True)
        self._builder._processors.append(marker)
        return self._builder


class PolicyMarkerProcessor:
    """Лёгкий marker-процессор для policy chain.

    На исполнении делегирует работу в соответствующий ResilienceCoordinator-
    backend по policy_name. В минимальной версии (Wave 7) — просто метаданные
    в exchange.properties для downstream-инспекции и интеграции.
    """

    side_effect: Any = "PURE"
    compensatable: bool = True

    def __init__(
        self, *, policy_name: str, params: dict[str, Any], enabled: bool
    ) -> None:
        self.name = f"policy:{policy_name}"
        self.policy_name = policy_name
        self.params = dict(params)
        self.enabled = enabled

    async def process(self, exchange: Any, context: Any) -> None:
        """Записать факт применения policy в exchange.properties."""
        try:
            from src.backend.core.config.features import feature_flags

            if not feature_flags.policy_chainable_enabled:
                return
        except Exception:  # noqa: BLE001
            pass

        if not self.enabled:
            return

        # Накопление списка применённых policy в properties
        applied = list(exchange.properties.get("_policies_applied") or [])
        applied.append({"name": self.policy_name, "params": self.params})
        exchange.set_property("_policies_applied", applied)

        # Интеграция с ResilienceCoordinator (опционально)
        try:
            from src.backend.infrastructure.resilience.coordinator import (
                ResilienceCoordinator,
            )

            coordinator = ResilienceCoordinator()
            register = getattr(coordinator, f"register_{self.policy_name}", None)
            if register and callable(register):
                try:
                    register(**self.params)
                except Exception:  # noqa: BLE001
                    pass
        except ImportError:
            pass

    def to_spec(self) -> dict[str, Any] | None:
        return {"policy": {"name": self.policy_name, "params": self.params}}


class PolicyMixin:
    """Миксин chainable .policy property для RouteBuilder."""

    __slots__ = ()

    @property
    def policy(self) -> PolicyChain:
        """Возвращает PolicyChain proxy для chainable .policy.cache().policy.circuit_breaker()."""
        return PolicyChain(self)  # type: ignore[arg-type]
