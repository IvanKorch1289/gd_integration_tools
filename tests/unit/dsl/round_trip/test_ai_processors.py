"""W27 — Round-trip тесты для AI-процессоров.

Покрывает primitive-args batch:
``sanitize_pii`` / ``rag_search`` / ``compose_prompt`` / ``call_llm``.

Контракт ``to_spec`` для AI-процессоров: сериализуются только те kwargs,
что приняты публичным builder-методом. Не-builder-параметры (``output_property``,
``prompt_property``, ``max_retries``, ``retry_delay``) при round-trip
не сохраняются — by design (см. ``docs/reference/dsl/to_spec_audit.md``).
"""

# ruff: noqa: S101

from __future__ import annotations

import pytest
import yaml

from src.dsl.builder import RouteBuilder
from src.dsl.yaml_loader import load_pipeline_from_yaml


def _round_trip(builder: RouteBuilder) -> tuple[dict, dict]:
    pipeline = builder.build()
    dump = pipeline.to_dict()
    yaml_str = yaml.safe_dump(dump, sort_keys=False, allow_unicode=True)
    rebuilt = load_pipeline_from_yaml(yaml_str)
    return dump, rebuilt.to_dict()


@pytest.mark.parametrize(
    "method,kwargs",
    [
        ("sanitize_pii", {}),
        ("rag_search", {}),
        ("rag_search", {"query_field": "user_question", "top_k": 3}),
        ("rag_search", {"namespace": "kb_main"}),
        ("rag_search", {"query_field": "q", "top_k": 10, "namespace": "ns"}),
        ("compose_prompt", {"template": "Q: {input}\nCtx: {context}"}),
        ("compose_prompt", {"template": "T: {input}", "context_property": "rag_hits"}),
        ("call_llm", {}),
        ("call_llm", {"provider": "perplexity"}),
        ("call_llm", {"model": "gpt-4"}),
        ("call_llm", {"provider": "openai", "model": "gpt-4o"}),
    ],
)
def test_ai_processor_round_trip(method: str, kwargs: dict) -> None:
    """Single-processor round-trip: builder → YAML → builder, идентичный to_dict."""
    builder = RouteBuilder.from_(f"rt.ai.{method}", source="test:rt.ai")
    getattr(builder, method)(**kwargs)
    original, rebuilt = _round_trip(builder)
    assert original == rebuilt, (
        f"Round-trip mismatch for {method}({kwargs}): {original} != {rebuilt}"
    )


def test_ai_pipeline_round_trip_full_chain() -> None:
    """Реалистичная RAG-цепочка: sanitize → rag → compose → llm.

    Порядок sanitize_pii перед call_llm соответствует политике линтера
    (``src/dsl/engine/validation.py`` запрещает обратный порядок).
    """
    builder = (
        RouteBuilder.from_("rt.ai.full", source="test:rt.ai.full", description="full")
        .sanitize_pii()
        .rag_search(query_field="question", top_k=5, namespace="kb")
        .compose_prompt(template="Контекст:\n{context}\n\nВопрос: {input}")
        .call_llm(provider="perplexity", model="default")
    )
    original, rebuilt = _round_trip(builder)
    assert original == rebuilt
    methods = [next(iter(p)) for p in original["processors"]]
    assert methods == ["sanitize_pii", "rag_search", "compose_prompt", "call_llm"]


def test_compose_prompt_default_context_property_omitted() -> None:
    """Default ``context_property='vector_results'`` не пишется в spec."""
    builder = RouteBuilder.from_("rt.ai.cp", source="test:rt").compose_prompt(
        template="T: {input}"
    )
    spec = builder.build().to_dict()
    proc = spec["processors"][0]
    assert proc == {"compose_prompt": {"template": "T: {input}"}}


def test_rag_search_defaults_omitted() -> None:
    """Все default-значения опускаются — пустой kwargs."""
    builder = RouteBuilder.from_("rt.ai.rag", source="test:rt").rag_search()
    spec = builder.build().to_dict()
    proc = spec["processors"][0]
    assert proc == {"rag_search": {}}


def test_call_llm_no_args_round_trip() -> None:
    """``call_llm()`` без provider/model — пустой kwargs в spec."""
    builder = RouteBuilder.from_("rt.ai.llm", source="test:rt").call_llm()
    spec = builder.build().to_dict()
    proc = spec["processors"][0]
    assert proc == {"call_llm": {}}


def test_sanitize_pii_no_args() -> None:
    """``sanitize_pii()`` — empty params dict."""
    builder = RouteBuilder.from_("rt.ai.s", source="test:rt").sanitize_pii()
    spec = builder.build().to_dict()
    proc = spec["processors"][0]
    assert proc == {"sanitize_pii": {}}
