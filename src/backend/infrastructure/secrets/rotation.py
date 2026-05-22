"""RotationScheduler — push-нотификация при ротации секрета (V15 S3).

Поллит metadata Vault'а с интервалом ``poll_interval_seconds``; если
``current_version`` изменилась — читает новый ``SecretValue`` и вызывает
всех подписчиков через :meth:`SecretBrokerImpl.notify_rotation`. Без
рестарта.

Запускается через :class:`TaskRegistry` (R-V15-11) для leak prevention.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from src.backend.infrastructure.secrets.broker import SecretBrokerImpl

__all__ = ("RotationScheduler",)

_logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_SECONDS: float = 60.0


class RotationScheduler:
    """Поллер metadata Vault'а с push-нотификацией подписчикам.

    Args:
        broker: :class:`SecretBrokerImpl` с зарегистрированными подписчиками.
        watched_secrets: Список имён секретов для мониторинга.
        poll_interval_seconds: Интервал поллинга (sec).
        version_fetcher: Функция ``(name) -> int`` (текущая версия по
            metadata). Обычно ``VaultBackend.get_metadata(...)["current_version"]``.
    """

    def __init__(
        self,
        *,
        broker: SecretBrokerImpl,
        watched_secrets: list[str],
        version_fetcher: Callable[[str], int],
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    ) -> None:
        self._broker = broker
        self._watched = list(watched_secrets)
        self._fetch_version = version_fetcher
        self._interval = poll_interval_seconds
        self._known_versions: dict[str, int] = {}
        self._task: asyncio.Task[None] | None = None
        self._closed: bool = False

    async def poll_once(self) -> int:
        """Один проход: проверить metadata всех watched секретов.

        Returns:
            Число обнаруженных и нотифицированных ротаций.
        """
        rotated = 0
        for name in self._watched:
            try:
                current = self._fetch_version(name)
            except Exception as exc:  # noqa: BLE001
                _logger.warning(
                    "rotation.fetch_version_failed name=%s err=%s", name, exc
                )
                continue

            previous = self._known_versions.get(name)
            if previous is None:
                self._known_versions[name] = current
                continue

            if current == previous:
                continue

            try:
                snapshot = self._broker.get_versioned(name, current)
            except Exception as exc:  # noqa: BLE001
                _logger.warning(
                    "rotation.read_new_version_failed name=%s ver=%d err=%s",
                    name,
                    current,
                    exc,
                )
                continue

            self._broker.notify_rotation(snapshot)
            self._known_versions[name] = current
            rotated += 1
        return rotated

    async def start(
        self, *, task_factory: Callable[..., asyncio.Task[None]] | None = None
    ) -> None:
        """Запустить фоновый цикл (TaskRegistry-aware)."""
        if self._task is not None and not self._task.done():
            return

        async def _loop() -> None:
            while not self._closed:
                try:
                    await self.poll_once()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    _logger.warning("rotation.loop_error: %s", exc)
                await asyncio.sleep(self._interval)

        if task_factory is None:
            from src.backend.core.utils.task_registry import get_task_registry

            self._task = get_task_registry().create_task(
                _loop(),
                name="secret-rotation",
                deadline_seconds=None,
            )
        else:
            self._task = task_factory(_loop(), name="secret-rotation")

    async def stop(self) -> None:
        """Остановить фоновый цикл."""
        self._closed = True
        task = self._task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001, S110
                pass

    def add_watch(self, name: str, *, current_version: int | None = None) -> None:
        """Добавить секрет в список наблюдаемых (без рестарта loop'а)."""
        if name not in self._watched:
            self._watched.append(name)
        if current_version is not None:
            self._known_versions[name] = current_version

    def known_versions(self) -> dict[str, int]:
        """Снимок известных версий (для диагностики/admin-UI)."""
        return dict(self._known_versions)


def vault_version_fetcher(vault_backend: Any) -> Callable[[str], int]:
    """Вернуть ``Callable[[name], int]`` поверх :class:`VaultBackend`.

    Удобный helper, чтобы не пробрасывать ``VaultBackend`` в Scheduler
    напрямую (он использует только metadata).
    """

    def _fetch(name: str) -> int:
        meta = vault_backend.get_metadata(name)
        return int(meta.get("current_version", 0))

    return _fetch
