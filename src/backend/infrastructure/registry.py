"""ConnectorRegistry — единая точка управления всеми infra-клиентами.

Соответствует ADR-022 и плану IL1.

Registry — process-wide singleton, который хранит все `InfrastructureClient`
экземпляры по имени и обеспечивает:

* Централизованный bootstrap (`start_all`) и shutdown (`stop_all` — reverse
  order).
* Aggregated health (`health_all`) для endpoint
  `/api/v1/health/components?mode=fast|deep`.
* Manual reload (`reload(name)`) для Admin API
  (`POST /api/v1/admin/connectors/{name}/reload`) и для Vault-rotation
  callback (см. `src/core/config/vault_refresher.py`).

Registry **не заменяет** svcs DI (ADR-002) — он дополняет его. svcs продолжает
использоваться для lookup сервиса по типу/имени; Registry — только lifecycle
+ health + reload.

Коммерческий референс — MuleSoft Runtime `ConnectionManager`, WSO2 Carbon
`ServiceBusComponentRegistry`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from src.infrastructure.clients.base_connector import (
        HealthMode,
        HealthResult,
        InfrastructureClient,
    )


_logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ConnectorSpec:
    """Внутренняя запись Registry о зарегистрированном клиенте.

    * ``client`` — экземпляр `InfrastructureClient`.
    * ``vault_path`` — опционально; путь в Vault, обновление которого должно
      триггерить `registry.reload(name)` (IL2.4 Vault hot-reload wiring).
    * ``register_order`` — позиция в порядке регистрации; используется для
      reverse-shutdown.
    """

    client: "InfrastructureClient"
    vault_path: str | None = None
    register_order: int = 0
    _reload_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class ConnectorAlreadyRegisteredError(ValueError):
    """Имя клиента уже занято в Registry."""


class ConnectorNotRegisteredError(KeyError):
    """Запрошен клиент с неизвестным именем."""


class ConnectorRegistry:
    """Process-wide реестр infra-клиентов.

    Не потокобезопасен по самому dict-у регистраций (регистрация ожидается
    однократно в startup), но `reload(name)` защищён per-client lock-ом.
    """

    _instance: "ConnectorRegistry | None" = None

    def __init__(self) -> None:
        self._connectors: dict[str, ConnectorSpec] = {}
        self._order_counter: int = 0

    # -- Singleton -----------------------------------------------------

    @classmethod
    def instance(cls) -> "ConnectorRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Очистить singleton (использовать только в тестах/dev)."""
        cls._instance = None

    # -- Регистрация ---------------------------------------------------

    def register(
        self, client: "InfrastructureClient", *, vault_path: str | None = None
    ) -> None:
        """Зарегистрировать клиент в Registry.

        * ``vault_path`` — если задан, `VaultSecretRefresher` при ротации
          этого path вызовет `registry.reload(client.name)` (wiring — IL2.4).
        """
        if client.name in self._connectors:
            raise ConnectorAlreadyRegisteredError(
                f"Connector '{client.name}' already registered"
            )
        self._order_counter += 1
        self._connectors[client.name] = ConnectorSpec(
            client=client, vault_path=vault_path, register_order=self._order_counter
        )

    def unregister(self, name: str) -> None:
        """Убрать клиент из Registry (не вызывает stop — предполагается, что
        клиент уже остановлен).
        """
        self._connectors.pop(name, None)

    # -- Доступ --------------------------------------------------------

    def get(self, name: str) -> "InfrastructureClient":
        """Получить клиент по имени. Бросает `ConnectorNotRegisteredError`."""
        spec = self._connectors.get(name)
        if spec is None:
            raise ConnectorNotRegisteredError(f"Connector '{name}' not registered")
        return spec.client

    def names(self) -> list[str]:
        """Список всех зарегистрированных имён (в порядке регистрации)."""
        return [
            name
            for name, _ in sorted(
                self._connectors.items(), key=lambda kv: kv[1].register_order
            )
        ]

    def vault_path(self, name: str) -> str | None:
        """Vault-путь, на который подписан клиент (если есть)."""
        spec = self._connectors.get(name)
        return spec.vault_path if spec else None

    # -- Lifecycle -----------------------------------------------------

    async def start_all(self) -> None:
        """Поднять все клиенты в порядке регистрации.

        При ошибке старта какого-либо клиента — откатить уже поднятые
        (reverse order stop) и прокинуть исключение.
        """
        started: list[str] = []
        for name in self.names():
            client = self._connectors[name].client
            try:
                _logger.info("connector starting", extra={"connector": name})
                await client.start()
                started.append(name)
                _logger.info("connector started", extra={"connector": name})
            except Exception as exc:  # noqa: BLE001
                _logger.error(
                    "connector failed to start — rolling back",
                    extra={"connector": name, "error": str(exc)},
                )
                for rollback_name in reversed(started):
                    with suppress(Exception):
                        await self._connectors[rollback_name].client.stop()
                raise

    async def stop_all(self) -> None:
        """Закрыть все клиенты в обратном порядке регистрации.

        Ошибки отдельных клиентов не прерывают shutdown (логируются и идём
        дальше). Graceful timeout берётся из `PoolingProfile.acquire_timeout_s`
        (использован как мягкая верхняя граница per-client).
        """
        for name in reversed(self.names()):
            client = self._connectors[name].client
            timeout = client.pooling.acquire_timeout_s
            _logger.info("connector stopping", extra={"connector": name})
            try:
                await asyncio.wait_for(client.stop(), timeout=timeout)
            except asyncio.TimeoutError:
                _logger.warning(
                    "connector stop timed out",
                    extra={"connector": name, "timeout": timeout},
                )
            except Exception as exc:  # noqa: BLE001
                _logger.error(
                    "connector stop errored",
                    extra={"connector": name, "error": str(exc)},
                )

    async def health_all(
        self, mode: "HealthMode" = "fast"
    ) -> "dict[str, HealthResult]":
        """Параллельный health-check всех клиентов.

        Используется эндпоинтом `/api/v1/health/components?mode=fast|deep`.
        """
        names = self.names()
        if not names:
            return {}
        coros = [self._connectors[n].client.health(mode=mode) for n in names]
        results = await asyncio.gather(*coros, return_exceptions=True)
        out: dict[str, HealthResult] = {}
        for name, result in zip(names, results, strict=True):
            if isinstance(result, Exception):
                # Импорт-поздний чтобы избежать циклов.
                from src.infrastructure.clients.base_connector import (
                    HealthResult as _HR,
                )

                out[name] = _HR.failed(
                    error=f"{type(result).__name__}: {result}", mode=mode
                )
            else:
                out[name] = result
        return out

    async def reload(self, name: str) -> float:
        """Atomic reload одного клиента. Возвращает длительность в мс."""
        spec = self._connectors.get(name)
        if spec is None:
            raise ConnectorNotRegisteredError(f"Connector '{name}' not registered")
        async with spec._reload_lock:
            _logger.info("connector reloading", extra={"connector": name})
            start = time.perf_counter()
            await spec.client.reload()
            duration_ms = (time.perf_counter() - start) * 1000.0
            _logger.info(
                "connector reloaded",
                extra={"connector": name, "duration_ms": duration_ms},
            )
            return duration_ms


#: Глобальный helper для бизнес-кода — не хранит состояние, делегирует в singleton.
def get_registry() -> ConnectorRegistry:
    return ConnectorRegistry.instance()


_PUBLIC: Final = (
    "ConnectorRegistry",
    "ConnectorSpec",
    "ConnectorAlreadyRegisteredError",
    "ConnectorNotRegisteredError",
    "get_registry",
)
__all__ = _PUBLIC
