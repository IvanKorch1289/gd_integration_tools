"""W23 — Реестр Source/Sink (Gateway).

``SourceRegistry`` хранит зарегистрированные source-инстансы по
``source_id``. Композиционный корень собирает их по YAML-spec
(:func:`services.sources.factory.build_source`) и складывает в
``app.state.source_registry``.

Сам Registry не запускает бэкенды — этим занимается
``SourceToInvokerAdapter`` (см. :mod:`services.sources.adapter`),
который для каждого зарегистрированного source поднимает
``Source.start(adapter.handle)`` в lifecycle hook'е.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.core.di import app_state_singleton
from src.core.interfaces.sink import Sink
from src.core.interfaces.source import Source

if TYPE_CHECKING:
    pass

__all__ = ("SourceRegistry", "SinkRegistry", "get_source_registry", "get_sink_registry")

logger = logging.getLogger("services.sources.registry")


class SourceRegistry:
    """Реестр зарегистрированных :class:`Source`-инстансов.

    Регистрация идёт по ``source_id`` (унікальный в пределах процесса).
    Дубль-регистрация — ``ValueError``.
    """

    def __init__(self) -> None:
        self._sources: dict[str, Source] = {}

    def register(self, source: Source) -> None:
        """Зарегистрировать source. ``ValueError`` при дубле id."""
        if source.source_id in self._sources:
            raise ValueError(f"Source с id={source.source_id!r} уже зарегистрирован")
        self._sources[source.source_id] = source
        logger.info(
            "SourceRegistry: registered %s (kind=%s)",
            source.source_id,
            source.kind.value,
        )

    def get(self, source_id: str) -> Source:
        """Получить source по id; ``KeyError`` при отсутствии."""
        if source_id not in self._sources:
            raise KeyError(f"Source с id={source_id!r} не зарегистрирован")
        return self._sources[source_id]

    def all(self) -> tuple[Source, ...]:
        """Все зарегистрированные source — упорядочены по id."""
        return tuple(self._sources[k] for k in sorted(self._sources))

    def __len__(self) -> int:
        return len(self._sources)

    def __contains__(self, source_id: object) -> bool:
        return isinstance(source_id, str) and source_id in self._sources


class SinkRegistry:
    """Реестр зарегистрированных :class:`Sink`-инстансов.

    Симметричен ``SourceRegistry``: lookup по ``sink_id``, дубль = ``ValueError``.
    """

    def __init__(self) -> None:
        self._sinks: dict[str, Sink] = {}

    def register(self, sink: Sink) -> None:
        """Зарегистрировать sink. ``ValueError`` при дубле id."""
        if sink.sink_id in self._sinks:
            raise ValueError(f"Sink с id={sink.sink_id!r} уже зарегистрирован")
        self._sinks[sink.sink_id] = sink
        logger.info(
            "SinkRegistry: registered %s (kind=%s)", sink.sink_id, sink.kind.value
        )

    def get(self, sink_id: str) -> Sink:
        if sink_id not in self._sinks:
            raise KeyError(f"Sink с id={sink_id!r} не зарегистрирован")
        return self._sinks[sink_id]

    def all(self) -> tuple[Sink, ...]:
        return tuple(self._sinks[k] for k in sorted(self._sinks))

    def __len__(self) -> int:
        return len(self._sinks)

    def __contains__(self, sink_id: object) -> bool:
        return isinstance(sink_id, str) and sink_id in self._sinks


# ─────────── DI accessors (composition root заполняет app.state.*) ───────────


@app_state_singleton("source_registry", factory=SourceRegistry)
def get_source_registry() -> SourceRegistry:
    """Singleton-аксессор :class:`SourceRegistry`.

    Lazy-инициализация пустым реестром в non-FastAPI контекстах
    (тесты, скрипты). В FastAPI заполняется в ``register_app_state``.
    """
    raise RuntimeError("unreachable — фабрика создаёт пустой реестр")


@app_state_singleton("sink_registry", factory=SinkRegistry)
def get_sink_registry() -> SinkRegistry:
    """Singleton-аксессор :class:`SinkRegistry` (см. :func:`get_source_registry`)."""
    raise RuntimeError("unreachable — фабрика создаёт пустой реестр")
