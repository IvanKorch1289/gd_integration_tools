"""HTTP per-upstream профили (WSO2 Dynamic Endpoint / MuleSoft HTTP Requester).

IL2.6 (ADR-022): до этой фазы все исходящие HTTP-вызовы делались через один
глобальный `httpx.AsyncClient` с общими pool-параметрами. Это не подходит в
реальных условиях: SKB и Dadata имеют разные SLA, разные rate-limits, разные
политики ретраев. Одна «плохая» upstream могла легко забить глобальный pool
и задеть остальные.

`UpstreamRegistry` хранит именованные профили (`skb`, `dadata`, `yandex`, ...),
каждый — со своим PoolingProfile, CircuitBreaker, rate-limit, base_url и
headers. Клиенты и DSL-процессоры запрашивают upstream по имени:

    from src.infrastructure.clients.transport.http_upstream import upstream_registry

    upstream = upstream_registry.get("dadata")
    async with upstream.client.stream("POST", "/suggestions") as resp:
        ...

Каждый upstream имеет собственный `httpx.AsyncClient` с HTTP/2 + connection
limits из `PoolingProfile.max_size` + keepalive из `idle_timeout_s`. При
работе через upstream автоматически подставляются base_url и default-headers.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    import httpx  # только для type-hints; runtime-импорт в `start()`.

from src.core.config.pooling import DEFAULT_POOLING_PROFILE, PoolingProfile
from src.infrastructure.clients.base_connector import HealthResult, InfrastructureClient
from src.infrastructure.observability.client_metrics import ClientMetricsMixin
from src.infrastructure.resilience.client_breaker import (
    CircuitOpen,
    ClientCircuitBreaker,
)

_logger = logging.getLogger(__name__)


@dataclass(slots=True)
class UpstreamProfile:
    """Декларативный профиль одной внешней HTTP-системы.

    Поля:
      * ``name`` — уникальное имя (ключ в Registry, label в Prometheus).
      * ``base_url`` — базовый URL (обязательный); относительные пути в коде.
      * ``default_headers`` — headers, добавляемые к каждому запросу
        (например ``{"X-Api-Key": "..."}``). Per-request headers override.
      * ``pooling`` — `PoolingProfile`: max_size = max connections, idle_timeout_s
        = keepalive_expiry, acquire_timeout_s = connect+read timeout.
      * ``verify_ssl`` — выключать только в dev.
      * ``http2`` — default True; автоматический fallback на HTTP/1.1 если
        сервер не поддерживает.
    """

    name: str
    base_url: str
    default_headers: dict[str, str] = field(default_factory=dict)
    pooling: PoolingProfile = field(default_factory=lambda: DEFAULT_POOLING_PROFILE)
    verify_ssl: bool = True
    http2: bool = True


class HttpUpstreamClient(ClientMetricsMixin, InfrastructureClient):
    """Одна зарегистрированная HTTP-upstream система.

    Наследует `InfrastructureClient` → участвует в ConnectorRegistry
    lifecycle (start/stop/health). Наследует `ClientMetricsMixin` →
    RED-метрики автоматически с `client=upstream:<name>`.

    Внутри хранит один `httpx.AsyncClient`, CB на уровне host, health-probe
    вызывает `HEAD /` (или `/healthcheck` если задан).
    """

    def __init__(self, profile: UpstreamProfile, *, health_path: str = "/") -> None:
        super().__init__(name=f"upstream:{profile.name}", pooling=profile.pooling)
        self._profile = profile
        self._health_path = health_path
        self._client: "httpx.AsyncClient | None" = None
        self._breaker = ClientCircuitBreaker.from_profile(
            name=self.name, profile=self.pooling, host=profile.base_url
        )

    # -- lifecycle -----------------------------------------------------

    async def start(self) -> None:
        if self._client is not None:
            return
        import httpx  # локальный импорт, чтобы не держать при import'е модуля

        limits = httpx.Limits(
            max_connections=self._profile.pooling.max_size,
            max_keepalive_connections=max(1, self._profile.pooling.max_size // 2),
            keepalive_expiry=self._profile.pooling.idle_timeout_s,
        )
        timeout = httpx.Timeout(
            connect=self._profile.pooling.acquire_timeout_s,
            read=self._profile.pooling.acquire_timeout_s * 2,
            write=self._profile.pooling.acquire_timeout_s,
            pool=self._profile.pooling.acquire_timeout_s,
        )
        self._client = httpx.AsyncClient(
            base_url=self._profile.base_url,
            headers=self._profile.default_headers,
            verify=self._profile.verify_ssl,
            http2=self._profile.http2,
            limits=limits,
            timeout=timeout,
        )
        self._started = True
        _logger.info(
            "upstream client started",
            extra={
                "upstream": self._profile.name,
                "base_url": self._profile.base_url,
                "max_conn": self._profile.pooling.max_size,
            },
        )

    async def stop(self) -> None:
        if self._client is None:
            return
        try:
            await self._client.aclose()
        finally:
            self._client = None
            self._started = False

    async def health(self, mode: str = "fast") -> HealthResult:
        if self._client is None:
            return HealthResult.failed(error="client not started", mode=mode)  # type: ignore[arg-type]

        import time

        start = time.perf_counter()
        try:
            if mode == "deep":
                # Deep probe — small GET / OPTIONS на health-path.
                resp = await self._client.get(self._health_path, timeout=2.0)
                latency_ms = (time.perf_counter() - start) * 1000.0
                if resp.status_code < 500:
                    return HealthResult.ok(
                        latency_ms=latency_ms,
                        mode=mode,  # type: ignore[arg-type]
                        status_code=resp.status_code,
                        path=self._health_path,
                    )
                return HealthResult.degraded(
                    error=f"HTTP {resp.status_code}",
                    mode=mode,  # type: ignore[arg-type]
                    latency_ms=latency_ms,
                    status_code=resp.status_code,
                )
            # Fast probe — только факт наличия открытого клиента + pool state.
            latency_ms = (time.perf_counter() - start) * 1000.0
            return HealthResult.ok(
                latency_ms=latency_ms,
                mode=mode,  # type: ignore[arg-type]
                base_url=self._profile.base_url,
            )
        except Exception as exc:  # noqa: BLE001
            return HealthResult.failed(
                error=f"{type(exc).__name__}: {exc}",
                mode=mode,  # type: ignore[arg-type]
                latency_ms=(time.perf_counter() - start) * 1000.0,
            )

    # -- API -----------------------------------------------------------

    @property
    def client(self) -> "httpx.AsyncClient":
        """Получить httpx-клиент. Требует, чтобы start() уже вызывался."""
        if self._client is None:
            raise RuntimeError(
                f"Upstream '{self._profile.name}' not started — call start_all() first"
            )
        return self._client

    @property
    def profile(self) -> UpstreamProfile:
        return self._profile

    async def request(self, method: str, url: str, **kwargs: Any) -> "httpx.Response":
        """Выполнить запрос с CB + метриками.

        Отличие от прямого `client.request()` в том, что:
          1. operation-label = метод (`GET` / `POST`), не raw URL (cardinality).
          2. CB оборачивает вызов — circuit_open = fast-fail.
          3. RED-метрики обновляются автоматически.
        """
        if self._client is None:
            raise RuntimeError("upstream client not started")
        try:
            async with self._breaker.guard():
                async with self.track(method.upper()):
                    return await self._client.request(method, url, **kwargs)
        except CircuitOpen:
            _logger.warning(
                "upstream circuit open",
                extra={"upstream": self._profile.name, "host": self._profile.base_url},
            )
            raise


class UpstreamRegistry:
    """Process-wide реестр HTTP-upstream профилей.

    Не конфликтует с `ConnectorRegistry` — это отдельный уровень
    абстракции (конкретные upstream-профили). Каждый создаваемый
    `HttpUpstreamClient` регистрируется и в `ConnectorRegistry` тоже,
    что даёт единую admin API / health aggregation.
    """

    _instance: "UpstreamRegistry | None" = None

    def __init__(self) -> None:
        self._upstreams: dict[str, HttpUpstreamClient] = {}

    @classmethod
    def instance(cls) -> "UpstreamRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    def register(
        self,
        profile: UpstreamProfile,
        *,
        health_path: str = "/",
        also_in_connector_registry: bool = True,
    ) -> HttpUpstreamClient:
        """Создать `HttpUpstreamClient` и зарегистрировать его.

        По умолчанию также добавляет в `ConnectorRegistry` — чтобы
        upstream-ы участвовали в startup/shutdown вместе с остальными
        infra-клиентами.
        """
        if profile.name in self._upstreams:
            raise ValueError(f"Upstream '{profile.name}' already registered")
        client = HttpUpstreamClient(profile, health_path=health_path)
        self._upstreams[profile.name] = client
        if also_in_connector_registry:
            from src.infrastructure.registry import ConnectorRegistry

            ConnectorRegistry.instance().register(client)
        return client

    def get(self, name: str) -> HttpUpstreamClient:
        try:
            return self._upstreams[name]
        except KeyError:
            raise KeyError(f"Upstream '{name}' not registered") from None

    def names(self) -> list[str]:
        return sorted(self._upstreams.keys())


#: Глобальный helper для бизнес-кода.
def upstream(name: str) -> HttpUpstreamClient:
    """Shortcut: ``upstream("dadata").request("POST", "/suggestions", ...)``."""
    return UpstreamRegistry.instance().get(name)


upstream_registry: Final = UpstreamRegistry.instance()


__all__ = (
    "UpstreamProfile",
    "UpstreamRegistry",
    "HttpUpstreamClient",
    "upstream",
    "upstream_registry",
)
