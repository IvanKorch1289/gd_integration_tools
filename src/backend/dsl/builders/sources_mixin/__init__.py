"""SourcesMixin package (S57 W2 decomp from sources_mixin.py 590 LOC).

11 methods decomposed в 7 mixin files (S57 W2):
- http_sources_mixin.py (1): from_webdav
- cdc_sources_mixin.py (3): from_cdc, from_cdc_logical, from_cdc_capture
- messaging_sources_mixin.py (3): from_kafka, from_rabbit, from_mqtt
- streaming_sources_mixin.py (1): from_redis_streams
- file_sources_mixin.py (1): from_filewatcher
- webhook_sources_mixin.py (1): from_webhook
- schedule_sources_mixin.py (1): from_schedule

S94 W4: добавлен 8-й mixin — sse_sources_mixin.py (1): from_sse.
S97 W4: добавлен 9-й mixin — telegram_sources_mixin.py (1): from_telegram.
S132 W4: добавлен 10-й mixin — external_sources_mixin.py (1): from_grpc_stream
  (TD-011 PARTIAL closure). from_nats/from_mongo — ALREADY EXIST в
  transport/sources.py (S106 W4, feature-flag default-OFF) — не дублируем
  per R10 (no parallel versions).

Backward-compat: ``from src.backend.dsl.builders.sources_mixin import SourcesMixin`` works.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.backend.core.logging import get_logger

if TYPE_CHECKING:
    pass

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder

logger = get_logger(__name__)

from src.backend.dsl.builders.sources_mixin.cdc_sources_mixin import (
    CdcSourcesMixin,  # S57 W2: MRO
)
from src.backend.dsl.builders.sources_mixin.external_sources_mixin import (
    ExternalSourcesMixin,  # S132 W4: gRPC stream (TD-011 partial)
)
from src.backend.dsl.builders.sources_mixin.file_sources_mixin import (
    FileSourcesMixin,  # S57 W2: MRO
)
from src.backend.dsl.builders.sources_mixin.http_sources_mixin import (
    HttpSourcesMixin,  # S57 W2: MRO
)
from src.backend.dsl.builders.sources_mixin.messaging_sources_mixin import (
    MessagingSourcesMixin,  # S57 W2: MRO
)
from src.backend.dsl.builders.sources_mixin.schedule_sources_mixin import (
    ScheduleSourcesMixin,  # S57 W2: MRO
)
from src.backend.dsl.builders.sources_mixin.sse_sources_mixin import (
    StreamingSSEMixin,  # S94 W4: SSE
)
from src.backend.dsl.builders.sources_mixin.streaming_sources_mixin import (
    StreamingSourcesMixin,  # S57 W2: MRO
)
from src.backend.dsl.builders.sources_mixin.telegram_sources_mixin import (
    TelegramSourcesMixin,  # S97 W4: Telegram Bot webhook
)
from src.backend.dsl.builders.sources_mixin.webhook_sources_mixin import (
    WebhookSourcesMixin,  # S57 W2: MRO
)

__all__ = ("SourcesMixin",)


class SourcesMixin(
    HttpSourcesMixin,
    CdcSourcesMixin,
    MessagingSourcesMixin,
    StreamingSourcesMixin,
    StreamingSSEMixin,  # S94 W4: SSE
    FileSourcesMixin,
    WebhookSourcesMixin,
    ScheduleSourcesMixin,
    TelegramSourcesMixin,  # S97 W4: Telegram Bot
    ExternalSourcesMixin,  # S132 W4: NATS/Mongo/gRPC (TD-011)
):
    """Sources mixin (10 mixins = 14 methods)."""

    __slots__ = ()
