"""`WorkflowRegistry` — singleton реестр Temporal workflow-классов (cycle 33).

Bridge между Protocol-сигнатурой
:meth:`WorkflowBackend.replay(workflow_name: str, history: bytes)` и SDK-реальностью
(temporalio :class:`Replayer` ожидает ``Sequence[type]`` workflow-классов,
задекорированных ``@workflow.defn``).

Без этого реестра ``replay()`` приходилось делать narrow cast ``str → type``
и надеяться, что temporalio SDK терпимо отнесётся к невалидному входу — что
является протокольным расхождением (см. ``temporal_backend.replay`` B-10).

Сейчас (Sprint 171, B-10) в кодовой базе ещё нет классов, помеченных
``@workflow.defn`` напрямую (только docstring-упоминания и ссылки в
emitter.py / versioning.py). Реестр готов принимать их по мере появления;
bootstrap-сканер в :mod:`app_factory` ищет их на старте.

Валидация: класс должен иметь marker temporalio SDK
``__temporal_workflow_definition__`` (проставляется декоратором
``@workflow.defn``) либо fallback-флаг ``_is_workflow=True`` для
test-fixtures (плагины и unit-тесты).
"""

from __future__ import annotations

import threading
from typing import Any

__all__ = ("WorkflowRegistry", "workflow_registry")


# Marker attribute that temporalio.workflow.defn decorator sets on the class.
# Reference: temporalio.workflow._defn — wraps the class with a
# _WorkflowDefinition bound under this name.
_TEMPORAL_DEFN_MARKER = "__temporal_workflow_definition__"

# Private fallback sentinel for unit-tests / synthetic fixtures that
# cannot easily invoke the real temporalio decorator without a running
# event loop (decorator side-effects are global).
_FALLBACK_MARKER = "_is_workflow"


class WorkflowRegistry:
    """Thread-safe singleton реестр Temporal workflow-классов.

    Хранит :class:`type` под именем workflow'а (``@workflow.defn(name=...)``
    либо ``cls.__name__``). Используется
    :meth:`TemporalWorkflowBackend.replay` для маппинга Protocol-строки
    ``workflow_name`` в список классов, которые :class:`Replayer` принимает.
    """

    def __init__(self) -> None:
        self._classes: dict[str, type] = {}
        self._lock = threading.Lock()  # noqa: violation-check — sync register/get/all/names/clear/__contains__

    def register(self, cls: type) -> type:
        """Регистрирует workflow-класс.

        Args:
            cls: Класс, задекорированный ``@workflow.defn`` (или
                помеченный ``_is_workflow=True`` для тестов).

        Returns:
            Тот же ``cls`` (позволяет использовать registry как декоратор).

        Raises:
            TypeError: Если класс не помечен как Temporal workflow.
            ValueError: Если workflow с таким именем уже зарегистрирован.

        """
        if not self._is_workflow_class(cls):
            raise TypeError(
                f"{cls!r} не помечен @workflow.defn — WorkflowRegistry принимает "
                "только классы, задекорированные @workflow.defn "
                "(или явно помеченные атрибутом _is_workflow=True для тестов)"
            )

        name = self._extract_name(cls)
        with self._lock:
            if name in self._classes:
                raise ValueError(
                    f"Workflow '{name}' уже зарегистрирован "
                    f"(prev={self._classes[name]!r}, new={cls!r})"
                )
            self._classes[name] = cls
        return cls

    def get(self, name: str) -> type | None:
        """Возвращает workflow-класс по имени или ``None``."""
        return self._classes.get(name)

    def all(self) -> list[type]:
        """Возвращает копию списка всех зарегистрированных классов.

        Порядок — детерминированный (по имени) для стабильного вывода в
        логах и предсказуемого поведения ``Replayer``.
        """
        with self._lock:
            return [self._classes[name] for name in sorted(self._classes)]

    def names(self) -> list[str]:
        """Возвращает отсортированный список зарегистрированных workflow-имён."""
        with self._lock:
            return sorted(self._classes.keys())

    def clear(self) -> None:
        """Очищает реестр (используется в тестах и при hot-reload)."""
        with self._lock:
            self._classes.clear()

    @staticmethod
    def _is_workflow_class(cls: Any) -> bool:
        """``True`` если класс помечен temporalio ``@workflow.defn`` или
        явным fallback-флагом ``_is_workflow``.
        """
        if not isinstance(cls, type):
            return False
        if hasattr(cls, _TEMPORAL_DEFN_MARKER):
            return True
        return bool(getattr(cls, _FALLBACK_MARKER, False))

    @staticmethod
    def _extract_name(cls: type) -> str:
        """Имя workflow'а: ``__temporal_workflow_definition__.name`` если
        temporalio decorator проставил ``name=...``, иначе ``cls.__name__``.
        """
        defn = getattr(cls, _TEMPORAL_DEFN_MARKER, None)
        name = getattr(defn, "name", None) if defn is not None else None
        return name or cls.__name__

    def __contains__(self, name: str) -> bool:
        return name in self._classes

    def __len__(self) -> int:
        return len(self._classes)


# Глобальный singleton — импортируется из app_factory (bootstrap),
# temporal_backend.replay (lookup), unit-тестов.
workflow_registry = WorkflowRegistry()
