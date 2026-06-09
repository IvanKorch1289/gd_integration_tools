"""Registry — кеш скомпилированных workflow-классов.

План V16.1 §4 Sprint 4 (К3): держим compile result между YAML
hot-reload'ами, чтобы `register_workflows_with_temporal` не
пересобирал worker'а при каждом изменении YAML без надобности.

Контракт:
    * :meth:`get_or_compile` — возвращает из кеша или компилирует
      и сохраняет.
    * :meth:`replace` — invalidates существующий кеш по имени и
      записывает новый (используется hot-reload).
    * :meth:`unregister` — удаляет из кеша.
    * :meth:`snapshot` / :meth:`restore` — atomic-операции для
      безопасного обновления коллекции workflow.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable

from src.backend.core.logging import get_logger
from src.backend.dsl.workflow.compiler.emitter import CompiledWorkflow, compile_workflow
from src.backend.dsl.workflow.spec import WorkflowDeclaration

__all__ = ("WorkflowCompilerRegistry",)


_logger = get_logger("workflow.compiler.registry")


class WorkflowCompilerRegistry:
    """Кеш компиляции workflow по имени.

    Thread-safe (RLock): hot-reload может обновлять реестр
    параллельно с активным worker, читающим коллекцию для
    регистрации.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: dict[str, CompiledWorkflow] = {}

    def get(self, name: str) -> CompiledWorkflow | None:
        """Вернуть кеш или ``None`` если не зарегистрирован."""
        with self._lock:
            return self._cache.get(name)

    def get_or_compile(self, decl: WorkflowDeclaration) -> CompiledWorkflow:
        """Compile (если ещё нет) и закешировать по ``decl.name``.

        Идемпотентно: повторный вызов с тем же ``decl.name`` вернёт
        кеш-значение без перекомпиляции.
        """
        with self._lock:
            cached = self._cache.get(decl.name)
            if cached is not None and cached.declaration == decl:
                return cached
            compiled = compile_workflow(decl)
            self._cache[compiled.name] = compiled
            return compiled

    def replace(self, decl: WorkflowDeclaration) -> CompiledWorkflow:
        """Принудительная перекомпиляция (hot-reload контракт).

        Args:
            decl: Новая декларация — ``decl.name`` определяет ключ кеша.

        Returns:
            Свежий :class:`CompiledWorkflow`.
        """
        with self._lock:
            compiled = compile_workflow(decl)
            self._cache[compiled.name] = compiled
            _logger.debug("workflow %s recompiled (hot-reload)", decl.name)
            return compiled

    def unregister(self, name: str) -> bool:
        """Удалить workflow из кеша.

        Returns:
            ``True`` если ключ был найден и удалён.
        """
        with self._lock:
            return self._cache.pop(name, None) is not None

    def list_compiled(self) -> tuple[CompiledWorkflow, ...]:
        """Вернуть кортеж всех скомпилированных workflow.

        Используется при регистрации Worker (одним пакетом).
        """
        with self._lock:
            return tuple(self._cache.values())

    def list_names(self) -> tuple[str, ...]:
        """Вернуть отсортированный список зарегистрированных имён."""
        with self._lock:
            return tuple(sorted(self._cache.keys()))

    def snapshot(self) -> dict[str, CompiledWorkflow]:
        """Поверхностная копия кеша (для atomic-rollback)."""
        with self._lock:
            return dict(self._cache)

    def restore(self, snapshot: dict[str, CompiledWorkflow]) -> None:
        """Заменить состояние снапшотом (atomic-rollback hot-reload)."""
        with self._lock:
            self._cache = dict(snapshot)

    def bulk_register(
        self, declarations: Iterable[WorkflowDeclaration]
    ) -> list[CompiledWorkflow]:
        """Скомпилировать и закешировать список деклараций.

        Args:
            declarations: Итератор деклараций.

        Returns:
            Список свежих :class:`CompiledWorkflow` (всегда
            пересобранные — каждое имя реплейсится).
        """
        with self._lock:
            result: list[CompiledWorkflow] = []
            for decl in declarations:
                compiled = compile_workflow(decl)
                self._cache[compiled.name] = compiled
                result.append(compiled)
            return result

    def clear(self) -> None:
        """Полная очистка реестра."""
        with self._lock:
            self._cache.clear()
