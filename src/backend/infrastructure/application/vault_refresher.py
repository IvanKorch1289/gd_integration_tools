"""Периодическое обновление секретов из HashiCorp Vault.

Запускается как фоновая задача при старте приложения.
Проверяет Vault каждые N минут и обновляет in-memory настройки.

IL2.4 (ADR-022): расширение до per-path подписок. Помимо глобального
env-based callback (``on_refresh``), теперь поддерживаются:

  * ``watch(path)`` — добавить конкретный secret-path в отслеживание.
  * ``on_rotation(path, callback)`` — per-path callback.

Это позволяет `ConnectorRegistry` подписать ``registry.reload(name)`` на
ротацию secret-path конкретного клиента (например, ``database/creds/app``
триггерит reload Postgres, без рестарта приложения).
"""

import asyncio
import logging
from collections import defaultdict
from os import getenv
from typing import Any, Awaitable, Callable

__all__ = ("VaultSecretRefresher", "get_vault_refresher")

logger = logging.getLogger("vault.refresher")


RotationCallback = Callable[[str, dict[str, Any]], Awaitable[None] | None]


class VaultSecretRefresher:
    """Фоновое обновление секретов из Vault."""

    def __init__(self, refresh_interval_seconds: int = 300) -> None:
        self._interval = refresh_interval_seconds
        self._running = False
        self._task: asyncio.Task | None = None
        self._last_version: str | None = None
        self._callbacks: list[Any] = []
        # IL2.4: per-path tracking + callbacks.
        self._tracked_paths: dict[str, str | None] = {}
        self._path_callbacks: dict[str, list[RotationCallback]] = defaultdict(list)

    def on_refresh(self, callback: Any) -> None:
        """Регистрирует callback при обновлении секретов (legacy, глобальный)."""
        self._callbacks.append(callback)

    # -- IL2.4: per-path API ----------------------------------------

    def watch(self, path: str) -> None:
        """Добавить secret-path в отслеживание.

        Первая версия фиксируется при следующем check-цикле; callbacks на
        этот path будут вызываться только при **последующих** ротациях,
        а не при первом обнаружении.
        """
        if path not in self._tracked_paths:
            self._tracked_paths[path] = None
            logger.info("vault path watched", extra={"path": path})

    def on_rotation(self, path: str, callback: RotationCallback) -> None:
        """Подписаться на ротацию конкретного secret-path.

        Callback получает `(path, new_secrets_data)`. Может быть sync или
        async. Ошибки внутри callback'а логируются, но не прерывают цикл
        (один упавший клиент не должен ломать ротацию остальных).

        Для валидности подписки нужно также вызвать `watch(path)` —
        регистратор (`ConnectorRegistry` bridge) делает это автоматически.
        """
        self._path_callbacks[path].append(callback)
        self.watch(path)

    async def start(self) -> None:
        """Запускает фоновый refresh loop."""
        vault_addr = getenv("VAULT_ADDR")
        if not vault_addr:
            logger.info("VAULT_ADDR not set — secret refresh disabled")
            return

        self._running = True
        self._task = asyncio.create_task(self._refresh_loop())
        logger.info("Vault secret refresher started (interval=%ds)", self._interval)

    async def stop(self) -> None:
        """Останавливает refresh loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Vault secret refresher stopped")

    async def _refresh_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self._interval)
                await self._check_and_refresh()
                await self._check_tracked_paths()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Vault refresh error: %s", exc)
                await asyncio.sleep(30)

    async def _check_and_refresh(self) -> None:
        """Проверяет Vault на новые версии секретов."""
        vault_addr = getenv("VAULT_ADDR")
        vault_token = getenv("VAULT_TOKEN")
        vault_path = getenv("VAULT_SECRET_PATH")

        if not all([vault_addr, vault_token, vault_path]):
            return

        try:
            from hvac import Client

            client = Client(url=vault_addr, token=vault_token)
            if not client.is_authenticated():
                logger.warning("Vault token expired — attempting re-auth")
                return

            response = client.secrets.kv.v2.read_secret_version(path=vault_path)
            metadata = response.get("data", {}).get("metadata", {})
            current_version = str(metadata.get("version", "0"))

            if self._last_version is not None and current_version != self._last_version:
                logger.info(
                    "Vault secrets updated: v%s → v%s",
                    self._last_version,
                    current_version,
                )
                secrets_data = response.get("data", {}).get("data", {})
                await self._notify_callbacks(secrets_data)

            self._last_version = current_version

        except ImportError:
            logger.debug("hvac not installed — Vault refresh skipped")
        except Exception as exc:
            logger.error("Vault check failed: %s", exc)

    async def _notify_callbacks(self, new_secrets: dict[str, Any]) -> None:
        """Уведомляет подписчиков об обновлении секретов."""
        for cb in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(new_secrets)
                else:
                    cb(new_secrets)
            except Exception as exc:
                logger.error("Vault refresh callback error: %s", exc)

    # -- IL2.4: per-path checks ------------------------------------

    async def _check_tracked_paths(self) -> None:
        """Проверить версии всех отслеживаемых path-ов и триггернуть callbacks.

        Использует тот же Vault-клиент. Ошибки per-path локализуются: если
        один path упал, остальные продолжают обрабатываться.
        """
        if not self._tracked_paths:
            return

        vault_addr = getenv("VAULT_ADDR")
        vault_token = getenv("VAULT_TOKEN")
        if not all([vault_addr, vault_token]):
            return

        try:
            from hvac import Client
        except ImportError:
            return

        client = Client(url=vault_addr, token=vault_token)
        if not client.is_authenticated():
            logger.warning("Vault token expired for tracked-paths check")
            return

        for path, last_v in list(self._tracked_paths.items()):
            try:
                response = client.secrets.kv.v2.read_secret_version(path=path)
                metadata = response.get("data", {}).get("metadata", {})
                current_version = str(metadata.get("version", "0"))
                if last_v is not None and current_version != last_v:
                    secrets_data = response.get("data", {}).get("data", {})
                    logger.info(
                        "vault path rotated",
                        extra={"path": path, "from": last_v, "to": current_version},
                    )
                    await self._notify_path_callbacks(path, secrets_data)
                self._tracked_paths[path] = current_version
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "vault path check failed", extra={"path": path, "error": str(exc)}
                )

    async def _notify_path_callbacks(
        self, path: str, new_secrets: dict[str, Any]
    ) -> None:
        for cb in self._path_callbacks.get(path, []):
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(path, new_secrets)
                else:
                    cb(path, new_secrets)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "vault rotation callback error",
                    extra={"path": path, "error": str(exc)},
                )


from src.backend.core.di import app_state_singleton


@app_state_singleton("vault_refresher", VaultSecretRefresher)
def get_vault_refresher() -> VaultSecretRefresher:
    """Возвращает VaultSecretRefresher из app.state или lazy-init fallback."""
