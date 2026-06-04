"""Unit tests for IDPPipelineProcessor (S39 W1).

5 stages tested: Ingest → Classify → Extract → Validate → Route.
17+ test cases covering classification, extraction, validation, routing,
threshold configurability, state observability, idempotency, defaults,
and YAML-spec round-trip.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.processors.idp_pipeline_processor import (
    DEFAULT_EXTRACTORS,
    IDPPipelineProcessor,
    IDPResult,
    classify_document,
    extract_fields,
    validate_result,
)

# ─── Fixtures ──────────────────────────────────────────────────────────


def _make_exchange(body: Any = b"") -> Exchange:
    msg = Message(body=body, headers={})
    return Exchange(in_message=msg, out_message=msg)


_INVOICE_BODY = (
    b"Invoice #12345\nDate: 2026-05-01\nVendor: Acme Corp\nTotal: $1,234.56\n"
)

_CONTRACT_BODY = (
    b"Service Agreement\n"
    b"Party A: Acme Corp\n"
    b"Party B: Beta LLC\n"
    b"Effective Date: 2026-01-15\n"
    b"Term: 24 months\n"
)

_RECEIPT_BODY = (
    b"Receipt\n"
    b"Merchant: Coffee Shop\n"
    b"Subtotal: $10.00\n"
    b"Tax: $1.00\n"
    b"Total: $11.00\n"
    b"Thank you for your purchase!\n"
)


# ─── Stage 2 — Classify ────────────────────────────────────────────────


class TestClassification:
    def test_idp_invoice_classification(self) -> None:
        result = classify_document(_INVOICE_BODY.decode())
        assert result == "invoice"

    def test_idp_contract_classification(self) -> None:
        result = classify_document(_CONTRACT_BODY.decode())
        assert result == "contract"

    def test_idp_receipt_classification(self) -> None:
        result = classify_document(_RECEIPT_BODY.decode())
        assert result == "receipt"

    def test_idp_unknown_classification(self) -> None:
        result = classify_document("Random document with no keywords here.")
        assert result == "other"

    def test_idp_empty_text_classification(self) -> None:
        assert classify_document("") == "other"

    def test_idp_classification_case_insensitive(self) -> None:
        # Uppercase keywords should still match.
        assert classify_document("INVOICE #999 Total: $50.00") == "invoice"

    def test_idp_classification_bytes_body(self) -> None:
        """The processor should accept bytes body via ``_coerce_to_text``."""
        p = IDPPipelineProcessor()
        ex = _make_exchange(_INVOICE_BODY)
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(p.process(ex, MagicMock()))
        finally:
            loop.close()
        assert ex.get_property("idp_doc_type") == "invoice"


# ─── Stage 3 — Extract ─────────────────────────────────────────────────


class TestExtraction:
    def test_idp_extract_invoice(self) -> None:
        p = IDPPipelineProcessor()
        ex = _make_exchange(_INVOICE_BODY)
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(p.process(ex, MagicMock()))
        finally:
            loop.close()
        fields = ex.get_property("idp_extracted_fields")
        assert "invoice_number" in fields
        assert fields["invoice_number"] == "12345"
        assert "total" in fields
        assert "1,234.56" in fields["total"]
        assert "vendor" in fields
        assert "date" in fields

    def test_idp_extract_with_custom_patterns(self) -> None:
        """Custom extractors inherit canonical field names from defaults."""
        custom = {"invoice": [r"Ref\s*[:\-]\s*(\w+)", r"Amount\s*[:\-]\s*\$?([\d.]+)"]}
        p = IDPPipelineProcessor(doc_type="invoice", extractors=custom)
        ex = _make_exchange(b"Ref: ABC99\nAmount: $750.00")
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(p.process(ex, MagicMock()))
        finally:
            loop.close()
        fields = ex.get_property("idp_extracted_fields")
        # Custom patterns inherit canonical default field names positionally
        # (1st pattern → "invoice_number", 2nd → "total").
        assert "invoice_number" in fields
        assert fields["invoice_number"] == "ABC99"
        assert "total" in fields
        assert "750" in fields["total"]

    def test_idp_extract_no_patterns(self) -> None:
        """doc_type='other' has no defaults → empty fields dict."""
        p = IDPPipelineProcessor(doc_type="other")
        ex = _make_exchange(b"Invoice #1 Total: $5")
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(p.process(ex, MagicMock()))
        finally:
            loop.close()
        assert ex.get_property("idp_extracted_fields") == {}

    def test_idp_extract_handles_bytes_body(self) -> None:
        p = IDPPipelineProcessor(doc_type="invoice")
        ex = _make_exchange(_INVOICE_BODY)
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(p.process(ex, MagicMock()))
        finally:
            loop.close()
        assert ex.get_property("idp_extracted_fields")  # non-empty

    def test_idp_extract_helper_direct(self) -> None:
        fields = extract_fields(_INVOICE_BODY.decode(), "invoice")
        assert "invoice_number" in fields
        assert fields["invoice_number"] == "12345"


# ─── Stage 4 — Validate ────────────────────────────────────────────────


class TestValidation:
    def test_idp_validate_high_confidence(self) -> None:
        """All 4 invoice default patterns match → confidence = 1.0."""
        p = IDPPipelineProcessor(doc_type="invoice")
        ex = _make_exchange(_INVOICE_BODY)
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(p.process(ex, MagicMock()))
        finally:
            loop.close()
        conf = ex.get_property("idp_confidence")
        assert conf == 1.0
        assert ex.get_property("idp_validation_errors") == []

    def test_idp_validate_low_confidence(self) -> None:
        """Body with only one matchable pattern → low confidence."""
        p = IDPPipelineProcessor(doc_type="invoice")
        # Only 'total' will match; others (invoice_number, date, vendor) won't.
        ex = _make_exchange(b"Total: $99.00 random text")
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(p.process(ex, MagicMock()))
        finally:
            loop.close()
        conf = ex.get_property("idp_confidence")
        assert 0.0 < conf < 0.5
        assert ex.get_property("needs_hitl") is True

    def test_idp_validation_errors_missing_fields(self) -> None:
        """Empty fields → 'no fields extracted' validation error."""
        p = IDPPipelineProcessor(doc_type="other")  # no default extractors
        ex = _make_exchange(b"")
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(p.process(ex, MagicMock()))
        finally:
            loop.close()
        errors = ex.get_property("idp_validation_errors")
        assert "no fields extracted" in errors

    def test_idp_validation_errors_total_not_positive(self) -> None:
        """Total=0 fails the total_positive validator."""
        p = IDPPipelineProcessor(doc_type="invoice")
        ex = _make_exchange(b"Invoice #1\nDate: 2026-01-01\nVendor: X\nTotal: $0.00")
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(p.process(ex, MagicMock()))
        finally:
            loop.close()
        # confidence is 1.0 (all 4 patterns match), but total=0 → validation
        # error → needs_hitl.
        errors = ex.get_property("idp_validation_errors")
        assert any("total" in e for e in errors)
        assert ex.get_property("needs_hitl") is True

    def test_idp_validation_unknown_validator(self) -> None:
        """Unknown validator name recorded as error."""
        result = IDPResult(doc_type="invoice", fields={"x": "1"})
        validate_result(result, "x", validators=["nonexistent_validator"])
        assert "unknown validator: nonexistent_validator" in result.validation_errors


# ─── Stage 5 — Route ───────────────────────────────────────────────────


class TestRouting:
    def test_idp_route_high_confidence(self) -> None:
        p = IDPPipelineProcessor(doc_type="invoice")
        ex = _make_exchange(_INVOICE_BODY)
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(p.process(ex, MagicMock()))
        finally:
            loop.close()
        assert ex.get_property("needs_hitl") is False
        assert ex.get_property("idp_auto_processed") is True

    def test_idp_route_low_confidence(self) -> None:
        p = IDPPipelineProcessor(doc_type="invoice")
        ex = _make_exchange(b"unrelated content")
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(p.process(ex, MagicMock()))
        finally:
            loop.close()
        assert ex.get_property("needs_hitl") is True
        assert ex.get_property("idp_auto_processed") is False

    def test_idp_threshold_configurable(self) -> None:
        """Custom threshold (0.3) accepts lower-confidence result."""
        # 2-of-4 patterns match → confidence 0.5; default threshold 0.8
        # would force HITL, but with threshold=0.3 it's auto-processed.
        p = IDPPipelineProcessor(doc_type="invoice", confidence_threshold=0.3)
        ex = _make_exchange(b"Invoice #42\nDate: 2026-03-03\nrandom text\nrandom text")
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(p.process(ex, MagicMock()))
        finally:
            loop.close()
        conf = ex.get_property("idp_confidence")
        assert conf == 0.5
        assert ex.get_property("needs_hitl") is False
        assert ex.get_property("idp_auto_processed") is True

    def test_idp_default_threshold(self) -> None:
        p = IDPPipelineProcessor()
        assert p._threshold == 0.8

    def test_idp_threshold_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="confidence_threshold"):
            IDPPipelineProcessor(confidence_threshold=1.5)
        with pytest.raises(ValueError, match="confidence_threshold"):
            IDPPipelineProcessor(confidence_threshold=-0.1)


# ─── Observability ─────────────────────────────────────────────────────


class TestObservability:
    def test_idp_state_observable(self) -> None:
        """exchange.properties has stage_reached, confidence, etc."""
        p = IDPPipelineProcessor(doc_type="invoice")
        ex = _make_exchange(_INVOICE_BODY)
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(p.process(ex, MagicMock()))
        finally:
            loop.close()
        assert ex.get_property("idp_stage_reached") == "route"
        assert ex.get_property("idp_confidence") == 1.0
        assert ex.get_property("idp_doc_type") == "invoice"
        assert ex.get_property("idp_validation_errors") == []
        assert ex.get_property("needs_hitl") is False
        assert ex.get_property("idp_result") is not None

    def test_idp_state_stage_progression(self) -> None:
        """Stage label is the final 'route' after all 5 stages."""
        p = IDPPipelineProcessor(doc_type="invoice")
        ex = _make_exchange(_INVOICE_BODY)
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(p.process(ex, MagicMock()))
        finally:
            loop.close()
        # Final stage is 'route' (Validate -> Route is the 5th stage).
        assert ex.get_property("idp_stage_reached") in {"validate", "route"}

    def test_idp_hitl_property_custom_name(self) -> None:
        """Custom hitl_property is honored."""
        p = IDPPipelineProcessor(doc_type="invoice", hitl_property="my_hitl_flag")
        ex = _make_exchange(_INVOICE_BODY)
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(p.process(ex, MagicMock()))
        finally:
            loop.close()
        assert ex.get_property("my_hitl_flag") is False
        # Default name NOT set.
        assert ex.get_property("needs_hitl") is None


# ─── Force / Idempotency / Defaults ────────────────────────────────────


class TestForceTypeAndIdempotency:
    def test_idp_force_type(self) -> None:
        """doc_type='invoice' forces invoice classification regardless of body."""
        p = IDPPipelineProcessor(doc_type="invoice")
        ex = _make_exchange(b"random text no invoice keywords here")
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(p.process(ex, MagicMock()))
        finally:
            loop.close()
        assert ex.get_property("idp_doc_type") == "invoice"

    def test_idp_force_type_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="doc_type"):
            IDPPipelineProcessor(doc_type="resume")

    def test_idp_idempotent(self) -> None:
        """Re-running the same processor on the same exchange yields same result."""
        p = IDPPipelineProcessor(doc_type="invoice")
        ex1 = _make_exchange(_INVOICE_BODY)
        ex2 = _make_exchange(_INVOICE_BODY)
        import asyncio

        loop = asyncio.new_event_loop()
        loop.run_until_complete(p.process(ex1, MagicMock()))
        loop.run_until_complete(p.process(ex2, MagicMock()))
        for key in (
            "idp_doc_type",
            "idp_confidence",
            "idp_extracted_fields",
            "idp_validation_errors",
            "needs_hitl",
            "idp_auto_processed",
        ):
            assert ex1.get_property(key) == ex2.get_property(key), key

    def test_idp_idempotent_under_rerun(self) -> None:
        """Running twice on the SAME exchange yields the same result."""
        p = IDPPipelineProcessor(doc_type="invoice")
        ex = _make_exchange(_INVOICE_BODY)
        import asyncio

        loop = asyncio.new_event_loop()
        loop.run_until_complete(p.process(ex, MagicMock()))
        first_conf = ex.get_property("idp_confidence")
        first_doc = ex.get_property("idp_doc_type")
        # Re-run.
        loop.run_until_complete(p.process(ex, MagicMock()))
        assert ex.get_property("idp_confidence") == first_conf
        assert ex.get_property("idp_doc_type") == first_doc


# ─── to_spec / serialization ───────────────────────────────────────────


class TestSpec:
    def test_idp_to_spec(self) -> None:
        p = IDPPipelineProcessor(
            doc_type="invoice",
            confidence_threshold=0.5,
            extractors={"invoice": [r"Invoice\s*#?\s*(\d+)"]},
            validators=["required_fields"],
        )
        spec = p.to_spec()
        assert spec is not None
        assert "idp_pipeline" in spec
        inner = spec["idp_pipeline"]
        assert inner["doc_type"] == "invoice"
        assert inner["confidence_threshold"] == 0.5
        assert inner["extractors"] == {"invoice": [r"Invoice\s*#?\s*(\d+)"]}
        assert inner["validators"] == ["required_fields"]

    def test_idp_to_spec_defaults(self) -> None:
        p = IDPPipelineProcessor()
        spec = p.to_spec()
        assert spec is not None
        assert spec["idp_pipeline"]["doc_type"] == "auto"
        assert spec["idp_pipeline"]["confidence_threshold"] == 0.8
        assert spec["idp_pipeline"]["extractors"] is None
        assert spec["idp_pipeline"]["validators"] is None

    def test_idp_to_spec_result_property(self) -> None:
        p = IDPPipelineProcessor(result_property="custom_result_key")
        spec = p.to_spec()
        assert spec["idp_pipeline"]["result_property"] == "custom_result_key"


# ─── Defaults & constants ──────────────────────────────────────────────


class TestDefaults:
    def test_idp_default_extractors_invoice(self) -> None:
        assert "invoice" in DEFAULT_EXTRACTORS
        assert len(DEFAULT_EXTRACTORS["invoice"]) >= 3

    def test_idp_default_extractors_contract(self) -> None:
        assert "contract" in DEFAULT_EXTRACTORS
        assert any("party" in p.lower() for p in DEFAULT_EXTRACTORS["contract"])

    def test_idp_default_extractors_receipt(self) -> None:
        assert "receipt" in DEFAULT_EXTRACTORS
        assert any("subtotal" in p.lower() for p in DEFAULT_EXTRACTORS["receipt"])
