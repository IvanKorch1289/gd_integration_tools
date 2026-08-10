"""W23 — Конкретные backends Source + фабрика.

Каждый backend живёт в собственном модуле
(``webhook.py``, ``mq.py``, ``cdc.py``, ...) и собирается через
:func:`build_source` (match по ``SourceKind``).

Тяжёлые зависимости (psycopg3 для CDC, spyne для SOAP, nats-py для NATS)
лениво подгружаются внутри конкретного класса, чтобы dev_light без них
оставался работоспособным.
"""

from src.backend.infrastructure.sources.factory import (
    build_source,  # noqa: F401 — re-export
)
from src.backend.infrastructure.sources.file_watcher import (  # noqa: F401 — re-export
    FileEvent,
    FileWatcherSource,
)

__all__ = ("FileEvent", "FileWatcherSource", "build_source")
