from __future__ import annotations

"""Enrichment processors package (S61 W2 decomp from enrichment.py 523 LOC).

8 processor classes decomposed в 5 files (per enrichment type):
- ``geo_ip.py``: GeoIpProcessor
- ``jwt.py``: JwtSignProcessor, JwtVerifyProcessor
- ``compression.py``: CompressProcessor, DecompressProcessor
- ``webhook.py``: WebhookSignProcessor, WebhookSignVerifyProcessor
- ``deadline.py``: DeadlineProcessor

Backward-compat: ``from src.backend.dsl.engine.processors.enrichment import GeoIpProcessor`` works.
"""


from src.backend.dsl.engine.processors.enrichment.compression import (
    CompressProcessor,  # S61 W2: re-export
    DecompressProcessor,  # S61 W2: re-export
)
from src.backend.dsl.engine.processors.enrichment.deadline import (
    DeadlineProcessor,  # S61 W2: re-export
)
from src.backend.dsl.engine.processors.enrichment.geo_ip import (
    GeoIpProcessor,  # S61 W2: re-export
)
from src.backend.dsl.engine.processors.enrichment.jwt import (
    JwtSignProcessor,  # S61 W2: re-export
    JwtVerifyProcessor,  # S61 W2: re-export
)
from src.backend.dsl.engine.processors.enrichment.webhook import (
    WebhookSignProcessor,  # S61 W2: re-export
    WebhookSignVerifyProcessor,  # S61 W2: re-export
)

__all__ = (
    "GeoIpProcessor",
    "JwtSignProcessor",
    "JwtVerifyProcessor",
    "CompressProcessor",
    "DecompressProcessor",
    "WebhookSignProcessor",
    "WebhookSignVerifyProcessor",
    "DeadlineProcessor",
)
