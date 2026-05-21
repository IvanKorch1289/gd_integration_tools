"""Sprint 7 Team T5 — hot-swap API для V11 in-tree плагинов.

Назначение:
    Перезагрузка плагина без рестарта приложения. При hot-swap:

    1. Текущий экземпляр плагина проходит graceful shutdown
       (``on_shutdown``).
    2. Все ранее выданные capability отзываются через
       ``CapabilityGate.revoke``.
    3. Модуль ``entry_class`` принудительно reload-ится через
       ``importlib.reload`` (захватывает изменения исходников
       без рестарта Python-процесса).
    4. ``PluginLoaderV11`` перечитывает ``plugin.toml`` и заново
       выполняет полный lifecycle: проверка ``requires_core`` →
       capability allocation → ``on_load`` → регистрация
       ``actions/repositories/processors``.

    Если ``capabilities[]`` в plugin.toml изменились, новая декларация
    автоматически вступает в силу через :class:`CapabilityGate.declare`
    (audit-event ``capability.allocated`` фиксирует расширение прав).

Использование:
    .. code-block:: python

        from src.backend.core.plugin_runtime.hot_swap import hot_swap

        await hot_swap("example_plugin", loader)

Безопасность:
    Hot-swap НЕ обходит capability-gate. Если новый ``plugin.toml``
    декларирует capability, недоступную в системе, выдача упадёт
    в ``status="failed"`` и плагин останется выгруженным.

    Hot-swap НЕ затрагивает запущенные workflow/route — они
    продолжают работать со ссылками на старые объекты до
    завершения текущих exchanges.
"""

from __future__ import annotations

import importlib
import logging
import sys
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ("HotSwapError", "HotSwapResult", "PluginLoaderProtocol", "hot_swap")

_logger = logging.getLogger("core.plugin_runtime.hot_swap")


class HotSwapError(RuntimeError):
    """Hot-swap не удался — причина в ``reason`` и ``cause``."""

    def __init__(
        self, plugin_name: str, reason: str, *, cause: Exception | None = None
    ) -> None:
        self.plugin_name = plugin_name
        self.reason = reason
        self.cause = cause
        super().__init__(f"hot_swap({plugin_name!r}) failed: {reason}")


class HotSwapResult:
    """Результат hot-swap одного плагина (минимальный pure-data объект)."""

    __slots__ = ("plugin_name", "old_version", "new_version", "status", "reason")

    def __init__(
        self,
        *,
        plugin_name: str,
        old_version: str,
        new_version: str,
        status: str,
        reason: str | None = None,
    ) -> None:
        """Инициализирует результат hot-swap.

        Args:
            plugin_name: Имя плагина (из manifest).
            old_version: Версия до reload (``"?"`` если плагин был failed).
            new_version: Версия после reload (``"?"`` если reload не дошёл).
            status: ``"reloaded"`` | ``"failed"`` | ``"unchanged"``.
            reason: Описание ошибки или skip-причины (опционально).
        """
        self.plugin_name = plugin_name
        self.old_version = old_version
        self.new_version = new_version
        self.status = status
        self.reason = reason

    def to_dict(self) -> dict[str, Any]:
        """Сериализация для admin-endpoint / CLI output."""
        return {
            "plugin_name": self.plugin_name,
            "old_version": self.old_version,
            "new_version": self.new_version,
            "status": self.status,
            "reason": self.reason,
        }


class PluginLoaderProtocol(Protocol):
    """Минимальный контракт PluginLoader для hot_swap.

    Совместим с :class:`PluginLoaderV11` из ``services/plugins/loader_v11.py``,
    но описан как Protocol, чтобы избежать импорта infrastructure/services
    из ``core/``.
    """

    @property
    def loaded(self) -> tuple[Any, ...]:
        """Все известные плагины (loaded / failed / skipped)."""
        ...

    async def shutdown_all(self) -> None:
        """Graceful shutdown всех загруженных плагинов."""
        ...

    async def discover_and_load(self) -> tuple[Any, ...]:
        """Discovery + load всех плагинов в extensions/."""
        ...


def _find_loaded_entry(loader: PluginLoaderProtocol, plugin_name: str) -> Any | None:
    """Находит запись плагина в реестре loader по имени."""
    for entry in loader.loaded:
        if getattr(entry, "name", None) == plugin_name:
            return entry
    return None


def _reload_module(module_name: str) -> bool:
    """Принудительно перезагружает модуль через :func:`importlib.reload`.

    Args:
        module_name: Полное dotted-name модуля (``"extensions.foo.plugin"``).

    Returns:
        True, если модуль был в ``sys.modules`` и был reload-нут.
        False, если модуль ещё не был импортирован (reload не нужен).
    """
    if module_name in sys.modules:
        try:
            importlib.reload(sys.modules[module_name])
        except Exception as exc:  # noqa: BLE001 — логируем без падения вызывающего
            _logger.warning("Module %s reload failed: %s", module_name, exc)
            return False
        return True
    return False


