"""W23 — Фабрика :class:`Source` по :class:`SourceSpec`.

Match по ``SourceKind`` → конкретный backend из
``infrastructure/sources/<kind>/``. Импорт backend'а ленивый, чтобы
dev_light без psycopg3/spyne/nats-py не падал на старте.

Типичное использование (composition root):

```python
for spec in load_sources_spec().sources:
    source = build_source(spec)
    source_registry.register(source)
```
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.core.interfaces.source import Source, SourceKind

if TYPE_CHECKING:
    from src.core.config.source_spec import SourceSpec

__all__ = ("build_source",)

logger = logging.getLogger("services.sources.factory")


def build_source(spec: SourceSpec) -> Source:
    """Создать ``Source``-инстанс по описанию из YAML.

    Args:
        spec: Валидированная :class:`SourceSpec` (kind, id, config).

    Returns:
        Конкретная реализация ``Source`` (Protocol-совместимая).

    Raises:
        ValueError: при неизвестном ``kind`` (защитный код — schema
            обычно ловит это раньше).
    """
    match spec.kind:
        case SourceKind.WEBHOOK:
            from src.infrastructure.sources.webhook import WebhookSource

            return WebhookSource(source_id=spec.id, **spec.config)
        case SourceKind.HTTP:
            from src.infrastructure.sources.http import HttpSource

            return HttpSource(source_id=spec.id, **spec.config)
        case SourceKind.MQ:
            from src.infrastructure.sources.mq import MQSource

            return MQSource(source_id=spec.id, **spec.config)
        case SourceKind.FILE_WATCHER:
            from src.infrastructure.sources.file_watcher import FileWatcherSource

            return FileWatcherSource(source_id=spec.id, **spec.config)
        case SourceKind.POLLING:
            from src.infrastructure.sources.polling import PollingSource

            return PollingSource(source_id=spec.id, **spec.config)
        case SourceKind.WEBSOCKET:
            from src.infrastructure.sources.websocket import WebSocketSource

            return WebSocketSource(source_id=spec.id, **spec.config)
        case SourceKind.SOAP:
            from src.infrastructure.sources.soap import SoapSource

            return SoapSource(source_id=spec.id, **spec.config)
        case SourceKind.GRPC:
            from src.infrastructure.sources.grpc import GrpcSource

            return GrpcSource(source_id=spec.id, **spec.config)
        case SourceKind.CDC:
            from src.infrastructure.sources.cdc import CDCSource

            return CDCSource(source_id=spec.id, **spec.config)
        case _:
            raise ValueError(f"Unknown SourceKind: {spec.kind!r}")
