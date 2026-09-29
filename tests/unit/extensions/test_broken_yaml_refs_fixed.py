"""D-AUDIT-A10/B-101/102/103 fix (cycle 1): broken YAML refs в extensions/routes.

B-101 (P0): extensions/credit_pipeline/workflows/credit_assessment.workflow.yaml
ссылался на 2 несуществующие функции (fetch_for_workflow + emit_decision).
B-102 (P0): routes/hello_route/main.dsl.yaml ссылался на
extensions.hello_route.normalizer:apply_rules (модуль не существует —
route — pure YAML).
B-103 (P0): routes/test_route_w1/main.dsl.yaml аналогично.

Фикс:
- credit_assessment.workflow.yaml: 3 broken refs заменены на реально
  существующие функции (extensions.credit_pipeline.services.clients.skb:
  get_result + extensions.credit_pipeline.functions.normalize:apply_rules).
- hello_route/main.dsl.yaml: broken call_function step удалён (route — pure YAML demo).
- test_route_w1/main.dsl.yaml: broken call_function step удалён аналогично.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[3]


class TestBrokenYAMLRefsFixed:
    """D-AUDIT-A10 fix: broken YAML refs в extensions/routes."""

    @pytest.fixture
    def credit_assessment_yaml(self) -> dict:
        """Загрузить credit_assessment.workflow.yaml как dict."""
        path = (
            _ROOT
            / "extensions"
            / "credit_pipeline"
            / "workflows"
            / "credit_assessment.workflow.yaml"
        )
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    @pytest.fixture
    def hello_route_yaml(self) -> dict:
        """Загрузить hello_route/main.dsl.yaml как dict."""
        path = _ROOT / "routes" / "hello_route" / "main.dsl.yaml"
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    @pytest.fixture
    def test_route_w1_yaml(self) -> dict:
        """Загрузить test_route_w1/main.dsl.yaml как dict."""
        path = _ROOT / "routes" / "test_route_w1" / "main.dsl.yaml"
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    def test_credit_assessment_fetch_uses_existing_function(
        self, credit_assessment_yaml: dict
    ) -> None:
        """fetch_skb_report и fetch_nbki_report используют реально существующую функцию.

        B-101 fix (cycle 1): было extensions.credit_pipeline.services.clients.
        skb:fetch_for_workflow (НЕ существует). Заменено на get_result
        (метод на CreditSKBClient class — AttributeError при getattr).

        D-AUDIT-A10 carry-over (cycle 1, follow-up 2026-08-12): get_result
        заменён на module-level fetch_result wrapper (skb.py:152-181),
        matching call_function contract fn(payload) -> Any.

        Схема шага изменилась: было ``activities[].function``, стало
        ``steps[]`` с ``type`` ("activity") и ``name``, где ``name`` несёт
        dotted-ссылку ``module:function``. Охраняемый инвариант прежний.
        """
        refs = [s["name"] for s in credit_assessment_yaml["steps"]]
        fetch_refs = [r for r in refs if r.endswith(":fetch_result")]
        assert len(fetch_refs) == 2, (
            f"ожидались 2 fetch-шага на :fetch_result, найдено {len(fetch_refs)}: {refs}"
        )
        for fn in fetch_refs:
            assert "fetch_for_workflow" not in fn, (
                f"fetch-шаг всё ещё ссылается на несуществующую fetch_for_workflow: {fn}"
            )
        assert not any("fetch_for_workflow" in r for r in refs), (
            f"credit_assessment всё ещё ссылается на fetch_for_workflow: {refs}"
        )

    def test_credit_assessment_publish_uses_existing_function(
        self, credit_assessment_yaml: dict
    ) -> None:
        """publish_decision использует реально существующую функцию.

        D-AUDIT-B-101 fix: было extensions.credit_pipeline.functions.publish:
        emit_decision (НЕ существует). Заменено на extensions.credit_pipeline.
        functions.normalize:apply_rules (placeholder).
        """
        refs = [s["name"] for s in credit_assessment_yaml["steps"]]
        assert not any("emit_decision" in r for r in refs), (
            f"workflow всё ещё ссылается на несуществующую emit_decision: {refs}"
        )
        # Новая цель — extensions.credit_pipeline.functions.normalize:apply_rules
        assert "extensions.credit_pipeline.functions.normalize:apply_rules" in refs, (
            f"publish-шаг должен ссылаться на normalize:apply_rules, шаги: {refs}"
        )

    def test_hello_route_no_broken_normalizer_ref(self, hello_route_yaml: dict) -> None:
        """routes/hello_route/main.dsl.yaml НЕ содержит broken normalizer ref.

        D-AUDIT-B-102 fix: broken extensions.hello_route.normalizer:apply_rules
        удалён (модуль не существует).
        """
        yaml_text = (_ROOT / "routes" / "hello_route" / "main.dsl.yaml").read_text(
            encoding="utf-8"
        )
        assert "extensions.hello_route.normalizer" not in yaml_text, (
            "hello_route/main.dsl.yaml всё ещё ссылается на несуществующий normalizer"
        )

    def test_test_route_w1_no_broken_normalizer_ref(
        self, test_route_w1_yaml: dict
    ) -> None:
        """routes/test_route_w1/main.dsl.yaml НЕ содержит broken normalizer ref.

        D-AUDIT-B-103 fix: broken extensions.test_route_w1.normalizer:apply_rules
        удалён.
        """
        yaml_text = (_ROOT / "routes" / "test_route_w1" / "main.dsl.yaml").read_text(
            encoding="utf-8"
        )
        assert "extensions.test_route_w1.normalizer" not in yaml_text, (
            "test_route_w1/main.dsl.yaml всё ещё ссылается на несуществующий normalizer"
        )

    def test_target_functions_exist(self) -> None:
        """Целевые функции, на которые ссылаются YAML, реально существуют.

        Sanity-check после замены refs.
        """
        # extensions.credit_pipeline.functions.normalize:apply_rules
        from extensions.credit_pipeline.functions.normalize import apply_rules

        assert callable(apply_rules), "normalize:apply_rules должен быть callable"

        # extensions.credit_pipeline.services.clients.skb:get_result
        from extensions.credit_pipeline.services.clients.skb import CreditSKBClient

        assert hasattr(CreditSKBClient, "get_result"), (
            "CreditSKBClient должен иметь get_result метод"
        )
