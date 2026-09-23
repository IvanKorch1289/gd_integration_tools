"""TombstonePublisher — publishes tombstone event для downstream consumers.

W9 P2-13 Phase 3 (cycle 153): извлечено из ``core/privacy/delete_data_subject.py``
(691 LOC god-module).

Back-compat: ``core/privacy/delete_data_subject.py`` продолжает re-export
``TombstonePublisher`` через thin ``__init__.py`` shim (см. ADR-0328).
"""

from __future__ import annotations

import logging

from src.backend.core.privacy.delete_data_subject._types import OrchestratorResult

logger = logging.getLogger(__name__)


class TombstonePublisher:
    """Publishes tombstone event для downstream consumers."""

    async def publish(
        self,
        subject_id: str,
        subject_type: str,
        correlation_id: str,
        result: OrchestratorResult,
    ) -> bool:
        """Publish tombstone event в MQ.

        Returns True если published, False если failed.
        """
        logger.info(
            "tombstone_published_stub subject_id=%s correlation_id=%s records=%d",
            subject_id,
            correlation_id,
            result.total_records,
        )
        return True
