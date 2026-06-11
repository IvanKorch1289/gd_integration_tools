from __future__ import annotations
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

# ─── Constants & defaults ──────────────────────────────────────────────

_VALID_TYPES: frozenset[str] = frozenset({"invoice", "contract", "receipt", "other"})
_DEFAULT_TYPE: str = "other"
_DEFAULT_THRESHOLD: float = 0.8
_STAGE_REACHED: str = "route"  # final stage label

# Classification keyword map (case-insensitive).
_CLASSIFY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "invoice": ("invoice", "bill to", "amount due", "invoice number"),
    "contract": ("contract", "agreement", "party a", "party b", "whereas"),
    "receipt": ("receipt", "paid", "thank you for your purchase", "subtotal"),
}

# Default extractors: dict[type] → list[(field_name, regex)].
# Patterns are deliberately permissive to keep confidence ≥ threshold
# on well-formed documents.

class PipelineMixin:
    """pipeline execution (process + _run_pipeline) для IDPPipelineProcessor. S65 W4 extraction."""

    __slots__ = ()

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        result = self._run_pipeline(exchange)
        # Persist observability snapshot.
        exchange.set_property(self._result_property, self._result_to_dict(result))
        exchange.set_property("idp_doc_type", result.doc_type)
        exchange.set_property("idp_extracted_fields", dict(result.fields))
        exchange.set_property("idp_confidence", result.confidence)
        exchange.set_property("idp_validation_errors", list(result.validation_errors))
        exchange.set_property("idp_stage_reached", result.stage_reached)
        exchange.set_property(self._hitl_property, result.needs_hitl)
        exchange.set_property("idp_auto_processed", result.auto_processed)

    def _run_pipeline(self, exchange: Exchange[Any]) -> IDPResult:
        """Run the 5 stages and return a populated :class:`IDPResult`.

        Designed to be re-runnable / idempotent: re-invoking with the
        same ``exchange`` (and no prior ``idp_*`` properties) yields
        the same result.
        """
        # Stage 1 — Ingest
        text = _coerce_to_text(exchange.in_message.body)
        result = IDPResult(doc_type=self._doc_type)
        result.stage_reached = "ingest"

        # Stage 2 — Classify (or skip if forced)
        if self._doc_type == "auto":
            result.doc_type = classify_document(text)
        else:
            result.doc_type = self._doc_type
        result.stage_reached = "classify"

        # Stage 3 — Extract
        result.fields = extract_fields(
            text, result.doc_type, extractors=self._extractors
        )
        result.stage_reached = "extract"

        # Stage 4 — Validate
        validate_result(result, text, validators=self._validators)
        result.stage_reached = "validate"

        # Stage 5 — Route
        self._route(result)
        result.stage_reached = _STAGE_REACHED
        return result

