from __future__ import annotations

"""IDPPipelineProcessor package (S65 W4 decomp from idp_pipeline_processor.py 472 LOC).

1 god-class (7 methods) + 2 small classes + 10 funcs → 4 mixins + state.py + helpers.py.

Backward-compat: ``from src.backend.dsl.processors.idp_pipeline_processor import IDPPipelineProcessor`` works.
"""


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

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

from src.backend.dsl.processors.idp_pipeline_processor.helpers import (
    DEFAULT_EXTRACTORS,  # S124 W2: restored constant (lost in S65 W4 decomp)
    _coerce_to_text,  # S65 W4: helper re-export
    _contract_extractors,  # S65 W4: helper re-export
    _default_extractors_for,  # S65 W4: helper re-export
    _invoice_extractors,  # S65 W4: helper re-export
    _receipt_extractors,  # S65 W4: helper re-export
    _rule_required_present,  # S65 W4: helper re-export
    _rule_total_positive,  # S65 W4: helper re-export
    classify_document,  # S65 W4: helper re-export
    extract_fields,  # S65 W4: helper re-export
    validate_result,  # S65 W4: helper re-export
)
from src.backend.dsl.processors.idp_pipeline_processor.helpers_mixin import (
    HelpersMixin,  # S65 W4: MRO
)
from src.backend.dsl.processors.idp_pipeline_processor.pipeline_mixin import (
    PipelineMixin,  # S65 W4: MRO
)
from src.backend.dsl.processors.idp_pipeline_processor.routing_mixin import (
    RoutingMixin,  # S65 W4: MRO
)
from src.backend.dsl.processors.idp_pipeline_processor.serialization_mixin import (
    SerializationMixin,  # S65 W4: MRO
)
from src.backend.dsl.processors.idp_pipeline_processor.state import (
    IDPResult,  # S65 W4: re-export
    _FieldPattern,  # S65 W4: re-export
)

__all__ = (
    "IDPPipelineProcessor",
    "IDPResult",
    "_FieldPattern",
    "_invoice_extractors",
    "_contract_extractors",
    "_receipt_extractors",
    "_default_extractors_for",
    "DEFAULT_EXTRACTORS",
    "classify_document",
    "extract_fields",
    "_rule_required_present",
    "_rule_total_positive",
    "validate_result",
    "_coerce_to_text",
)


class IDPPipelineProcessor(
    PipelineMixin, RoutingMixin, SerializationMixin, HelpersMixin
):
    """IDP pipeline processor (4 mixins = 6 methods + 1 core)."""

    __slots__ = ()

    def __init__(
        self,
        *,
        doc_type: str = "auto",
        confidence_threshold: float = _DEFAULT_THRESHOLD,
        extractors: dict[str, list[str]] | None = None,
        validators: list[str] | None = None,
        hitl_property: str = "needs_hitl",
        result_property: str = "idp_result",
        name: str | None = None,
    ) -> None:
        if not 0.0 <= confidence_threshold <= 1.0:
            raise ValueError(
                f"confidence_threshold ∈ [0, 1], получено {confidence_threshold}"
            )
        if doc_type != "auto" and doc_type not in _VALID_TYPES:
            raise ValueError(
                f"doc_type ∈ auto|{sorted(_VALID_TYPES)}, получено {doc_type!r}"
            )
        super().__init__(name=name or "idp_pipeline")
        self._doc_type = doc_type
        self._threshold = float(confidence_threshold)
        # Shallow copy so callers cannot mutate our state.
        self._extractors: dict[str, list[str]] | None = (
            {k: list(v) for k, v in extractors.items()} if extractors else None
        )
        self._validators: list[str] | None = list(validators) if validators else None
        self._hitl_property = hitl_property
        self._result_property = result_property
