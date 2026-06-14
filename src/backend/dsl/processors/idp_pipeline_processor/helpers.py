from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from src.backend.dsl.processors.idp_pipeline_processor.state import _FieldPattern

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


# Public default-extractors mapping: type → list[regex]. Restored in S124 W2
# (was lost during S65 W4 decomp). Used by IDP tests + public API.
DEFAULT_EXTRACTORS: dict[str, list[str]] = {
    "invoice": [p.regex for p in _invoice_extractors()],
    "contract": [p.regex for p in _contract_extractors()],
    "receipt": [p.regex for p in _receipt_extractors()],
}


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
    except (TypeError, ValueError):
        return f"total is not numeric: {result.fields['total']!r}"
    if value <= 0:
        return f"total must be > 0, got {value}"
    return None


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
