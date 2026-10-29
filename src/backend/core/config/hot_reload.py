"""Горячая перезагрузка конфигурации без рестарта приложения.

Модуль использует :mod:`watchfiles` для отслеживания изменений в ``.env``
и YAML-конфигах, и публикует событие через callback-реестр. Подписчики
(LLM-провайдеры, cache, feature flags) переподгружают свои настройки.

Также доступен ручной триггер через админ-эндпоинт ``POST /admin/config/reload``
для ситуаций, когда файловая система не проксируется в контейнер (read-only FS).

Принципы:

* Watcher живёт в отдельной asyncio-таске, запускается в ``lifespan.startup``.
* Callbacks выполняются последовательно, чтобы избежать гонок.
* Ошибки callback'а логируются, но не останавливают watcher.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.core.utils.task_registry import get_task_registry

__all__ = ("ConfigHotReloader", "ConfigReloadError", "get_hot_reloader")

logger = get_logger("config.hot_reload")

ReloadCallback = Callable[[], Awaitable[None] | None]

#: Период опроса файловой системы (``watchfiles.awatch(step=...)``), мс.
#: Это НЕ окно группировки изменений — за него отвечает ``debounce``.
_WATCH_STEP_MS: int = 50


class ConfigReloadError(RuntimeError):
    """Ошибка перезагрузки конфигурации: часть моделей не собралась.

    ADR-0379: ``settings.reload()`` возвращает отчёт
    ``{"reloaded": [...], "failed": [...]}``. Раньше отчёт игнорировался,
    и битый YAML давал ложный успех ``ok=True`` в
    ``POST /admin/config/reload``.
    """

    def __init__(self, failed: list[dict[str, str]]) -> None:
        """Создаёт ошибку с перечнем не перезагруженных настроек.

        Args:
            failed: Список ``{"name": ..., "error": ...}`` из отчёта reload.

        """
        self.failed = failed
        names = ", ".join(str(item.get("name", "?")) for item in failed[:5])
        super().__init__(f"Не удалось перезагрузить {len(failed)} настроек: {names}")


class ConfigHotReloader:
    """Отслеживает изменения конфигурационных файлов и вызывает callback'и.

    Использование::

        reloader = get_hot_reloader()
        reloader.watch(Path(".env"))
        reloader.watch(Path("configs/routes.yaml"))
        reloader.on_reload(lambda: settings.reload())
        await reloader.start()

    После изменения любого отслеживаемого файла все зарегистрированные
    callback'и будут вызваны (по порядку регистрации).
    """

    def __init__(self, *, debounce_ms: int = 1600) -> None:
        """Создаёт watcher конфигурации.

        Args:
            debounce_ms: Окно группировки изменений ФС в миллисекундах
                (параметр ``debounce`` в ``watchfiles.awatch``). ADR-0379:
                раньше это значение передавалось в ``step`` (период
                опроса), а ``debounce`` оставался 1600 мс — имя
                параметра не соответствовало поведению.

        """
        self._paths: set[Path] = set()
        self._callbacks: list[ReloadCallback] = []
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._debounce_ms = debounce_ms

    def watch(self, path: str | Path) -> None:
        """Добавляет файл или директорию в список отслеживаемых.

        Путь приводится к абсолютному (ADR-0372): относительный
        ``config_profiles`` зависел от текущего рабочего каталога и
        «терял» watcher при запуске не из корня репозитория.

        Args:
            path: Файл или директория для наблюдения.

        Returns:
            None.

        """
        self._paths.add(Path(path).absolute())

    def on_reload(self, callback: ReloadCallback) -> None:
        """Регистрирует callback, вызываемый при изменении."""
        self._callbacks.append(callback)

    async def trigger_reload(self, reason: str = "manual") -> dict[str, Any]:
        """Вручную вызывает все callback'и (для админ-эндпоинта).

        Отчёт честный (ADR-0372): если callback'ов нет или callback
        завершился ошибкой — это попадает в ``failed``, а не в ``succeeded``.
        Раньше отсутствие ``settings.reload()`` давало ложный успех
        ``{"succeeded": 1, "failed": []}``.

        Args:
            reason: Причина перезагрузки (для логов и отчёта).

        Returns:
            Отчёт ``{"reason", "succeeded", "failed", "callbacks", "ok"}``.

        """
        if not self._callbacks:
            logger.error(
                "Config reload requested (%s), но ни один callback не зарегистрирован",
                reason,
            )
            return {
                "reason": reason,
                "succeeded": 0,
                "failed": [
                    {
                        "callback": "<none>",
                        "error": (
                            "no reload callbacks registered — "
                            "конфигурация не перезагружена"
                        ),
                    }
                ],
                "callbacks": 0,
                "ok": False,
            }

        ok, failed = 0, []
        for cb in self._callbacks:
            try:
                result = cb()
                if asyncio.iscoroutine(result):
                    await result
                ok += 1
            except Exception as exc:
                entry: dict[str, Any] = {
                    "callback": getattr(cb, "__name__", repr(cb)),
                    "error": str(exc),
                }
                if isinstance(exc, ConfigReloadError):
                    entry["failed"] = exc.failed
                failed.append(entry)
                logger.error("Hot-reload callback failed: %s", exc)
        logger.info("Config reloaded (%s): %d OK, %d failed", reason, ok, len(failed))
        return {
            "reason": reason,
            "succeeded": ok,
            "failed": failed,
            "callbacks": len(self._callbacks),
            "ok": not failed,
        }

    async def start(self) -> None:
        """Запускает watcher в отдельной таске."""
        if self._task and not self._task.done():
            return  # уже запущен

        # K1 S19 W6: Disable hot-reload when APP_PROFILE=prod and flag is set
        from src.backend.core.config.features import feature_flags
        from src.backend.core.config.profile import get_active_profile

        if (
            get_active_profile().value == "prod"
            and feature_flags.prod_hot_reload_disable
        ):
            logger.info(
                "Config hot-reload disabled (APP_PROFILE=prod, prod_hot_reload_disable=True)"
            )
            return

        self._stop_event.clear()
        self._task = get_task_registry().create_task(
            self._watch_loop(), name="config-hot-reload"
        )
        # ADR-0379: дать watcher'у подписаться на ФС ДО возврата из start().
        # create_task только планирует запуск — без yield событие, случившееся
        # в том же тике (запись файла сразу после start()), терялось.
        await asyncio.sleep(0)
        logger.info("Config hot-reload started, watching %d paths", len(self._paths))

    async def stop(self) -> None:
        """Останавливает watcher."""
        self._stop_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:  # noqa: violation-check — expected after cancel
                pass

    async def _watch_loop(self) -> None:
        """Главный цикл: слушает watchfiles, дебаунсит, вызывает callback'и."""
        try:
            from watchfiles import awatch
        except ImportError:
            logger.warning("watchfiles не установлен — hot-reload отключён")
            return

        paths = [str(p) for p in self._paths if p.exists()]
        if not paths:
            logger.warning("Hot-reload: нет существующих путей для наблюдения")
            return

        # debounce=debounce_ms собирает пакет изменений за интервал — избегает
        # множественных срабатываний при сохранении редактором (который
        # обычно создаёт tmp-файл и затем переименовывает). step — период
        # опроса ФС (ADR-0379: раньше сюда попадало значение debounce).
        async for _changes in awatch(
            *paths,
            step=_WATCH_STEP_MS,
            debounce=self._debounce_ms,
            stop_event=self._stop_event,
        ):
            await self.trigger_reload(reason="file-change")


