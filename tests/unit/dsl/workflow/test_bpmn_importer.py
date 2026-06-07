"""Тесты BPMN 2.0 импортёра (Sprint 4 Wave B)."""
# ruff: noqa: S101

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.backend.dsl.workflow.bpmn_importer import (
    BpmnImportDisabledError,
    BpmnImportError,
    import_bpmn,
)
from src.backend.dsl.workflow.spec import ActivityDeclaration, WorkflowDeclaration

_CREDIT_SCORING_PATH = (
    Path(__file__).resolve().parents[4] / "docs" / "bpmn" / "credit_scoring_sample.bpmn"
)


def _make_bpmn(*, body: str, process_id: str = "p1") -> str:
    """Сконструировать минимальный BPMN-XML с заданным body."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">\n'
        f'  <bpmn:process id="{process_id}" isExecutable="true">\n'
        f"    {body}\n"
        "  </bpmn:process>\n"
        "</bpmn:definitions>\n"
    )


def test_import_bpmn_sample_credit_scoring() -> None:
    """Sample credit_scoring.bpmn парсится корректно: 2 task + 1 gateway + 2 ветки."""
    xml = _CREDIT_SCORING_PATH.read_text(encoding="utf-8")
    decl = import_bpmn(xml, check_feature_flag=False)

    assert isinstance(decl, WorkflowDeclaration)
    assert decl.name == "credit_scoring"
    # 2 serviceTask до gateway + gateway-маркер + 2 serviceTask после gateway = 5 steps
    activity_names = [s.name for s in decl.steps if isinstance(s, ActivityDeclaration)]
    assert "validate_input" in activity_names
    assert "fetch_credit_bureau" in activity_names
    assert any(n.startswith("__gateway__") for n in activity_names)


def test_xor_gateway_maps_to_xor_kind() -> None:
    """exclusiveGateway → kind="xor" в args["gateway"]."""
    xml = _make_bpmn(
        body="""
        <bpmn:startEvent id="s"/>
        <bpmn:exclusiveGateway id="gw"/>
        <bpmn:serviceTask id="t1" name="branch_a"/>
        <bpmn:serviceTask id="t2" name="branch_b"/>
        <bpmn:endEvent id="e"/>
        <bpmn:sequenceFlow id="f1" sourceRef="s" targetRef="gw"/>
        <bpmn:sequenceFlow id="f2" sourceRef="gw" targetRef="t1"/>
        <bpmn:sequenceFlow id="f3" sourceRef="gw" targetRef="t2"/>
        <bpmn:sequenceFlow id="f4" sourceRef="t1" targetRef="e"/>
        <bpmn:sequenceFlow id="f5" sourceRef="t2" targetRef="e"/>
        """
    )
    decl = import_bpmn(xml, check_feature_flag=False)
    gateway_step = next(
        s
        for s in decl.steps
        if s.name.startswith("__gateway__")  # type: ignore[union-attr]
    )
    assert isinstance(gateway_step, ActivityDeclaration)
    assert gateway_step.args["gateway"]["kind"] == "xor"
    assert len(gateway_step.args["gateway"]["branches"]) == 2


def test_parallel_gateway_maps_to_and() -> None:
    """parallelGateway → kind="and"."""
    xml = _make_bpmn(
        body="""
        <bpmn:startEvent id="s"/>
        <bpmn:parallelGateway id="gw"/>
        <bpmn:serviceTask id="t1" name="a"/>
        <bpmn:endEvent id="e"/>
        <bpmn:sequenceFlow id="f1" sourceRef="s" targetRef="gw"/>
        <bpmn:sequenceFlow id="f2" sourceRef="gw" targetRef="t1"/>
        <bpmn:sequenceFlow id="f3" sourceRef="t1" targetRef="e"/>
        """
    )
    decl = import_bpmn(xml, check_feature_flag=False)
    gateway_step = next(
        s
        for s in decl.steps
        if s.name.startswith("__gateway__")  # type: ignore[union-attr]
    )
    assert gateway_step.args["gateway"]["kind"] == "and"  # type: ignore[union-attr]


def test_inclusive_gateway_maps_to_or() -> None:
    """inclusiveGateway → kind="or"."""
    xml = _make_bpmn(
        body="""
        <bpmn:startEvent id="s"/>
        <bpmn:inclusiveGateway id="gw"/>
        <bpmn:serviceTask id="t1" name="a"/>
        <bpmn:endEvent id="e"/>
        <bpmn:sequenceFlow id="f1" sourceRef="s" targetRef="gw"/>
        <bpmn:sequenceFlow id="f2" sourceRef="gw" targetRef="t1"/>
        <bpmn:sequenceFlow id="f3" sourceRef="t1" targetRef="e"/>
        """
    )
    decl = import_bpmn(xml, check_feature_flag=False)
    gateway_step = next(
        s
        for s in decl.steps
        if s.name.startswith("__gateway__")  # type: ignore[union-attr]
    )
    assert gateway_step.args["gateway"]["kind"] == "or"  # type: ignore[union-attr]


def test_invalid_xml_raises() -> None:
    """Невалидный XML → BpmnImportError."""
    with pytest.raises(BpmnImportError, match="Невалидный BPMN XML"):
        import_bpmn("<not><xml", check_feature_flag=False)


def test_missing_process_raises() -> None:
    """BPMN без <bpmn:process> → BpmnImportError."""
    xml = (
        '<?xml version="1.0"?>'
        '<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"/>'
    )
    with pytest.raises(BpmnImportError, match="bpmn:process"):
        import_bpmn(xml, check_feature_flag=False)


def test_import_disabled_when_feature_off() -> None:
    """При выключенном feature-flag (default-OFF) — BpmnImportDisabledError."""
    xml = _make_bpmn(
        body="""
        <bpmn:startEvent id="s"/>
        <bpmn:serviceTask id="t" name="x"/>
        <bpmn:endEvent id="e"/>
        <bpmn:sequenceFlow id="f1" sourceRef="s" targetRef="t"/>
        <bpmn:sequenceFlow id="f2" sourceRef="t" targetRef="e"/>
        """
    )
    with (
        patch(
            "src.backend.core.config.features.feature_flags.workflow_bpmn_import", False
        ),
        pytest.raises(BpmnImportDisabledError),
    ):
        import_bpmn(xml)


def test_name_override_applied() -> None:
    """name=... override-ит default name из <bpmn:process>."""
    xml = _make_bpmn(
        body="""
        <bpmn:startEvent id="s"/>
        <bpmn:serviceTask id="t" name="x"/>
        <bpmn:endEvent id="e"/>
        <bpmn:sequenceFlow id="f1" sourceRef="s" targetRef="t"/>
        <bpmn:sequenceFlow id="f2" sourceRef="t" targetRef="e"/>
        """,
        process_id="original_name",
    )
    decl = import_bpmn(xml, name="custom_name", check_feature_flag=False)
    assert decl.name == "custom_name"
