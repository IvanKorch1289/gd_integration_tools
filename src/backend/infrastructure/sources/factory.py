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

from typing import TYPE_CHECKING

from src.backend.core.interfaces.source import Source, SourceKind
from src.backend.core.logging import get_logger

if TYPE_CHECKING:
    from src.backend.core.config.source_spec import SourceSpec

__all__ = ("build_source",)

logger = get_logger("services.sources.factory")


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
            from src.backend.infrastructure.sources.webhook import WebhookSource

            return WebhookSource(source_id=spec.id, **spec.config)
        case SourceKind.HTTP:
            from src.backend.infrastructure.sources.http import HttpSource

            return HttpSource(source_id=spec.id, **spec.config)
        case SourceKind.MQ:
            from src.backend.infrastructure.sources.mq import MQSource

            return MQSource(source_id=spec.id, **spec.config)
        case SourceKind.FILE_WATCHER:
            from pathlib import Path

            from src.backend.infrastructure.sources.file_watcher import (
                FileWatcherSource,
            )

            config = dict(spec.config)
            if "directory" in config:
                config["path"] = Path(config.pop("directory"))
            return FileWatcherSource(source_id=spec.id, **config)
        case SourceKind.POLLING:
            from src.backend.infrastructure.sources.polling import PollingSource

            return PollingSource(source_id=spec.id, **spec.config)
        case SourceKind.WEBSOCKET:
            from src.backend.infrastructure.sources.websocket import WebSocketSource

            return WebSocketSource(source_id=spec.id, **spec.config)
        case SourceKind.SOAP:
            from src.backend.infrastructure.sources.soap import SoapSource

            return SoapSource(source_id=spec.id, **spec.config)
        case SourceKind.GRPC:
            from src.backend.infrastructure.sources.grpc import GrpcSource

            return GrpcSource(source_id=spec.id, **spec.config)
        case SourceKind.CDC:
            from src.backend.infrastructure.sources.cdc import CDCSource

            return CDCSource(source_id=spec.id, **spec.config)
        case SourceKind.EMAIL:
            from src.backend.infrastructure.sources.email import EmailSource

            return EmailSource(source_id=spec.id, **spec.config)
        case _:
            raise ValueError(f"Unknown SourceKind: {spec.kind!r}")
