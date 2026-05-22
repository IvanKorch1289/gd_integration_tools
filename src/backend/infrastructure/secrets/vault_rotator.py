"""Фоновая ротация секретов из HashiCorp Vault без рестарта приложения.

Назначение:
    VaultSecretRotator периодически обращается к Vault KV API, сравнивает
    metadata.version ответа с кэшированным значением и при изменении
    вызывает зарегистрированный callback с новым словарём секрета.

Использование:

    rotator = get_vault_rotator()
    rotator.register("secret/data/db/password", lambda data: db.reload(data))
    await rotator.start(interval_seconds=300)
    # при shutdown:
    await rotator.stop()

Требования:
    - default-OFF под feature_flags.vault_rotation_enabled
    - lazy-import hvac (не подключать при старте, если flag выключен)
    - singleton через get_vault_rotator()
    - все взаимодействия с asyncio — без блокирующих time.sleep()
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import structlog

from src.backend.core.config.features import feature_flags

__all__ = ("VaultSecretRotator", "get_vault_rotator")

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# Хранилище для зарегистрированных path'ов
_PathCallbackEntry = tuple[str, Callable[[dict[str, Any]], None]]


class VaultSecretRotator:
    """Фоновый ротатор секретов из HashiCorp Vault.

    Attributes:
        _entries: Список (vault_path, callback) для периодической проверки.
        _versions: Словарь path → последняя известная версия metadata.
        _task: Фоновая asyncio.Task; None пока не запущен.
        _running: Флаг работы цикла.

    Все docstrings и комментарии на русском (политика проекта).
    """

    def __init__(self) -> None:
        """Инициализирует пустой ротатор без зарегистрированных path'ов."""
        self._entries: list[_PathCallbackEntry] = []
        self._versions: dict[str, int | None] = {}
        self._task: asyncio.Task[None] | None = None
        self._running: bool = False

    # ──────────────────────────────────────────────────────────────────────
    # Публичный API
    # ──────────────────────────────────────────────────────────────────────

    def register(self, path: str, callback: Callable[[dict[str, Any]], None]) -> None:
        """Регистрирует Vault path и callback для периодической проверки.

        Args:
            path: Путь в Vault KV v2, например ``secret/data/db/password``.
            callback: Вызывается при обнаружении новой версии секрета.
                Получает словарь ``data`` из Vault ответа.

        Note:
            Повторная регистрация одного и того же path добавит второй callback.
            Для идемпотентного поведения проверяйте регистрацию на стороне вызывающего.
        """
        self._entries.append((path, callback))
        self._versions.setdefault(path, None)
        logger.debug("vault_rotator.registered", path=path)

    async def start(self, interval_seconds: float = 300.0) -> None:
        """Запускает фоновую задачу ротации через asyncio.create_task.

        Если feature_flags.vault_rotation_enabled == False — запуск пропускается.
        Повторный вызов start() при уже запущенной задаче — игнорируется.

        Args:
            interval_seconds: Интервал между проверками Vault в секундах.
                По умолчанию 300 (5 минут).
        """
        if not feature_flags.vault_rotation_enabled:
            logger.info(
                "vault_rotator.skipped",
                reason="feature_flag vault_rotation_enabled is OFF",
            )
            return

        if self._task is not None and not self._task.done():
            logger.warning("vault_rotator.already_running")
            return

        self._running = True
        from src.backend.core.utils.task_registry import get_task_registry

        self._task = get_task_registry().create_task(
            self._rotation_loop(interval_seconds),
            name="vault-secret-rotation",
            deadline_seconds=None,
        )
        logger.info("vault_rotator.started", interval_seconds=interval_seconds)

    async def stop(self) -> None:
        """Graceful-отмена фоновой задачи ротации.

        Устанавливает флаг _running=False и отменяет asyncio.Task.
        Ожидает завершения задачи перед возвратом.
        """
        self._running = False
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            logger.info("vault_rotator.stopped")
        self._task = None

    async def tick(self) -> None:
        """Один обход всех зарегистрированных path'ов.

        Для каждого path выполняет hvac-запрос к Vault,
        сравнивает metadata version с кэшированным значением
        и при изменении вызывает зарегистрированный callback.

        Hvac импортируется лениво (lazy-import) чтобы не тянуть зависимость
        при старте, когда flag выключен.

        Exceptions:
            Ошибки отдельных path'ов логируются через structlog и не прерывают
            обход остальных путей.
        """
        import hvac  # noqa: PLC0415 — lazy import, намеренно внутри метода

        vault_client: hvac.Client = hvac.Client()

        seen_paths: set[str] = set()
        for path, callback in self._entries:
            if path in seen_paths:
                # Обновление уже было — callback вызывается для каждой записи
                pass
            try:
                response = vault_client.secrets.kv.v2.read_secret_version(path=path)
                new_version: int = response["data"]["metadata"]["version"]
                cached_version = self._versions.get(path)

                if cached_version != new_version:
                    logger.info(
                        "vault_rotator.secret_changed",
                        path=path,
                        old_version=cached_version,
                        new_version=new_version,
                    )
                    self._versions[path] = new_version
                    secret_data: dict[str, Any] = response["data"]["data"]
                    callback(secret_data)
                else:
                    logger.debug(
                        "vault_rotator.secret_unchanged", path=path, version=new_version
                    )
            except Exception as exc:  # noqa: BLE001 — намеренный broad catch для изоляции path
                logger.error("vault_rotator.tick_error", path=path, error=str(exc))
            seen_paths.add(path)

    # ──────────────────────────────────────────────────────────────────────
    # Внутренние методы
    # ──────────────────────────────────────────────────────────────────────

    async def _rotation_loop(self, interval_seconds: float) -> None:
        """Основной цикл ротации.

        Выполняет tick() и спит interval_seconds до следующей итерации.
        Завершается при _running=False или CancelledError.

        Args:
            interval_seconds: Пауза между итерациями в секундах.
        """
        while self._running:
            await self.tick()
            try:
                await asyncio.sleep(interval_seconds)
            except asyncio.CancelledError:
                break


# ──────────────────────────────────────────────────────────────────────────────
# Singleton
# ──────────────────────────────────────────────────────────────────────────────

_vault_rotator_instance: VaultSecretRotator | None = None


def get_vault_rotator() -> VaultSecretRotator:
    """Возвращает singleton экземпляр VaultSecretRotator.

    Создаёт экземпляр при первом вызове; повторные вызовы возвращают тот же объект.

    Returns:
        Единственный экземпляр VaultSecretRotator для текущего процесса.
    """
    global _vault_rotator_instance  # noqa: PLW0603 — намеренный singleton pattern
    if _vault_rotator_instance is None:
        _vault_rotator_instance = VaultSecretRotator()
    return _vault_rotator_instance
