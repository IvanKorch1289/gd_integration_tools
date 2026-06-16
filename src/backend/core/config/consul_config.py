"""Distributed configuration store with hot-reload via Consul.

S36 P4: Consul для хранения констант — замена etcd (уже развёрнут в
организации). Реализует KV-get, put и watch (blocking queries).

Usage::

    from src.backend.core.config.consul_config import ConsulConfigStore

    store = ConsulConfigStore(host="consul.internal", port=8500)
    value = store.get("app/database_url", default="postgres://localhost")

    # Hot-reload подписка (blocking query):
    for new_value in store.watch("app/feature_flag"):
        print(f"Flag changed: {new_value}")
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.backend.core.logging import get_logger

_logger = get_logger("core.config.consul")

__all__ = ("ConsulConfigStore",)


class ConsulConfigStore:
    """Клиент Consul KV с локальным кэшем и blocking-query watch.

    Args:
        host: Адрес Consul-сервера.
        port: Порт HTTP API (default 8500).
        scheme: ``http`` или ``https``.
        token: ACL-токен (опционально).
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8500,
        *,
        scheme: str = "http",
        token: str | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._scheme = scheme
        self._token = token
        self._cache: dict[str, Any] = {}
        self._client: Any | None = None

    def _get_client(self) -> Any:
        """Lazy-import consul — не требуется при отсутствии Consul в окружении."""
        if self._client is None:
            import consul

            self._client = consul.Consul(
                host=self._host, port=self._port, scheme=self._scheme, token=self._token
            )
        return self._client

    def get(self, key: str, default: Any = None) -> Any:
        """Вернуть значение по ключу из Consul KV.

        Результат кэшируется для повторных вызовов в рамках
        lifecycle экземпляра ``ConsulConfigStore``.
        """
        if key in self._cache:
            return self._cache[key]

        try:
            client = self._get_client()
            index, data = client.kv.get(key)
        except Exception as exc:
            _logger.warning("Consul get %s failed: %s", key, exc)
            return default

        if data and data.get("Value"):
            value = data["Value"]
            if isinstance(value, bytes):
                value = value.decode("utf-8")
            self._cache[key] = value
            return value
        return default

    def put(self, key: str, value: str) -> bool:
        """Записать значение в Consul KV.

        Returns:
            ``True`` если запись успешна, иначе ``False``.
        """
        try:
            client = self._get_client()
            client.kv.put(key, value)
            self._cache.pop(key, None)
            return True
        except Exception as exc:
            _logger.warning("Consul put %s failed: %s", key, exc)
            return False

    def watch(self, key: str, callback: Callable[[str], None] | None = None) -> None:
        """Blocking query — hot-reload без restart.

        Бесконечный цикл с blocking-запросом к Consul. При изменении
        значения вызывается ``callback`` (если передан) или просто
        обновляется локальный кэш.

        Args:
            key: Ключ в Consul KV.
            callback: Функция ``(new_value: str) -> None``.

        Note:
            Метод блокирующий; запускать в отдельном asyncio-task
            или thread при использовании в async-контексте.
        """
        try:
            client = self._get_client()
        except Exception as exc:
            _logger.error("Consul watch %s init failed: %s", key, exc)
            return

        index: int | None = None
        while True:
            try:
                index, data = client.kv.get(key, index=index, wait="30s")
            except RuntimeError:
                raise
            except Exception as exc:
                _logger.warning("Consul watch %s error: %s", key, exc)
                continue

            if data and data.get("Value"):
                value = data["Value"]
                if isinstance(value, bytes):
                    value = value.decode("utf-8")
                self._cache[key] = value
                if callback is not None:
                    callback(value)
