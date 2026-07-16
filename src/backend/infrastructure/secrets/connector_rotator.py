"""Connector rotation bridge (Security Wave S5).

Когда Vault ротирует секрет, подписанные на этот path коннекторы
автоматически перезагружаются с новыми credentials.

Использование::

    # В setup_infra:connector_setup()
    await rotator.subscribe(
        connector_name="kafka_main",
        vault_path="kv/data/kafka/credentials",
        reload_fn=lambda: kafka_pool.reload(),
    )
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from src.backend.core.logging import get_logger

__all__ = ("ConnectorRotator", "get_connector_rotator")


class ConnectorRotator:
    """Subscribe-based rotation: vault path → connector reload function."""

    def __init__(self) -> None:
        self._subscriptions: dict[str, list[tuple[str, Callable[..., Awaitable[None]]]]] = {}
        self._lock = asyncio.Lock()
        self._logger = get_logger("security.rotator")

    async def subscribe(
        self,
        *,
        connector_name: str,
        vault_path: str,
        reload_fn: Callable[..., Awaitable[None]],
    ) -> None:
        async with self._lock:
            self._subscriptions.setdefault(vault_path, []).append(
                (connector_name, reload_fn)
            )
            self._logger.info(
                "Connector subscribed to vault rotation",
                extra={"connector": connector_name, "vault_path": vault_path},
            )

    async def on_rotation(self, vault_path: str, new_value: Any) -> int:
        """Вызывается VaultSecretRefresher при ротации.

        Returns:
            Число успешно перезагруженных коннекторов.
        """
        subs = self._subscriptions.get(vault_path, [])
        ok_count = 0
        for name, reload_fn in subs:
            try:
                await reload_fn()
                ok_count += 1
                self._logger.info(
                    "Connector reloaded after rotation",
                    extra={"connector": name, "vault_path": vault_path},
                )
            except Exception as exc:
                self._logger.error(
                    "Connector reload failed",
                    extra={
                        "connector": name,
                        "vault_path": vault_path,
                        "error": str(exc),
                    },
                )
        return ok_count


_instance: ConnectorRotator | None = None


def get_connector_rotator() -> ConnectorRotator:
    global _instance
    if _instance is None:
        _instance = ConnectorRotator()
    return _instance
