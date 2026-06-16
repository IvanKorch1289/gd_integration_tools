from __future__ import annotations

from typing import Any

from src.backend.dsl.processors.idp_pipeline_processor.helpers import DEFAULT_EXTRACTORS
from src.backend.dsl.processors.idp_pipeline_processor.state import IDPResult


class HelpersMixin:
    """pipeline helpers (_pattern_count + _result_to_dict) для IDPPipelineProcessor. S65 W4 extraction."""

    __slots__ = ()

    def _pattern_count(self, doc_type: str) -> int:
        if self._extractors is not None and doc_type in self._extractors:
            return len(self._extractors[doc_type])
        return len(DEFAULT_EXTRACTORS.get(doc_type, []))

    def _result_to_dict(self, result: IDPResult) -> dict[str, Any]:
        return {
            "doc_type": result.doc_type,
            "fields": dict(result.fields),
            "confidence": result.confidence,
            "validation_errors": list(result.validation_errors),
            "needs_hitl": result.needs_hitl,
            "auto_processed": result.auto_processed,
            "stage_reached": result.stage_reached,
        }
