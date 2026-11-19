"""Реестр ресурсов расширений — инверсия зависимостей ``src/ → extensions``.

Зачем
-----
Ядро, DSL и entrypoints получали объекты расширений (схемы, сервисы,
модели) **прямым импортом** ``extensions.*``. Это нарушало правило слоёв
(`tools/check_layers.py`: entrypoints/dsl/services → extensions не разрешены)
и делало ядро зависимым от конкретных расширений.

ADR-0457 переворачивает зависимость: расширение **отдаёт** свои ресурсы
в реестр, а потребитель **забирает** их из реестра по ключу
``(domain, kind, name)``. Реестр живёт в core → core ни от кого не зависит.

Загрузка
--------
Расширения подключаются **динамическим** импортом
(:func:`load_extension_resources`): модуль ``extensions/<name>/resources.py``
импортируется и вызывает свою функцию ``register()``. Статической зависимости
``src/ → extensions`` при этом не возникает — ровно так же, как работает
PluginLoader (``services/plugins/loader``).

Потребитель может запросить ресурс до того, как расширения загружены:
:func:`get_extension_resource` при промахе сам инициирует загрузку.

Пример
------
В расширении::

    from src.backend.core.extension_registry import register_extension_resource

    def register() -> None:
        register_extension_resource("orders", "schema", "schema_in", OrderSchemaIn)
        register_extension_resource("orders", "service", "orders", get_order_service)

В потребителе::

    from src.backend.core.extension_registry import get_extension_resource

    OrderSchemaIn = get_extension_resource("orders", "schema", "schema_in")
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import pkgutil
import threading
from dataclasses import dataclass
from typing import Any

__all__ = (
    "ExtensionResource",
    "ExtensionResourceRegistry",
    "get_extension_resource",
    "get_extension_load_errors",
    "get_extension_registry",
    "load_extension_resources",
    "register_extension_resource",
    "reset_extension_resources",
)

logger = logging.getLogger("src.backend.core.extension_registry")

#: Имя корневого пакета расширений (динамический импорт, без статической связи).
_EXTENSIONS_PACKAGE = "extensions"

#: Имя модуля внутри расширения, который регистрирует ресурсы.
_RESOURCES_MODULE = "resources"

#: Максимальная глубина обхода пакетов расширений (extensions → core_entities → orders).
_MAX_DISCOVERY_DEPTH = 3

#: Таймаут ожидания чужого потока, который уже грузит расширения.
#: Страховка от «вечной» блокировки (зависший импорт расширения) — после
#: таймаута ожидающий поток продолжает работу и получает обычный KeyError.
_LOAD_WAIT_TIMEOUT: float = 60.0

#: Sentinel «ресурс не зарегистрирован» — отличает отсутствие ресурса от
#: ресурса, зарегистрированного со значением ``None``.
_MISSING: Any = object()


@dataclass(frozen=True, slots=True)
class ExtensionResource:
    """Ресурс, предоставленный расширением.

    Attributes:
        domain: Домен ресурса (``"orders"``, ``"users"``, ``"skb"`` …).
        kind: Тип ресурса (``"schema"``, ``"service"``, ``"model"``).
        name: Имя ресурса внутри домена и типа.
        obj: Объект (схема, callable-геттер сервиса, ORM-модель …).

    """

    domain: str
    kind: str
    name: str
    obj: Any

    @property
    def key(self) -> tuple[str, str, str]:
        """Ключ ресурса в реестре."""
        return (self.domain, self.kind, self.name)


class ExtensionResourceRegistry:
    """Потокобезопасный реестр ресурсов расширений.

    Ключ ресурса — тройка ``(domain, kind, name)``. Повторная регистрация
    того же ключа перезаписывает значение (расширение может перерегистрировать
    ресурс при hot-reload) и пишет warning-лог.
    """

    def __init__(self) -> None:
        """Создаёт пустой реестр."""
        self._resources: dict[tuple[str, str, str], Any] = {}
        self._lock = threading.RLock()

    def register(self, resource: ExtensionResource) -> None:
        """Регистрирует ресурс расширения.

        Args:
            resource: Ресурс для регистрации.

        """
        with self._lock:
            previous = self._resources.get(resource.key, _MISSING)
            self._resources[resource.key] = resource.obj
        if previous is not _MISSING and previous is not resource.obj:
            logger.warning(
                "extension_resource.replaced: domain=%s kind=%s name=%s",
                resource.domain,
                resource.kind,
                resource.name,
            )

    def find(self, domain: str, kind: str, name: str) -> Any | None:
        """Возвращает ресурс или ``None``, если его нет.

        Args:
            domain: Домен ресурса.
            kind: Тип ресурса.
            name: Имя ресурса.

        Returns:
            Зарегистрированный объект либо ``None``.

        """
        with self._lock:
            return self._resources.get((domain, kind, name))

    def get(self, domain: str, kind: str, name: str) -> Any:
        """Возвращает ресурс; при отсутствии — ``KeyError``.

        Args:
            domain: Домен ресурса.
            kind: Тип ресурса.
            name: Имя ресурса.

        Returns:
            Зарегистрированный объект.

        Raises:
            KeyError: Ресурс не зарегистрирован.

        """
        with self._lock:
            found = self._resources.get((domain, kind, name), _MISSING)
        if found is _MISSING:
            raise KeyError(
                f"Ресурс расширения не зарегистрирован: domain={domain!r} "
                f"kind={kind!r} name={name!r}. Проверь, что расширение "
                f"экспортирует модуль '{_RESOURCES_MODULE}' с функцией register()."
            )
        return found

    def domains(self) -> tuple[str, ...]:
        """Возвращает отсортированный список доменов с ресурсами."""
        with self._lock:
            return tuple(sorted({key[0] for key in self._resources}))

    def clear(self) -> None:
        """Очищает реестр (используется в тестах и при hot-reload)."""
        with self._lock:
            self._resources.clear()


_registry = ExtensionResourceRegistry()
_load_lock = threading.RLock()
_loaded = False
_loading = False
#: ident потока, который сейчас грузит расширения (для re-entrance и reset).
_loader_ident: int | None = None
#: Событие завершения текущей загрузки (создаётся на каждую загрузку).
_load_done = threading.Event()
_load_done.set()
#: Ошибки загрузки расширений: ``модуль → описание``. Нужны, чтобы
#: потребитель получал не «KeyError без причины», а текст с реальной
#: причиной (сломанный импорт расширения / отсутствие ``register()``).
_load_errors: dict[str, str] = {}


def get_extension_registry() -> ExtensionResourceRegistry:
    """Возвращает process-wide реестр ресурсов расширений."""
    return _registry


def register_extension_resource(domain: str, kind: str, name: str, obj: Any) -> None:
    """Регистрирует ресурс расширения в process-wide реестре.

    Args:
        domain: Домен ресурса.
        kind: Тип ресурса (``"schema"`` / ``"service"`` / ``"model"``).
        name: Имя ресурса внутри домена.
        obj: Объект ресурса.

    """
    _registry.register(ExtensionResource(domain=domain, kind=kind, name=name, obj=obj))


def load_extension_resources(*, force: bool = False) -> None:
    """Загружает ресурсы расширений (динамический импорт ``extensions/*/resources.py``).

    Функция идемпотентна: повторный вызов без ``force`` ничего не делает.
    Расширение, которое не импортируется (например, из-за отсутствующих
    optional-зависимостей), **пропускается** с warning-логом — падать нельзя,
    иначе одно сломанное расширение блокирует старт приложения. Причина
    пропуска сохраняется (см. :func:`_load_error_summary`) и попадает в
    ``KeyError`` потребителя — «тихой» деградации нет.

    Обход рекурсивный: группа расширений (``extensions/core_entities/``)
    не содержит своего ``resources.py`` — он лежит в под-пакетах
    (``extensions/core_entities/orders/resources.py``).

    Потокобезопасность: если расширения уже грузит другой поток, вызов
    **ждёт** завершения загрузки (иначе потребитель получил бы ``KeyError``
    на полузагруженном реестре — гонка первых запросов после старта).
    Повторный вход из того же потока (реентерабельность из ``register()``
    расширения) — немедленный выход.

    Args:
        force: Перезагрузить ресурсы даже если они уже загружены.

    """
    global _loaded, _loading, _loader_ident, _load_done
    done = threading.Event()
    with _load_lock:
        if _loaded and not force:
            return
        if _loading:
            if _loader_ident == threading.get_ident():
                # Повторный вход из ресурса расширения — реентерабельность.
                return
            # Загрузку ведёт другой поток — дождаться её завершения.
            waiter = _load_done
        else:
            _loading = True
            _loader_ident = threading.get_ident()
            _load_done = done
            _load_errors.clear()
            waiter = None
    if waiter is not None:
        if not waiter.wait(timeout=_LOAD_WAIT_TIMEOUT):
            logger.warning(
                "extension_resources: ожидание загрузки расширений истекло "
                "(timeout=%.0fs)",
                _LOAD_WAIT_TIMEOUT,
            )
        return
    try:
        _discover_package(_EXTENSIONS_PACKAGE, depth=0)
    finally:
        with _load_lock:
            _loading = False
            _loader_ident = None
            _loaded = True
            done.set()


def get_extension_load_errors() -> dict[str, str]:
    """Ошибки загрузки расширений (публичный доступ для startup-фазы).

    Returns:
        Соответствие ``имя модуля → причина``. Пусто, если все расширения
        загрузились (или загрузка ещё не выполнялась).

    """
    with _load_lock:
        return dict(_load_errors)


def _load_error_summary() -> str:
    """Сводка ошибок загрузки расширений (диагностика для потребителя).

    Returns:
        Строка с ошибками загрузки или ``"ошибок загрузки не зафиксировано"``.

    """
    with _load_lock:
        errors = dict(_load_errors)
    if not errors:
        return "ошибок загрузки не зафиксировано"
    return "; ".join(f"{module}: {reason}" for module, reason in sorted(errors.items()))


def _discover_package(package_name: str, *, depth: int) -> None:
    """Ищет ``<package>/resources.py`` в пакете и его под-пакетах.

    Args:
        package_name: Dotted-имя пакета (``"extensions"``).
        depth: Текущая глубина обхода (ограничена :data:`_MAX_DISCOVERY_DEPTH`).

    """
    if depth > _MAX_DISCOVERY_DEPTH:
        return
    try:
        spec = importlib.util.find_spec(package_name)
    except ImportError, ValueError:
        return
    if spec is None or not spec.submodule_search_locations:
        return
    for module_info in pkgutil.iter_modules(list(spec.submodule_search_locations)):
        if not module_info.ispkg:
            continue
        _load_extension(f"{package_name}.{module_info.name}", depth=depth)


def _load_extension(package_name: str, *, depth: int) -> None:
    """Импортирует ``<package_name>/resources.py`` и регистрирует ресурсы.

    Args:
        package_name: Dotted-имя пакета расширения.
        depth: Текущая глубина обхода.

    """
    module_name = f"{package_name}.{_RESOURCES_MODULE}"
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name == module_name:
            # У пакета нет своего ``resources.py`` — ищем глубже.
            _discover_package(package_name, depth=depth + 1)
            return
        reason = f"{type(exc).__name__}: {exc}"
        _record_load_error(module_name, reason)
        logger.warning(
            "extension_resources: пропущено расширение %s (%s)", package_name, reason
        )
        return
    except Exception as exc:  # noqa: BLE001 — расширение не должно ронять старт
        reason = f"{type(exc).__name__}: {exc}"
        _record_load_error(module_name, reason)
        logger.warning(
            "extension_resources: пропущено расширение %s (%s)", package_name, reason
        )
        return
    register = getattr(module, "register", None)
    if register is None:
        _record_load_error(module_name, "нет функции register()")
        logger.warning(
            "extension_resources: у расширения %s нет функции register()", package_name
        )
        return
    try:
        register()
    except Exception as exc:  # noqa: BLE001 — ошибка регистрации не должна ронять старт
        reason = f"{type(exc).__name__}: {exc}"
        _record_load_error(module_name, reason)
        logger.warning(
            "extension_resources: расширение %s не зарегистрировало ресурсы (%s)",
            package_name,
            reason,
        )


def _record_load_error(module_name: str, reason: str) -> None:
    """Сохраняет причину пропуска расширения (диагностика для потребителя).

    Args:
        module_name: Dotted-имя модуля расширения.
        reason: Описание причины.

    """
    with _load_lock:
        _load_errors[module_name] = reason


def get_extension_resource(domain: str, kind: str, name: str) -> Any:
    """Возвращает ресурс расширения, при необходимости загрузив расширения.

    Args:
        domain: Домен ресурса (``"orders"`` …).
        kind: Тип ресурса (``"schema"`` / ``"service"`` / ``"model"``).
        name: Имя ресурса.

    Returns:
        Зарегистрированный объект.

    Raises:
        KeyError: Ресурс не найден даже после загрузки расширений. В текст
            включена сводка ошибок загрузки расширений — иначе потребитель
            получил бы «KeyError» без указания реальной причины (сломанный
            импорт расширения / отсутствие ``register()``).

    """
    found = _registry.find(domain, kind, name)
    if found is not None:
        return found
    load_extension_resources()
    try:
        return _registry.get(domain, kind, name)
    except KeyError as exc:
        message = exc.args[0] if exc.args else str(exc)
        raise KeyError(
            f"{message} Ошибки загрузки расширений: {_load_error_summary()}."
        ) from exc


def reset_extension_resources() -> None:
    """Очищает реестр и сбрасывает флаг загрузки расширений.

    Используется в тестах (изоляция process-wide состояния) и при
    hot-reload расширений: следующий :func:`get_extension_resource`
    перезагрузит расширения заново.

    Если в момент сброса расширения грузит другой поток — сброс дожидается
    завершения загрузки, иначе она дописала бы ресурсы уже «после» сброса
    (состояние реестра утекло бы в следующий тест).
    """
    global _loaded
    with _load_lock:
        if _loading and _loader_ident != threading.get_ident():
            waiter = _load_done
        else:
            waiter = None
    if waiter is not None:
        waiter.wait(timeout=_LOAD_WAIT_TIMEOUT)
    with _load_lock:
        _loaded = False
        _load_errors.clear()
    _registry.clear()
