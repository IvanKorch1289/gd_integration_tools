from __future__ import annotations

from src.backend.dsl.processors.idp_pipeline_processor._protocol import (
    _IDPPipelineProtocol,
)
from src.backend.dsl.processors.idp_pipeline_processor.state import IDPResult


class RoutingMixin(_IDPPipelineProtocol):
    """pipeline routing (_route) для IDPPipelineProcessor. S65 W4 extraction."""

    __slots__ = ()

    def _route(self, result: IDPResult) -> None:
        """Decide HITL vs auto. Mutates ``result`` in place."""
        # Total pattern count for confidence.
        total_patterns = self._pattern_count(result.doc_type)
        if total_patterns == 0:
            # No patterns → confidence is 0 (other / unconfigured type).
            result.confidence = 0.0
        else:
            result.confidence = round(len(result.fields) / total_patterns, 4)
        if result.validation_errors:
            result.needs_hitl = True
            result.auto_processed = False
            return
        if result.confidence >= self._threshold:
            result.needs_hitl = False
            result.auto_processed = True
        else:
            result.needs_hitl = True
            result.auto_processed = False
