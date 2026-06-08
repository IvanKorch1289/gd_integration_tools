"""Lazy processor registry (Sprint 9 K3 W3).

Цель DoD-7: startup time <3s через отложенный import процессоров.
Базовый :class:`ProcessorRegistry` требует, чтобы класс был импортирован
в момент регистрации; лениво это делается через :class:`LazyProcessorRef`
и :class:`LazyProcessorRegistry`, который оборачивает базовый реестр и
импортирует модуль только при первом lookup.

Использование:

.. code-block:: python

    lazy = LazyProcessorRegistry(base=get_processor_registry())
    lazy.register_lazy(
        name="http_call",
        namespace="core",
        module_path="src.backend.dsl.engine.processors.http_call:HttpCallProcessor",
    )
    # ничего не импортировано ещё
    spec = lazy.resolve("core:http_call")  # → triggers import
"""

from __future__ import annotations

import importlib
import threading
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from src.backend.dsl.registry.errors import ProcessorNotFoundError
from src.backend.infrastructure.logging.factory import get_logger

__all__ = ("LazyProcessorRef", "LazyProcessorRegistry", "load_processor_class")

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class LazyProcessorRef:
    """Lazy reference на процессор (без import).

    Attributes:
        name: короткое имя ("http_call").
        namespace: namespace ("core" / plugin name).
        module_path: ``module.path:ClassName`` для importlib.
        capabilities: кортеж capability-литералов (для policy без import).
    """

    name: str
    namespace: str
    module_path: str
    capabilities: tuple[str, ...] = ()

    @property
    def fqn(self) -> str:
        return f"{self.namespace}:{self.name}"


@lru_cache(maxsize=512)
def load_processor_class(module_path: str) -> type:
    """Импортирует и возвращает класс по ``module:attr`` ссылке.

    Кэширует через :func:`functools.lru_cache` — второй вызов с той же
    строкой не делает re-import.

    Raises:
        ImportError: модуль не найден.
        AttributeError: атрибут отсутствует в модуле.
    """
    module_name, _, attr = module_path.partition(":")
    if not module_name or not attr:
        raise ImportError(f"module_path must be 'module:attr', got {module_path!r}")
    module = importlib.import_module(module_name)
    return getattr(module, attr)


class LazyProcessorRegistry:
    """Wraps :class:`ProcessorRegistry` с lazy module loading.

    Args:
        base: реальный :class:`ProcessorRegistry` (для backward-compat).
    """

    def __init__(self, *, base: Any) -> None:
        self._base = base
        self._lazy_refs: dict[str, LazyProcessorRef] = {}
        self._resolved: set[str] = set()
        self._lock = threading.Lock()

    def register_lazy(
        self,
        *,
        name: str,
        namespace: str,
        module_path: str,
        capabilities: tuple[str, ...] = (),
    ) -> LazyProcessorRef:
        """Сохранить lazy ref без import."""
        ref = LazyProcessorRef(
            name=name,
            namespace=namespace,
            module_path=module_path,
            capabilities=capabilities,
        )
        with self._lock:
            self._lazy_refs[ref.fqn] = ref
        return ref

    def list_lazy_refs(self) -> list[LazyProcessorRef]:
        """Список всех lazy-refs (для startup-time inventory)."""
        with self._lock:
            return list(self._lazy_refs.values())

    def list_unresolved(self) -> list[LazyProcessorRef]:
        """Lazy-refs, которые ещё не были загружены."""
        with self._lock:
            return [
                ref for fqn, ref in self._lazy_refs.items() if fqn not in self._resolved
            ]

    def capabilities_for(self, fqn: str) -> tuple[str, ...]:
        """Capabilities процессора без полного импорта (policy-gate)."""
        with self._lock:
            ref = self._lazy_refs.get(fqn)
            if ref is None:
                # Возможно уже зарегистрирован в base
                try:
                    spec = self._base.get(fqn)
                    return tuple(spec.capabilities)
                except ProcessorNotFoundError:
                    return ()
            return ref.capabilities

    def resolve(self, fqn: str) -> Any:
        """Полная резолюция: import + регистрация в base.

        Идемпотентно. Второй вызов возвращает уже зарегистрированный spec.

        Raises:
            ProcessorNotFoundError: нет ни в base, ни в lazy_refs.
        """
        # Сначала проверим, может быть уже в base
        try:
            spec = self._base.get(fqn)
        except ProcessorNotFoundError:
            spec = None

        if spec is not None:
            # Помечаем как resolved (если был lazy-ref для него)
            with self._lock:
                if fqn in self._lazy_refs:
                    self._resolved.add(fqn)
            return spec

        with self._lock:
            ref = self._lazy_refs.get(fqn)
        if ref is None:
            raise ProcessorNotFoundError(f"Lazy ref for {fqn!r} not registered")

        # Import → класс уже должен быть decorated @processor,
        # т.е. __init_subclass__ / module-import side-effect зарегистрирует
        # spec в base. Если это не так — это контракт нарушение.
        load_processor_class(ref.module_path)
        with self._lock:
            self._resolved.add(fqn)
        return self._base.get(fqn)

    def resolve_all(self) -> int:
        """Eager-resolve всех lazy-refs. Используется в pre-prod-check."""
        count = 0
        for ref in self.list_lazy_refs():
            try:
                self.resolve(ref.fqn)
                count += 1
            except Exception as _:
                logger.exception(
                    "lazy_processor.resolve_failed",
                    extra={"fqn": ref.fqn, "module_path": ref.module_path},
                )
        return count
