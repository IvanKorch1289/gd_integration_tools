"""Периодическое обновление секретов из HashiCorp Vault.

Запускается как фоновая задача при старте приложения.
Проверяет Vault каждые N минут и обновляет in-memory настройки.
"""

import asyncio
import logging
from os import getenv
from typing import Any

__all__ = ("VaultSecretRefresher", "get_vault_refresher")

logger = logging.getLogger("vault.refresher")


class VaultSecretRefresher:
    """Фоновое обновление секретов из Vault."""

    def __init__(
        self,
        refresh_interval_seconds: int = 300,
    ) -> None:
        self._interval = refresh_interval_seconds
        self._running = False
        self._task: asyncio.Task | None = None
        self._last_version: str | None = None
        self._callbacks: list[Any] = []

    def on_refresh(self, callback: Any) -> None:
        """Регистрирует callback при обновлении секретов."""
        self._callbacks.append(callback)

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


from app.core.di import app_state_singleton


@app_state_singleton("vault_refresher", VaultSecretRefresher)
def get_vault_refresher() -> VaultSecretRefresher:
    """Возвращает VaultSecretRefresher из app.state или lazy-init fallback."""
