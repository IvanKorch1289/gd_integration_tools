from dataclasses import dataclass, field

from app.dsl.engine.processors import BaseProcessor

__all__ = ("Pipeline",)


@dataclass(slots=True)
class Pipeline:
    """
    Описание DSL-маршрута.

    Attributes:
        route_id: Уникальный идентификатор маршрута.
        source: Источник маршрута (например, http:tech.send_email).
        description: Человекочитаемое описание.
        processors: Последовательность шагов обработки.
    """

    route_id: str
    source: str | None = None
    description: str | None = None
    processors: list[BaseProcessor] = field(default_factory=list)

    def add_processor(self, processor: BaseProcessor) -> "Pipeline":
        """
        Добавляет процессор в конец маршрута.

        Args:
            processor: Экземпляр процессора.

        Returns:
            Pipeline: Текущий маршрут для fluent-chain.
        """
        self.processors.append(processor)
        return self

    def extend(self, processors: list[BaseProcessor]) -> "Pipeline":
        """
        Добавляет несколько процессоров.

        Args:
            processors: Список процессоров.

        Returns:
            Pipeline: Текущий маршрут для fluent-chain.
        """
        self.processors.extend(processors)
        return self
