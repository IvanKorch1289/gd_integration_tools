"""IDPPipelineProcessor — 5-stage Intelligent Document Processing pipeline.

S39 W1: regex-based IDP without external ML services.

Pipeline (5 stages, all synchronous, idempotent)::

    ingest (PDF/IMG/DOCX → raw text)
      → classify (doc type: invoice | contract | receipt | other)
      → extract (fields via regex patterns per type)
      → validate (confidence + business rules)
      → route (high-confidence → auto, low → HITL)

Observability: every stage writes to ``exchange.properties`` under
``idp_*`` keys (``idp_stage_reached``, ``idp_confidence``,
``idp_validation_errors``, ``idp_doc_type``, ``idp_extracted_fields``)
so callers (RouteBuilder / debug UI) can introspect progress.

Differences vs. a full ML-backed IDP:

* No OCR / no LLM calls — classification and extraction are regex-based.
* No external I/O. Pure transformation: same body in → same result out.
* Stdlib only (``re``, ``dataclasses``, ``json``).
* Idempotent by construction: no state, no side effects. Re-running the
  same ``exchange`` yields identical ``exchange.properties`` snapshot.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = (
    "DEFAULT_EXTRACTORS",
    "IDPPipelineProcessor",
    "IDPResult",
    "classify_document",
    "extract_fields",
    "validate_result",
)


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
@dataclass(frozen=True, slots=True)
class _FieldPattern:
    """Immutable (field name, regex) pair."""

    name: str
    pattern: str

    def compiled(self) -> re.Pattern[str]:
        return re.compile(self.pattern, re.IGNORECASE | re.MULTILINE)


def _invoice_extractors() -> list[_FieldPattern]:
    return [
        _FieldPattern("invoice_number", r"invoice\s*#?\s*[:\-]?\s*(\w+[\w\-]*)"),
        _FieldPattern("total", r"total\s*[:\-]?\s*\$?([\d,]+\.?\d*)"),
        _FieldPattern(
            "date", r"date\s*[:\-]?\s*([0-9]{1,4}[/\-\.][0-9]{1,2}[/\-\.][0-9]{1,4})"
        ),
        _FieldPattern(
            "vendor", r"(?:from|vendor|seller)\s*[:\-]?\s*([A-Za-z0-9 ,.&'\-]{2,40})"
        ),
    ]


def _contract_extractors() -> list[_FieldPattern]:
    return [
        _FieldPattern("party_a", r"party\s*a\s*[:\-]?\s*([A-Za-z0-9 ,.&'\-]{2,60})"),
        _FieldPattern("party_b", r"party\s*b\s*[:\-]?\s*([A-Za-z0-9 ,.&'\-]{2,60})"),
        _FieldPattern(
            "effective_date",
            r"effective\s*date\s*[:\-]?\s*([0-9]{1,4}[/\-\.][0-9]{1,2}[/\-\.][0-9]{1,4})",
        ),
        _FieldPattern("term", r"term\s*[:\-]?\s*([0-9]+)\s*(year|month|day)s?"),
    ]


def _receipt_extractors() -> list[_FieldPattern]:
    return [
        _FieldPattern("merchant", r"merchant\s*[:\-]?\s*([A-Za-z0-9 ,.&'\-]{2,40})"),
        _FieldPattern("subtotal", r"subtotal\s*[:\-]?\s*\$?([\d,]+\.?\d*)"),
        _FieldPattern("tax", r"tax\s*[:\-]?\s*\$?([\d,]+\.?\d*)"),
        _FieldPattern("total", r"total\s*[:\-]?\s*\$?([\d,]+\.?\d*)"),
    ]


def _default_extractors_for(doc_type: str) -> list[_FieldPattern]:
    """Return default regex extractors for a given document type."""
    if doc_type == "invoice":
        return _invoice_extractors()
    if doc_type == "contract":
        return _contract_extractors()
    if doc_type == "receipt":
        return _receipt_extractors()
    return []


# Public view of default extractors (dict-of-str-to-list-of-regex).
# Useful for tests and for YAML round-trip serialization.
DEFAULT_EXTRACTORS: dict[str, list[str]] = {
    "invoice": [p.pattern for p in _invoice_extractors()],
    "contract": [p.pattern for p in _contract_extractors()],
    "receipt": [p.pattern for p in _receipt_extractors()],
}


# ─── Pure helpers (re-usable, side-effect-free) ───────────────────────


def classify_document(text: str) -> str:
    """Classify text into ``invoice | contract | receipt | other``.

    Returns the type with the highest keyword match count. Ties are
    broken by declaration order in ``_CLASSIFY_KEYWORDS`` (invoice
    wins over contract, which wins over receipt).

    Args:
        text: Raw text (already bytes-decoded, lower-cased internally).

    Returns:
        Doc type string. Always one of ``_VALID_TYPES``.
    """
    if not text:
        return _DEFAULT_TYPE
    haystack = text.lower()
    best_type = _DEFAULT_TYPE
    best_count = 0
    for doc_type, keywords in _CLASSIFY_KEYWORDS.items():
        count = sum(1 for kw in keywords if kw in haystack)
        if count > best_count:
            best_count = count
            best_type = doc_type
    return best_type


def extract_fields(
    text: str, doc_type: str, *, extractors: dict[str, list[str]] | None = None
) -> dict[str, str]:
    """Apply regex extractors for a given doc_type and return fields.

    Args:
        text: Raw text to scan.
        doc_type: Document type — drives pattern selection.
        extractors: Optional custom patterns; format
            ``{doc_type: [regex, regex, ...]}``. If absent for a given
            type, falls back to :data:`DEFAULT_EXTRACTORS`.

    Returns:
        Mapping ``{field_name: first_match}`` for fields that matched.
    """
    if not text:
        return {}
    patterns: list[str]
    if extractors is not None and doc_type in extractors:
        patterns = list(extractors[doc_type])
    else:
        patterns = list(DEFAULT_EXTRACTORS.get(doc_type, []))
    out: dict[str, str] = {}
    # Iterate with the default _FieldPattern-derived names to keep
    # field names stable (e.g. "invoice_number" for invoice #1 pattern).
    default_named = _default_extractors_for(doc_type)
    for idx, raw_pattern in enumerate(patterns):
        try:
            rx = re.compile(raw_pattern, re.IGNORECASE | re.MULTILINE)
        except re.error:
            continue  # skip malformed user-supplied pattern
        m = rx.search(text)
        if m is None:
            continue
        value = (m.group(1) if m.lastindex else m.group(0)).strip()
        # Re-derive the canonical field name from the default set when
        # possible — this gives us "invoice_number" for the first
        # pattern, etc.  For custom extractors we fall back to a
        # positional name.
        if idx < len(default_named):
            name = default_named[idx].name
        else:
            name = f"field_{idx + 1}"
        out[name] = value
    return out


@dataclass(slots=True)
class IDPResult:
    """Immutable snapshot of one IDP pipeline run.

    Attributes:
        doc_type: Classified or forced document type.
        fields: Extracted field values.
        confidence: ``matched / total_patterns`` in ``[0.0, 1.0]``.
        validation_errors: List of human-readable error messages.
        needs_hitl: ``True`` if HITL is required.
        auto_processed: ``True`` if high-confidence + validation passed.
        stage_reached: Last successfully reached stage label.
    """

    doc_type: str
    fields: dict[str, str] = field(default_factory=dict)
    confidence: float = 0.0
    validation_errors: list[str] = field(default_factory=list)
    needs_hitl: bool = True
    auto_processed: bool = False
    stage_reached: str = "ingest"


# Validation rule registry — names mapped to (predicate, error_message).
def _rule_required_present(result: IDPResult, _text: str) -> str | None:
    if not result.fields:
        return "no fields extracted"
    return None


def _rule_total_positive(result: IDPResult, _text: str) -> str | None:
    """Total field, if present, must parse to a number > 0."""
    if "total" not in result.fields:
        return None
    raw = result.fields["total"].replace(",", "")
    try:
        value = float(raw)
    except TypeError, ValueError:
        return f"total is not numeric: {result.fields['total']!r}"
    if value <= 0:
        return f"total must be > 0, got {value}"
    return None


_VALIDATORS: dict[str, Callable[[IDPResult, str], str | None]] = {
    "required_fields": _rule_required_present,
    "total_positive": _rule_total_positive,
}


def validate_result(
    result: IDPResult, text: str, *, validators: list[str] | None = None
) -> list[str]:
    """Run business rules against a populated ``IDPResult``.

    Args:
        result: Result to validate (mutated: ``validation_errors`` is
            cleared and re-populated).
        text: Original text (for context-dependent rules).
        validators: List of validator names. ``None`` → use all
            default validators. Unknown names are silently skipped
            (and recorded as errors for transparency).

    Returns:
        The list of validation errors (also stored in
        ``result.validation_errors``).
    """
    names = list(validators) if validators else list(_VALIDATORS)
    errors: list[str] = []
    for name in names:
        fn = _VALIDATORS.get(name)
        if fn is None:
            errors.append(f"unknown validator: {name}")
            continue
        err = fn(result, text)
        if err:
            errors.append(err)
    result.validation_errors = errors
    return errors


# ─── Ingest helpers ────────────────────────────────────────────────────


def _coerce_to_text(body: Any) -> str:
    """Convert a body of any supported type into a searchable text.

    * ``str`` → as-is.
    * ``bytes`` / ``bytearray`` → decode (``utf-8`` with ``replace``).
    * ``dict`` / ``list`` → ``json.dumps``.
    * Other → ``str(body)``.
    """
    if isinstance(body, str):
        return body
    if isinstance(body, (bytes, bytearray)):
        return bytes(body).decode("utf-8", errors="replace")
    if isinstance(body, (dict, list)):
        import json

        return json.dumps(body, default=str)
    return str(body)


# ─── Main processor ────────────────────────────────────────────────────


class IDPPipelineProcessor(BaseProcessor):
    """5-stage IDP: Ingest → Classify → Extract → Validate → Route.

    The processor is purely synchronous — no I/O calls, no LLM, no
    regex compilation cost on hot path beyond one-pass scanning.  It
    is therefore safe to chain inline with other processors, run
    inside a Saga compensator, or replay on retries.

    Observability surface (all written to ``exchange.properties``)::

        idp_doc_type:          str   # classified or forced type
        idp_extracted_fields:  dict  # extracted field name → value
        idp_confidence:        float # matched / total patterns
        idp_validation_errors: list[str]
        idp_stage_reached:     str   # last completed stage label
        idp_needs_hitl:        bool
        idp_auto_processed:    bool
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE
    compensatable: ClassVar[bool] = True

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

    # ── Public API ──

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

    # ── Pipeline driver (pure, testable without exchange) ──

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

    def _pattern_count(self, doc_type: str) -> int:
        if self._extractors is not None and doc_type in self._extractors:
            return len(self._extractors[doc_type])
        return len(DEFAULT_EXTRACTORS.get(doc_type, []))

    # ── Serialization ──

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

    def to_spec(self) -> dict[str, Any] | None:
        """YAML-round-trip spec for IDPPipelineProcessor."""
        return {
            "idp_pipeline": {
                "doc_type": self._doc_type,
                "confidence_threshold": self._threshold,
                "extractors": (
                    {k: list(v) for k, v in self._extractors.items()}
                    if self._extractors
                    else None
                ),
                "validators": list(self._validators) if self._validators else None,
                "hitl_property": self._hitl_property,
                "result_property": self._result_property,
            }
        }
