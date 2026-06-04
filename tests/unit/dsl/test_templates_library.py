"""Tests for dsl/templates_library.py."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.backend.dsl.templates_library import TemplateInfo, list_templates, templates


@pytest.fixture(autouse=True)
def _disable_action_validation():
    with patch("src.backend.dsl.builders.base.RouteBuilder._validate_action_names"):
        yield


class TestTemplates:
    def test_not_empty(self) -> None:
        assert len(templates) > 0

    def test_template_info(self) -> None:
        for key, t in templates.items():
            assert isinstance(t, TemplateInfo)
            assert t.name
            assert callable(t.builder)

    def test_list_templates(self) -> None:
        items = list_templates()
        assert len(items) == len(templates)
        assert items[0]["id"] in templates
        assert "name" in items[0]
        assert "description" in items[0]
        assert "parameters" in items[0]

    def test_notify_on_event_builder(self) -> None:
        t = templates["notify.on_event"]
        pipeline = t.builder("queue:orders", "admin@example.com", "New order")
        assert pipeline.route_id == "notify.event"

    def test_safe_external_call_builder(self) -> None:
        t = templates["safe.external_call"]
        pipeline = t.builder("external.api.call", max_retries=5, dlq=False)
        assert pipeline.route_id == "safe.external.api.call"

    def test_ai_qa_with_rag_builder(self) -> None:
        t = templates["ai.qa_with_rag"]
        pipeline = t.builder(question_field="q", top_k=3, provider="openai")
        assert pipeline.route_id == "ai.qa_rag"
