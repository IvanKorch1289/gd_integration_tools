"""EIP / streaming / transport / messaging mixins для RouteBuilder.

Sprint 60 W4 — split из god-file ``eip.py`` (1354 LOC) на 8 per-domain модулей:

- :mod:`._base` — общие импорты, базовый контракт
- :mod:`.core` — transform, filter, cdc
- :mod:`.routing` — dynamic_route, scatter_gather, routing_slip, content_based_router,
  sampling, load_balance, multicast_routes, translate (DEPRECATED)
- :mod:`.sources` — from_interval, from_webhook, from_file, from_sql, from_http, from_s3, sse_source
- :mod:`.transformation` — split, aggregate, sort, claim_check, normalize, resequence
- :mod:`.protocols` — protocol, transport, on_completion
- :mod:`.streaming` — windowed_dedup, batch, windowed_collect, tumbling/sliding/session windows, group_by_key
- :mod:`.messaging` — validate_schema, reply_to, exactly_once, durable_fanout, purge_channel,
  sample, schema_validate, composed_message
- :mod:`.messengers` — express_* (7) + telegram_* (8)

:class:`EIPMixin` — combined class через множественное наследование.
API полностью backward-compatible с предыдущим ``eip.py``.

Apache Camel EIP reference: https://camel.apache.org/components/latest/eips/patterns.html
Apache Camel Routing Slip: https://camel.apache.org/components/latest/eips/routingSlip.html
Apache Camel Content-Based Router: https://camel.apache.org/components/latest/eips/contentBasedRouter.html
Apache Airflow Sensor: https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/sensors.html
"""

from __future__ import annotations

from src.backend.dsl.builders.eip.core import CoreEIPsMixin
from src.backend.dsl.builders.eip.messaging import MessagingEIPsMixin
from src.backend.dsl.builders.eip.messengers import MessengersEIPsMixin
from src.backend.dsl.builders.eip.protocols import ProtocolsEIPsMixin
from src.backend.dsl.builders.eip.routing import RoutingEIPsMixin
from src.backend.dsl.builders.eip.sources import SourcesEIPsMixin
from src.backend.dsl.builders.eip.streaming import StreamingEIPsMixin
from src.backend.dsl.builders.eip.transformation import TransformationEIPsMixin

__all__ = ("EIPMixin",)


class EIPMixin(
    CoreEIPsMixin,
    RoutingEIPsMixin,
    SourcesEIPsMixin,
    TransformationEIPsMixin,
    ProtocolsEIPsMixin,
    StreamingEIPsMixin,
    MessagingEIPsMixin,
    MessengersEIPsMixin,
):
    """Поведенческий миксин EIP / streaming / transport для ``RouteBuilder``.

    Stateless: миксин использует ``self._add`` / ``self._add_lazy`` /
    ``self._processors`` / ``self.route_id`` / ``self._protocol`` /
    ``self._transport_config`` через MRO; собственных полей не содержит.

    Содержит 59 публичных методов, разбитых на 8 per-domain mixin-классов
    (см. :mod:`__init__`).
    """
