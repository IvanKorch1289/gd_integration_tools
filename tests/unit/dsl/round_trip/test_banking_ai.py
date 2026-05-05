"""W29 — Round-trip тесты для ai_banking процессоров (AI pipelines).

Покрывает primitive-args batch (7 процессоров):

* ai_banking.py: kyc_aml_verify / antifraud_score / credit_scoring_rag /
  customer_chatbot / appeal_ai / tx_categorize / findoc_ocr_llm.

Все builder-методы существовали до W29 — добавлен только ``to_spec()``.

Note: специализированные финансовые протоколы (SWIFT MT/MX, ISO 20022,
FIX, EDIFACT) и интеграции с проприетарными ERP/CRM (1С) удалены —
маршрутизируются через корпоративную интеграционную шину.
"""

# ruff: noqa: S101

from __future__ import annotations

import pytest
import yaml

from src.backend.dsl.builder import RouteBuilder
from src.backend.dsl.yaml_loader import load_pipeline_from_yaml


def _round_trip(builder: RouteBuilder) -> tuple[dict, dict]:
    pipeline = builder.build()
    dump = pipeline.to_dict()
    yaml_str = yaml.safe_dump(dump, sort_keys=False, allow_unicode=True)
    rebuilt = load_pipeline_from_yaml(yaml_str)
    return dump, rebuilt.to_dict()


@pytest.mark.parametrize(
    "method,kwargs",
    [
        # ── ai_banking.py ──
        ("kyc_aml_verify", {}),
        ("kyc_aml_verify", {"jurisdiction": "kz"}),
        ("antifraud_score", {}),
        ("antifraud_score", {"model": "gpt-4o"}),
        ("credit_scoring_rag", {}),
        ("credit_scoring_rag", {"product": "mortgage"}),
        ("customer_chatbot", {}),
        ("customer_chatbot", {"channel": "telegram"}),
        ("appeal_ai", {}),
        ("tx_categorize", {}),
        ("tx_categorize", {"taxonomy": "internal_v2"}),
        ("findoc_ocr_llm", {}),
        ("findoc_ocr_llm", {"doc_type": "contract"}),
    ],
)
def test_w29_processor_round_trip(method: str, kwargs: dict) -> None:
    """Single-processor round-trip: builder → YAML → builder."""
    builder = RouteBuilder.from_(f"rt.w29.{method}", source="test:rt.w29")
    getattr(builder, method)(**kwargs)
    original, rebuilt = _round_trip(builder)
    assert original == rebuilt, (
        f"Round-trip mismatch for {method}({kwargs}): {original} != {rebuilt}"
    )


def test_w29_ai_banking_pipeline_full_chain() -> None:
    """Реалистичный AI-banking pipeline: KYC → антифрод → кредит-скоринг."""
    builder = (
        RouteBuilder.from_("rt.w29.aibank", source="test:rt.w29.aibank")
        .kyc_aml_verify(jurisdiction="ru")
        .antifraud_score(model="default")
        .credit_scoring_rag(product="retail")
        .customer_chatbot(channel="web")
    )
    original, rebuilt = _round_trip(builder)
    assert original == rebuilt
    methods = [next(iter(p)) for p in original["processors"]]
    assert methods == [
        "kyc_aml_verify",
        "antifraud_score",
        "credit_scoring_rag",
        "customer_chatbot",
    ]


def test_appeal_ai_no_args() -> None:
    """``appeal_ai()`` — empty params dict."""
    builder = RouteBuilder.from_("rt.appeal", source="test:rt").appeal_ai()
    spec = builder.build().to_dict()
    assert spec["processors"][0] == {"appeal_ai": {}}
