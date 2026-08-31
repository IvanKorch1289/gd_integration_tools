# ruff: noqa: S101
"""Smoke-тест YAML workflow credit_assessment (Sprint 7 Team T3).

Wave: ``[wave:s7/team-03-credit-1st-client]``.

Тест проверяет наличие YAML, корректность парсинга, обязательные секции
(steps[] per B-101 schema fix) и правильность wave-связки.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import yaml

_WORKFLOW_PATH = (
    Path(__file__).resolve().parents[1]
    / "workflows"
    / "credit_assessment.workflow.yaml"
)


def _load_workflow() -> dict[str, object]:
    """Читает и парсит workflow YAML (singleton-обёртка для тестов)."""
    return yaml.safe_load(_WORKFLOW_PATH.read_text(encoding="utf-8"))


def test_workflow_yaml_exists_and_parses() -> None:
    """YAML существует и парсится."""
    assert _WORKFLOW_PATH.exists()
    data = _load_workflow()
    assert data["name"] == "credit_assessment"
    assert data["version"] == "1.0"


def test_workflow_has_required_steps_section() -> None:
    """steps[] — обязательная секция (B-101 schema fix).

    Раньше (pre-B-101) workflow имел activities/compensation top-level keys.
    После B-101 schema unified с остальным DSL — только steps[].
    """
    data = _load_workflow()
    assert "steps" in data
    assert isinstance(data["steps"], list)
    assert len(data["steps"]) >= 1, "workflow должен иметь хотя бы 1 step"


def test_workflow_steps_include_activity_and_normalize() -> None:
    """Steps содержат activity (SKB fetch) и normalize (apply_rules)."""
    data = _load_workflow()
    activities = [s for s in data["steps"] if s.get("type") == "activity"]
    assert len(activities) >= 1, "должен быть как минимум один activity step"

    function_refs = [a.get("name") for a in activities]
    has_skb = any("skb:fetch_result" in (r or "") for r in function_refs)
    has_normalize = any("normalize:apply_rules" in (r or "") for r in function_refs)
    assert has_skb, "должен быть step с extensions.credit_pipeline.services.clients.skb:fetch_result"
    assert has_normalize, "должен быть step с extensions.credit_pipeline.functions.normalize:apply_rules"


# B-101 fix (cycle 1): regression test — все ``name:`` ссылки в
# activity steps должны резолвиться в module-level callable. Раньше
# ``extensions.credit_pipeline.services.clients.skb:get_result`` указывал
# на метод класса ``CreditSKBClient`` (не виден через ``getattr(module, ...)``)
# → workflow валился при первом ``call_function`` в runtime.
def test_workflow_activity_function_refs_resolve_to_module_callables() -> None:
    """Каждый ``name:`` в activity steps — реальный module-level callable.

    Контракт ``call_function`` (R-V15-6)::

        module = importlib.import_module(module_name)
        fn = getattr(module, fn_name)
        if fn is None or not callable(fn): raise PermissionError(...)
        result = fn(payload)

    Соответственно, ``fn`` обязан быть атрибутом *модуля*, а не класса.
    Метод класса через ``getattr(module, name)`` НЕ доступен → runtime-broken.
    """
    data = _load_workflow()
    activities = [s for s in data["steps"] if s.get("type") == "activity"]
    assert activities, "workflow должен содержать хотя бы одну activity"

    broken: list[str] = []
    for activity in activities:
        ref = activity.get("name")
        if not isinstance(ref, str) or ":" not in ref:
            continue
        module_name, fn_name = ref.split(":", 1)
        try:
            module = importlib.import_module(module_name)
        except ImportError as exc:
            broken.append(f"{activity.get('name')!r}: cannot import {module_name!r}: {exc}")
            continue
        fn = getattr(module, fn_name, None)
        if fn is None or not callable(fn):
            broken.append(
                f"{ref!r} → module attribute missing or not callable "
                f"(метод класса или опечатка)"
            )

    assert not broken, (
        "Broken call_function refs в credit_assessment.workflow.yaml:\n  - "
        + "\n  - ".join(broken)
    )


def test_workflow_skb_fetch_result_wrapper_exists() -> None:
    """``skb.fetch_result`` существует как module-level callable.

    Явный regression-тест на B-101: подтверждает наличие module-level
    wrapper'а, добавленного для исправления broken ref.
    """
    import extensions.credit_pipeline.services.clients.skb as skb_module

    assert hasattr(skb_module, "fetch_result")
    assert callable(skb_module.fetch_result)
    assert "fetch_result" in skb_module.__all__
