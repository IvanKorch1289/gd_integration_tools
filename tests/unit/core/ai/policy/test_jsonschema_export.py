"""Unit-тесты для core/ai/policy/jsonschema_export.py (cycle 33 L4 cycle 1).

Модуль предоставляет 3 функции для external consumers (admin UI,
MCP docs, IDE autocomplete, config validators):

* :func:`export_aipolicy_json_schema` — JSON-Schema export
* :func:`validate_aipolicy_dict` — dict validation against schema
* :func:`export_default_policy_yaml` — example YAML

Используется вне проекта (admin tools, MCP gateway) — критично
для backward-compatibility и consistency.
"""


from __future__ import annotations

import pytest
import yaml
from pydantic import ValidationError

from src.backend.core.ai.policy.jsonschema_export import (
    export_aipolicy_json_schema,
    export_default_policy_yaml,
    validate_aipolicy_dict,
)


def test_export_aipolicy_json_schema_returns_dict() -> None:
    """Schema export возвращает non-empty dict с required type='object'."""
    schema = export_aipolicy_json_schema()

    assert isinstance(schema, dict)
    assert schema, "schema dict не должен быть пустым"
    assert schema.get("type") == "object"
    assert "properties" in schema


def test_export_aipolicy_json_schema_includes_required_fields() -> None:
    """Schema содержит все required fields из AIPolicySpec."""
    schema = export_aipolicy_json_schema()

    required = schema.get("required", [])
    # AIPolicySpec требует минимум name, workflow_pattern, model_router.
    assert "name" in required
    assert "workflow_pattern" in required
    assert "model_router" in required


def test_export_aipolicy_json_schema_does_not_change_between_calls() -> None:
    """Schema export — детерминированный (cacheable)."""
    s1 = export_aipolicy_json_schema()
    s2 = export_aipolicy_json_schema()
    assert s1 == s2


def test_validate_aipolicy_dict_accepts_valid_dict() -> None:
    """Valid dict проходит validation и возвращает AIPolicySpec instance."""
    data = {
        "name": "test_policy",
        "version": 1,
        "workflow_pattern": "test_*",
        "tenant_pattern": "*",
        "model_router": {
            "primary": "openai/gpt-4o-mini",
            "fallback": [],
            "timeout_s": 30.0,
            "retry_attempts": 2,
        },
    }
    spec = validate_aipolicy_dict(data)
    assert spec.name == "test_policy"
    assert spec.workflow_pattern == "test_*"


def test_validate_aipolicy_dict_rejects_missing_required_fields() -> None:
    """Dict без обязательных полей → ValidationError."""
    data = {"name": "incomplete"}  # нет workflow_pattern и model_router

    with pytest.raises(ValidationError):
        validate_aipolicy_dict(data)


def test_validate_aipolicy_dict_rejects_invalid_type() -> None:
    """Dict с wrong-typed field → ValidationError."""
    data = {
        "name": "test",
        "workflow_pattern": "test_*",
        "model_router": {
            "primary": "openai/gpt-4o-mini",
            "timeout_s": "not-a-float",  # wrong type
        },
    }
    with pytest.raises(ValidationError):
        validate_aipolicy_dict(data)


def test_export_default_policy_yaml_is_valid_yaml() -> None:
    """export_default_policy_yaml возвращает valid YAML, parseable через yaml.safe_load."""
    yaml_str = export_default_policy_yaml()
    parsed = yaml.safe_load(yaml_str)

    assert isinstance(parsed, dict)
    assert "name" in parsed
    assert "workflow_pattern" in parsed
    assert "model_router" in parsed


def test_export_default_policy_yaml_validates_against_schema() -> None:
    """export_default_policy_yaml output passes validate_aipolicy_dict.

    Round-trip: YAML → parse → validate (как будет делать admin
    при импорте starter template).
    """
    yaml_str = export_default_policy_yaml()
    data = yaml.safe_load(yaml_str)
    # Должен проходить без ошибок.
    spec = validate_aipolicy_dict(data)
    assert spec.name == data["name"]


def test_export_default_policy_yaml_has_strict_defaults() -> None:
    """Default policy — strict (tools.on_violation=fail, required=True)."""
    yaml_str = export_default_policy_yaml()
    data = yaml.safe_load(yaml_str)

    # S209 fail-closed: default tools.on_violation = fail
    # (S176: пустые whitelist+blacklist + fail = strict policy)
    assert data.get("tools", {}).get("on_violation") == "fail"
    # required=True — policy обязателен к применению.
    assert data.get("required") is True
