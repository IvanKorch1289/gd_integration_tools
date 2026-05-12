"""Formal API реестра процессоров DSL (Stage 3, V15 Sprint 1).

Декоратор :func:`processor` регистрирует тип ``BaseProcessor`` в
:class:`ProcessorRegistry` с namespacing (``core:`` / ``<plugin>:``),
JSON-Schema метаданными и capability-gate.

Использование (ядро)::

    from src.backend.dsl.registry.processor import processor

    @processor(
        "http_call",
        spec_schema={"type": "object", "properties": {...}},
        output_schema={"type": "object"},
        namespace="core",
    )
    class HttpCallProcessor(BaseProcessor):
        ...

Использование (плагин)::

    @processor(
        "kyc_verify",
        namespace="banking_plugin",
        capabilities=("net.outbound.compliance.api:external",),
    )
    class KycVerifyProcessor(BaseProcessor):
        ...

Override встроенного процессора (требуется capability ``processor.override.<name>``
в plugin.toml)::

    @processor("http_call", namespace="banking_plugin", replaces="core:http_call")
    class CustomHttpCallProcessor(BaseProcessor):
        ...

См. план: ``/home/user/.claude/plans/replicated-seeking-panda.md``
(раздел A5/Stage 3).
"""

from __future__ import annotations

import threading
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from src.backend.dsl.registry.errors import (
    ProcessorConflictError,
    ProcessorNotFoundError,
)

if TYPE_CHECKING:
    from src.backend.dsl.engine.processors.base import BaseProcessor


__all__ = (
    "ProcessorRegistry",
    "ProcessorSpec",
    "get_processor_registry",
    "processor",
)


@dataclass(frozen=True, slots=True)
class ProcessorSpec:
    """Запись о зарегистрированном процессоре.

    Атрибуты:
        name: Короткое имя (``http_call``, ``dispatch_action`` и т.п.).
        namespace: ``core`` для ядра, имя плагина для extensions.
        cls: Класс процессора (``type[BaseProcessor]``).
        spec_schema: JSON-Schema для входной спецификации (params в YAML/builder).
        output_schema: JSON-Schema для выхода (для validate_response/contract-review).
        capabilities: Tuple capability-литералов, требуемых процессором.
        replaces: Полное имя ``namespace:name`` процессора, который замещается.
        meta: Произвольные метаданные (теги, deprecated_since, ...).
    """

    name: str
    namespace: str
    cls: type[BaseProcessor]
    spec_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    capabilities: tuple[str, ...] = field(default_factory=tuple)
    replaces: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def fqn(self) -> str:
        """Полное имя ``namespace:name`` (для ключа реестра)."""

        return f"{self.namespace}:{self.name}"


