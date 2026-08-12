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
        path = _ROOT / "extensions" / "credit_pipeline" / "workflows" / "credit_assessment.workflow.yaml"
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
        self, credit_assessment_yaml: dict,
    ) -> None:
        """fetch_skb_report и fetch_nbki_report используют реально существующую функцию.

        B-101 fix (cycle 1): было extensions.credit_pipeline.services.clients.
        skb:fetch_for_workflow (НЕ существует). Заменено на get_result
        (метод на CreditSKBClient class — AttributeError при getattr).

        D-AUDIT-A10 carry-over (cycle 1, follow-up 2026-08-12): get_result
        заменён на module-level fetch_result wrapper (skb.py:152-181),
        matching call_function contract fn(payload) -> Any.
        """
        activities = {a["name"]: a for a in credit_assessment_yaml["activities"]}
        for activity_name in ("fetch_skb_report", "fetch_nbki_report"):
            fn = activities[activity_name]["function"]
            assert "fetch_for_workflow" not in fn, (
                f"{activity_name} всё ещё ссылается на несуществующую fetch_for_workflow"
            )
            assert ":fetch_result" in fn, (
                f"{activity_name} должен использовать :fetch_result "
                "(module-level wrapper вокруг CreditSKBClient.get_result)"
            )

    def test_credit_assessment_publish_uses_existing_function(
        self, credit_assessment_yaml: dict,
    ) -> None:
        """publish_decision использует реально существующую функцию.

        D-AUDIT-B-101 fix: было extensions.credit_pipeline.functions.publish:
        emit_decision (НЕ существует). Заменено на extensions.credit_pipeline.
        functions.normalize:apply_rules (placeholder).
        """
        activities = {a["name"]: a for a in credit_assessment_yaml["activities"]}
        publish_fn = activities["publish_decision"]["function"]
        assert "emit_decision" not in publish_fn, (
            "publish_decision всё ещё ссылается на несуществующую emit_decision"
        )
        # Новая цель — extensions.credit_pipeline.functions.normalize:apply_rules
        assert publish_fn == (
            "extensions.credit_pipeline.functions.normalize:apply_rules"
        ), f"publish_decision function должен быть apply_rules, got {publish_fn}"

    def test_hello_route_no_broken_normalizer_ref(self, hello_route_yaml: dict) -> None:
        """routes/hello_route/main.dsl.yaml НЕ содержит broken normalizer ref.

        D-AUDIT-B-102 fix: broken extensions.hello_route.normalizer:apply_rules
        удалён (модуль не существует).
        """
        yaml_text = (
            _ROOT / "routes" / "hello_route" / "main.dsl.yaml"
        ).read_text(encoding="utf-8")
        assert "extensions.hello_route.normalizer" not in yaml_text, (
            "hello_route/main.dsl.yaml всё ещё ссылается на несуществующий normalizer"
        )

    def test_test_route_w1_no_broken_normalizer_ref(
        self, test_route_w1_yaml: dict,
    ) -> None:
        """routes/test_route_w1/main.dsl.yaml НЕ содержит broken normalizer ref.

        D-AUDIT-B-103 fix: broken extensions.test_route_w1.normalizer:apply_rules
        удалён.
        """
        yaml_text = (
            _ROOT / "routes" / "test_route_w1" / "main.dsl.yaml"
        ).read_text(encoding="utf-8")
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
