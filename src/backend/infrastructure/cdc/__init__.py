"""R2.1 — CDC backends infrastructure.

3 встроенных backend'а:

* ``PollCDCBackend`` — universal polling по `updated_at` колонке.
* ``ListenNotifyCDCBackend`` — PostgreSQL `LISTEN/NOTIFY`.
* ``DebeziumEventsCDCBackend`` — Kafka topic с Debezium-сообщениями.
"""

from src.backend.infrastructure.cdc.debezium_events_backend import (
    DebeziumEventsCDCBackend,
)
from src.backend.infrastructure.cdc.listen_notify_backend import ListenNotifyCDCBackend
from src.backend.infrastructure.cdc.poll_backend import PollCDCBackend

__all__ = ("DebeziumEventsCDCBackend", "ListenNotifyCDCBackend", "PollCDCBackend")