_reloader: ConfigHotReloader | None = None


def get_hot_reloader() -> ConfigHotReloader:
    """Singleton hot-reloader'а для всего приложения."""
    global _reloader
    if _reloader is None:
        _reloader = ConfigHotReloader()
    return _reloader


def register_settings_reload_callback(reloader: ConfigHotReloader) -> None:
    """Регистрирует callback перезагрузки настроек (``settings.reload()``).

    ADR-0372: метод ``settings.reload()`` обязан существовать. Если его
    нет — callback падает с ``RuntimeError``, и ``trigger_reload``
    сообщает об ОШИБКЕ. Раньше callback тихо ничего не делал, а
    ``POST /admin/config/reload`` отвечал ложным успехом
    ``{"succeeded": 1, "failed": []}``.

    ADR-0379: отчёт ``settings.reload()`` больше не игнорируется —
    непустой ``failed`` (например, битый YAML) превращается в
    :class:`ConfigReloadError`, поэтому админ-эндпоинт отвечает ошибкой,
    а не ``ok=True``.

    Args:
        reloader: Hot-reloader, в который регистрируется callback.

    Returns:
        None.

    """
    from src.backend.core.config.settings import settings

    async def _reload_settings() -> None:
        """Перечитывает конфигурацию и обновляет настройки in-place.

        Raises:
            RuntimeError: Если ``settings.reload()`` недоступен.
            ConfigReloadError: Если часть настроек не перезагрузилась.

        """
        reload_fn = getattr(settings, "reload", None)
        if not callable(reload_fn):
            raise RuntimeError(
                "settings.reload() недоступен — конфигурация не перезагружена"
            )
        result = reload_fn()
        if asyncio.iscoroutine(result):
            result = await result
        failed = list((result or {}).get("failed") or [])
        if failed:
            raise ConfigReloadError(failed)

    reloader.on_reload(_reload_settings)
