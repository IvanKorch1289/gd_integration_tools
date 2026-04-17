from dataclasses import dataclass, field

from app.dsl.adapters.types import ProtocolType, TransportConfig
from app.dsl.engine.processors import BaseProcessor

__all__ = ("Pipeline",)


@dataclass(slots=True)
class Pipeline:
    """Описание DSL-маршрута.

    Attrs:
        route_id: Уникальный идентификатор маршрута.
        source: Источник маршрута (например,
            ``internal:tech.send_email``).
        description: Человекочитаемое описание.
        processors: Последовательность шагов обработки.
        protocol: Протокол, через который обслуживается
            маршрут. ``None`` — протоколо-агностичный.
        transport_config: Конфигурация транспорта
            (endpoint, timeout, retry и т.д.).
        feature_flag: Имя feature-флага, защищающего маршрут.
            Если флаг присутствует в ``disabled_feature_flags``
            (runtime_state), маршрут недоступен для выполнения.
            ``None`` — маршрут всегда доступен.
    """

    route_id: str
    source: str | None = None
    description: str | None = None
    processors: list[BaseProcessor] = field(default_factory=list)
    protocol: ProtocolType | None = None
    transport_config: TransportConfig | None = None
    feature_flag: str | None = None

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
