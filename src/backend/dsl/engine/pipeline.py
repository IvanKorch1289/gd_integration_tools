from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.backend.dsl.adapters.types import ProtocolType, TransportConfig
from src.backend.dsl.engine.processors.base import BaseProcessor

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

    def to_dict(self) -> dict[str, Any]:
        """Сериализует Pipeline в словарь совместимый с YAML-лоадером.

        Процессоры без реализации ``to_spec()`` пропускаются. Поле
        ``apiVersion`` всегда выставляется равным ``CURRENT_VERSION`` —
        новая запись на диск или БД считается актуальной.

        Returns:
            Словарь с ключами apiVersion, route_id, source, description,
            processors.
        """
        from src.backend.dsl.versioning import CURRENT_VERSION

        result: dict[str, Any] = {
            "apiVersion": CURRENT_VERSION,
            "route_id": self.route_id,
        }
        if self.source:
            result["source"] = self.source
        if self.description:
            result["description"] = self.description
        if self.feature_flag:
            result["feature_flag"] = self.feature_flag

        specs = []
        for proc in self.processors:
            spec = proc.to_spec()
            if spec is not None:
                specs.append(spec)
        if specs:
            result["processors"] = specs

        return result

    def to_yaml(self) -> str:
        """Сериализует Pipeline в YAML-строку.

        Returns:
            YAML-строка пригодная для передачи в ``load_pipeline_from_yaml()``.

        Raises:
            ImportError: Если PyYAML не установлен.
        """
        try:
            import yaml
        except ImportError as exc:
            raise ImportError("PyYAML required: pip install pyyaml") from exc
        return yaml.dump(self.to_dict(), allow_unicode=True, sort_keys=False)

    def to_python(self) -> str:
        """Генерирует Python-код для воссоздания Pipeline через RouteBuilder.

        Returns:
            Строка Python-кода.
        """
        lines = [
            "from src.backend.dsl.builder import RouteBuilder",
            "",
            "pipeline = (",
            f"    RouteBuilder.from_({self.route_id!r}, source={self.source!r}",
        ]
        if self.description:
            lines[-1] += f", description={self.description!r}"
        lines[-1] += ")"

        for proc in self.processors:
            spec = proc.to_spec()
            if spec is not None:
                method, kwargs = next(iter(spec.items()))
                args_str = ", ".join(f"{k}={v!r}" for k, v in kwargs.items())
                lines.append(f"    .{method}({args_str})")
            else:
                lines.append(f"    # {proc.name} (сериализация недоступна)")

        lines.append("    .build()")
        lines.append(")")
        return "\n".join(lines)