class ProcessorRegistry:
    """Thread-safe реестр процессоров с namespacing и conflict-resolution.

    Контракт:
        * Один ``namespace:name`` ⇒ один процессор. Повторная регистрация
          без ``replaces=`` → :class:`ProcessorConflictError`.
        * ``replaces="core:http_call"`` явно замещает существующую запись
          (требуется capability ``processor.override.<name>`` в plugin.toml,
          проверка делается при загрузке плагина, не здесь).
        * ``get_by_short(name)`` — поиск по короткому имени; если коллизия
          между ``core:name`` и ``<plugin>:name``, override-цепочка
          ведёт к актуальному.
    """

    def __init__(self) -> None:
        self._by_fqn: dict[str, ProcessorSpec] = {}
        self._lock = threading.RLock()

    def register(self, spec: ProcessorSpec) -> ProcessorSpec:
        """Регистрирует процессор.

        Returns:
            Сохранённая спецификация (та же, что в аргументе).

        Raises:
            ProcessorConflictError: ``namespace:name`` уже занят и
                ``replaces=None``.
            ProcessorNotFoundError: ``replaces=...`` указан, но указанная
                запись не зарегистрирована.
        """

        with self._lock:
            if spec.fqn in self._by_fqn and spec.replaces != spec.fqn:
                raise ProcessorConflictError(
                    f"Processor {spec.fqn!r} already registered. "
                    f"Pass replaces={spec.fqn!r} to override explicitly."
                )

            if spec.replaces is not None and spec.replaces not in self._by_fqn:
                raise ProcessorNotFoundError(
                    f"replaces={spec.replaces!r} but no such processor registered."
                )

            self._by_fqn[spec.fqn] = spec
            return spec

    def unregister(self, fqn: str) -> None:
        """Удаляет процессор по полному имени (для тестов/hot-reload)."""

        with self._lock:
            self._by_fqn.pop(fqn, None)

    def get(self, fqn: str) -> ProcessorSpec:
        """Возвращает спецификацию по ``namespace:name``."""

        with self._lock:
            spec = self._by_fqn.get(fqn)
            if spec is None:
                raise ProcessorNotFoundError(f"Processor {fqn!r} not registered.")
            return spec

    def get_by_short(self, name: str, *, prefer_namespace: str = "core") -> ProcessorSpec:
        """Поиск по короткому имени.

        Если процессор зарегистрирован в нескольких namespace'ах, возвращает
        ``prefer_namespace`` (по умолчанию ``core``). Если в ``prefer_namespace``
        нет — возвращает первый найденный (отсортированный для детерминизма).
        """

        with self._lock:
            preferred_fqn = f"{prefer_namespace}:{name}"
            if preferred_fqn in self._by_fqn:
                return self._by_fqn[preferred_fqn]

            candidates = sorted(
                spec for fqn, spec in self._by_fqn.items() if spec.name == name
            )
            if not candidates:
                raise ProcessorNotFoundError(
                    f"Processor with short name {name!r} not registered."
                )
            return candidates[0]

    def list_specs(self) -> list[ProcessorSpec]:
        """Возвращает копию списка всех зарегистрированных спецификаций."""

        with self._lock:
            return list(self._by_fqn.values())

    def list_by_namespace(self, namespace: str) -> list[ProcessorSpec]:
        """Возвращает все процессоры из конкретного namespace."""

        with self._lock:
            return [s for s in self._by_fqn.values() if s.namespace == namespace]

    def __contains__(self, fqn: str) -> bool:
        with self._lock:
            return fqn in self._by_fqn

    def __iter__(self) -> Iterator[ProcessorSpec]:
        with self._lock:
            return iter(list(self._by_fqn.values()))

    def __len__(self) -> int:
        with self._lock:
            return len(self._by_fqn)


# Module-level singleton — заполняется через @processor декоратор на этапе import.
_REGISTRY: ProcessorRegistry = ProcessorRegistry()


def get_processor_registry() -> ProcessorRegistry:
    """Возвращает global-singleton :class:`ProcessorRegistry`."""

    return _REGISTRY


def processor(
    name: str,
    *,
    namespace: str = "core",
    spec_schema: dict[str, Any] | None = None,
    output_schema: dict[str, Any] | None = None,
    capabilities: Iterable[str] = (),
    replaces: str | None = None,
    meta: dict[str, Any] | None = None,
) -> Any:
    """Декоратор регистрирует ``BaseProcessor``-класс в реестре процессоров.

    Args:
        name: Короткое имя процессора (используется в YAML/builder).
        namespace: ``core`` для ядра, имя плагина для extensions.
        spec_schema: JSON-Schema входной спецификации (опционально).
        output_schema: JSON-Schema выхода (опционально).
        capabilities: Кортеж capability-литералов, требуемых процессором.
        replaces: Полное имя замещаемого процессора (``core:http_call``).
            Использование в плагине требует capability
            ``processor.override.<name>`` в plugin.toml — проверка
            делается на уровне PluginLoader, не здесь.
        meta: Произвольные метаданные.

    Returns:
        Декоратор класса.

    Example:
        >>> @processor("log", spec_schema={"type": "object"})
        ... class LogProcessor(BaseProcessor): ...
    """

    def decorator(cls: type[BaseProcessor]) -> type[BaseProcessor]:
        spec = ProcessorSpec(
            name=name,
            namespace=namespace,
            cls=cls,
            spec_schema=spec_schema,
            output_schema=output_schema,
            capabilities=tuple(capabilities),
            replaces=replaces,
            meta=dict(meta) if meta else {},
        )
        _REGISTRY.register(spec)
        cls.__processor_spec__ = spec  # type: ignore[attr-defined]
        return cls

    return decorator
