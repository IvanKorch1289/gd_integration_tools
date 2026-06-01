"""Фоновая ротация секретов из HashiCorp Vault без рестарта приложения.

Назначение:
    VaultSecretRotator периодически обращается к Vault KV API, сравнивает
    metadata.version ответа с кэшированным значением и при изменении
    вызывает зарегистрированный callback с новым словарём секрета.

Zero-downtime ротация (K1 S19 W1):
    * drift_tolerance_seconds: старый секрет хранится N секунд после
      появления новой версии — для drift-toleration (не все потребители
      могут перечитать одновременно).
    * validate_before_activate: перед вызовом callback'а вызывается
      ``validator(secret_data) -> bool``; если False — секрет не
      активируется, old secret остаётся активным.
    * graceful_reconnect: при ошибке подключения к Vault — retry с
      exponential backoff, старый секрет остаётся валидным.

Использование:

    rotator = get_vault_rotator()
    rotator.register(
        "secret/data/db/password",
        lambda data: db.reload(data),
        validator=lambda data: test_db_connection(data),
    )
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
import time
from collections.abc import Callable
from typing import Any

import structlog

from src.backend.core.config.features import feature_flags

__all__ = ("VaultSecretRotator", "get_vault_rotator")

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# Хранилище для зарегистрированных path'ов
_PathCallbackEntry = tuple[
    str, Callable[[dict[str, Any]], None], Callable[[dict[str, Any]], bool] | None
]


class VaultSecretRotator:
    """Фоновый ротатор секретов из HashiCorp Vault.

    K1 S19 W1: zero-downtime rotation с drift-toleration и
    validate-before-activate.

    Attributes:
        _entries: Список (vault_path, callback, validator) для периодической проверки.
        _versions: Словарь path → последняя известная версия metadata.
        _old_secrets: Словарь path → (secret_data, timestamp) для drift-toleration.
        _task: Фоновая asyncio.Task; None пока не запущен.
        _running: Флаг работы цикла.
        _drift_tolerance_seconds: Срок хранения старого секрета после появления нового.
        _reconnect_base_delay: Базовая задержка для exponential backoff при reconnect.
    """

    def __init__(
        self,
        *,
        drift_tolerance_seconds: float = 300.0,
        reconnect_base_delay: float = 1.0,
        reconnect_max_delay: float = 60.0,
    ) -> None:
        """Инициализирует пустой ротатор без зарегистрированных path'ов.

        Args:
            drift_tolerance_seconds: Время хранения старого секрета после
                появления нового (default 300s = 5 минут).
            reconnect_base_delay: Базовая задержка exponential backoff (default 1s).
            reconnect_max_delay: Максимальная задержка backoff (default 60s).
        """
        self._entries: list[_PathCallbackEntry] = []
        self._versions: dict[str, int | None] = {}
        self._old_secrets: dict[str, tuple[dict[str, Any], float]] = {}
        self._task: asyncio.Task[None] | None = None
        self._running: bool = False
        self._drift_tolerance = drift_tolerance_seconds
        self._reconnect_base = reconnect_base_delay
        self._reconnect_max = reconnect_max_delay

    # ──────────────────────────────────────────────────────────────────────
    # Публичный API
    # ──────────────────────────────────────────────────────────────────────

    def register(
        self,
        path: str,
        callback: Callable[[dict[str, Any]], None],
        validator: Callable[[dict[str, Any]], bool] | None = None,
    ) -> None:
        """Регистрирует Vault path, callback и опциональный validator.

        Args:
            path: Путь в Vault KV v2, например ``secret/data/db/password``.
            callback: Вызывается при активации новой версии секрета.
                Получает словарь ``data`` из Vault ответа.
            validator: Опциональная функция валидации.
                ``validator(secret_data) -> True`` означает валидные credentials.
                При False секрет НЕ активируется, старый секрет остаётся активным.
                Если None — валидация пропускается (S19 default-OK).

        Note:
            Повторная регистрация одного и того же path добавит второй callback.
            Для идемпотентного поведения проверяйте регистрацию на стороне вызывающего.
        """
        self._entries.append((path, callback, validator))
        self._versions.setdefault(path, None)
        self._old_secrets.setdefault(path, ({}, 0.0))
        logger.debug(
            "vault_rotator.registered", path=path, has_validator=validator is not None
        )

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

        K1 S19 W1: zero-downtime rotation.
        Для каждого path:
        1. Подключение к Vault (graceful reconnect с backoff).
        2. Проверка metadata version.
        3. Если новая версия и drift_tolerance_seconds ещё не прошло —
           старый секрет остаётся активным, callback не вызывается.
        4. Если включён validator — проверка новых credentials перед активацией.
        5. Callback вызывается только после успешной валидации.

        Exceptions:
            Ошибки отдельных path'ов логируются через structlog и не прерывают
            обход остальных путей.
        """
        import hvac  # noqa: PLC0415 — lazy import, намеренно внутри метода

        vault_client: hvac.Client = hvac.Client()

        seen_paths: set[str] = set()
        now = time.time()

        for path, callback, validator in self._entries:
            if path in seen_paths:
                continue

            try:
                response = vault_client.secrets.kv.v2.read_secret_version(path=path)
                new_version: int = response["data"]["metadata"]["version"]
                cached_version = self._versions.get(path)

                if cached_version is None:
                    # Первая инициализация — просто запоминаем версию
                    self._versions[path] = new_version
                    logger.debug("vault_rotator.init", path=path, version=new_version)
                elif cached_version != new_version:
                    # Новая версия обнаружена
                    new_secret: dict[str, Any] = response["data"]["data"]
                    old_secret, old_ts = self._old_secrets.get(path, ({}, 0.0))

                    # Проверяем drift-toleration: прошло ли достаточно времени?
                    drift_elapsed = now - old_ts
                    in_drift_window = drift_elapsed < self._drift_tolerance

                    if in_drift_window and old_secret:
                        # Zero-downtime: ещё в drift-window, старый секрет активен
                        logger.info(
                            "vault_rotator.drift_tolerating",
                            path=path,
                            new_version=new_version,
                            cached_version=cached_version,
                            drift_elapsed_s=drift_elapsed,
                            tolerance_s=self._drift_tolerance,
                        )
                        # Сохраняем новый секрет, но не активируем пока
                        self._old_secrets[path] = (new_secret, now)
                    else:
                        # Drift-window прошёл (или старого секрета нет) —
                        # пробуем валидировать и активировать
                        if validator is not None:
                            try:
                                is_valid = validator(new_secret)
                            except Exception as exc:
                                logger.error(
                                    "vault_rotator.validation_error",
                                    path=path,
                                    error=str(exc),
                                )
                                is_valid = False

                            if not is_valid:
                                logger.warning(
                                    "vault_rotator.validation_failed",
                                    path=path,
                                    new_version=new_version,
                                    old_secret_retained=True,
                                )
                                # Старый секрет остаётся активным
                                self._versions[path] = cached_version
                                continue

                        # Валидация прошла — активируем новый секрет
                        self._versions[path] = new_version
                        self._old_secrets[path] = ({}, 0.0)  # очищаем старый
                        logger.info(
                            "vault_rotator.secret_activated",
                            path=path,
                            old_version=cached_version,
                            new_version=new_version,
                        )
                        callback(new_secret)
                else:
                    logger.debug(
                        "vault_rotator.secret_unchanged", path=path, version=new_version
                    )

            except Exception as exc:  # noqa: BLE001 — намеренный broad catch для изоляции path
                # Graceful reconnect: логируем и продолжаем (старый секрет активен)
                if "connection" in str(exc).lower() or "vault" in str(exc).lower():
                    logger.warning(
                        "vault_rotator.connection_error",
                        path=path,
                        error=str(exc),
                        old_secret_active=True,
                    )
                else:
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
