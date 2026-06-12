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
):
    """Sources mixin (8 mixins = 12 methods)."""

    __slots__ = ()