async def hot_swap(
    plugin_name: str,
    loader: PluginLoaderProtocol,
    *,
    extensions_dir: Path | None = None,  # noqa: ARG001 — резерв под per-plugin reload через scan
) -> HotSwapResult:
    """Hot-swap (reload без рестарта) одного in-tree плагина.

    Алгоритм:

    1. Найти текущую запись плагина в ``loader.loaded`` по имени.
    2. Сохранить ``old_version`` и dotted-name модуля ``entry_class``.
    3. Выполнить graceful shutdown через ``loader.shutdown_all()``
       (текущая реализация PluginLoaderV11 не имеет per-plugin unload,
       поэтому здесь делается full shutdown + reload — это безопасно
       для in-tree dev-режима; production-вариант появится в S8).
    4. Reload модуля ``entry_class`` через :func:`importlib.reload`.
    5. Повторно выполнить ``discover_and_load()`` (loader перечитает
       все ``plugin.toml`` и заново применит capability-gate).
    6. Проверить, что плагин снова в реестре в статусе ``"loaded"``.

    Args:
        plugin_name: Имя плагина (как в ``plugin.toml::name``).
        loader: Экземпляр :class:`PluginLoaderV11` (или совместимый).
        extensions_dir: Каталог extensions/ — резерв под per-plugin reload
            (S8). В текущей версии не используется.

    Returns:
        :class:`HotSwapResult` с детализацией результата.

    Raises:
        HotSwapError: Если плагин не найден или reload-цепочка упала.

    Пример:
        >>> result = await hot_swap("example_plugin", loader)
        >>> assert result.status == "reloaded"
    """
    entry = _find_loaded_entry(loader, plugin_name)
    if entry is None:
        raise HotSwapError(plugin_name, "plugin not registered in loader")

    old_version = getattr(entry, "version", "?")

    # Запоминаем module dotted-name из entry_class, чтобы reload-нуть его явно.
    module_name: str | None = None
    instance = getattr(entry, "instance", None)
    if instance is not None:
        module_name = type(instance).__module__
    else:
        # Плагин не был успешно загружен — пробуем взять из manifest.
        manifest = getattr(entry, "manifest", None)
        entry_class: str | None = getattr(manifest, "entry_class", None)
        if entry_class:
            module_name = entry_class.rpartition(".")[0]

    # Graceful shutdown текущей версии (если есть что shutdown-ить).
    try:
        await loader.shutdown_all()
    except Exception as exc:  # noqa: BLE001
        _logger.exception("shutdown_all() during hot_swap raised")
        raise HotSwapError(plugin_name, "shutdown_all_failed", cause=exc) from exc

    # Reload Python-модуля, чтобы захватить изменения исходников.
    if module_name:
        _reload_module(module_name)

    # Полная переподпись плагинов (PluginLoaderV11.discover_and_load
    # идемпотентен в части owner-tracking, но capability-gate работает
    # на чистом старте — поэтому повторно регистрируем всё).
    # Resetting внутреннего реестра loader — деликатно: используем _loaded
    # через атрибут (контракт PluginLoaderV11).
    loaded_dict = getattr(loader, "_loaded", None)
    if isinstance(loaded_dict, dict):
        loaded_dict.clear()
    owners_dict = getattr(loader, "_owners", None)
    if isinstance(owners_dict, dict):
        for kind_map in owners_dict.values():
            if isinstance(kind_map, dict):
                kind_map.clear()

    try:
        await loader.discover_and_load()
    except Exception as exc:  # noqa: BLE001
        _logger.exception("discover_and_load() during hot_swap raised")
        raise HotSwapError(plugin_name, "discover_and_load_failed", cause=exc) from exc

    new_entry = _find_loaded_entry(loader, plugin_name)
    if new_entry is None:
        return HotSwapResult(
            plugin_name=plugin_name,
            old_version=old_version,
            new_version="?",
            status="failed",
            reason="plugin not rediscovered after reload",
        )

    new_version = getattr(new_entry, "version", "?")
    new_status = getattr(new_entry, "status", "unknown")

    if new_status != "loaded":
        return HotSwapResult(
            plugin_name=plugin_name,
            old_version=old_version,
            new_version=new_version,
            status="failed",
            reason=getattr(new_entry, "reason", None) or f"status={new_status}",
        )

    return HotSwapResult(
        plugin_name=plugin_name,
        old_version=old_version,
        new_version=new_version,
        status="reloaded",
    )
