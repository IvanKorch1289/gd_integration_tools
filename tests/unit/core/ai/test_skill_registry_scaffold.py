"""Smoke-тесты scaffold :class:`SkillRegistry` V11.2 (Sprint 26 W5, ADR-NEW-22).

Проверяют:

* SkillSpec Pydantic v2 валидация;
* SkillRegistry empty по умолчанию;
* scaffold-методы поднимают ``NotImplementedError``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.backend.core.ai.skill_registry import SkillRegistry, SkillSpec


def test_minimal_skill_spec() -> None:
    """SkillSpec с минимальными required полями валиден."""
    spec = SkillSpec(
        id="credit.score.calculate",
        version="1.2.0",
        handler="extensions.credit.functions.score:calculate",
    )
    assert spec.id == "credit.score.calculate"
    assert spec.version == "1.2.0"
    assert spec.handler == "extensions.credit.functions.score:calculate"
    assert spec.protocols == ["all"]
    assert spec.capabilities == []
    assert spec.policy_ref is None
    assert spec.timeout_s == 30.0
    assert spec.tenant_aware is False
    assert spec.feature_flag is None


def test_full_skill_spec() -> None:
    """SkillSpec с полным набором опций."""
    spec = SkillSpec(
        id="credit.score.calculate",
        version="1.2.0",
        handler="extensions.credit.functions.score:calculate",
        description="Расчёт скоринга",
        input_schema="schemas/credit_score_input.json",
        output_schema="schemas/credit_score_output.json",
        capabilities=["db.read.orders", "ai.invoke.credit_check"],
        policy_ref="credit_check_strict",
        protocols=["mcp", "langgraph", "openai_tools"],
        timeout_s=10.0,
        tenant_aware=True,
        feature_flag="CREDIT_SCORE_V2_ENABLED",
    )
    assert "ai.invoke.credit_check" in spec.capabilities
    assert spec.policy_ref == "credit_check_strict"
    assert "mcp" in spec.protocols
    assert spec.timeout_s == 10.0


def test_skill_registry_empty() -> None:
    """SkillRegistry по умолчанию пуст."""
    registry = SkillRegistry()
    assert registry.list_skills() == []


def test_skill_registry_from_toml_loads_skills(tmp_path: Path) -> None:
    """from_toml_manifest загружает [[skill]] секции из plugin.toml V11.2."""
    registry = SkillRegistry()
    plugin_toml = tmp_path / "plugin.toml"
    plugin_toml.write_text(
        '[[skill]]\nid="credit.score"\nversion="1.0"\nhandler="skills.credit:score"\n',
        encoding="utf-8",
    )
    specs = registry.from_toml_manifest(plugin_toml)
    assert len(specs) == 1
    assert specs[0].id == "credit.score"


@pytest.mark.asyncio
async def test_skill_registry_invoke_raises_key_error_for_unknown_skill() -> None:
    """invoke() raises KeyError for an unknown skill_id."""
    registry = SkillRegistry()
    with pytest.raises(KeyError):
        await registry.invoke("credit.score.calculate")


def test_skill_registry_export_methods_not_implemented() -> None:
    """auto-export методы: S162 W1, Sibling Sprint 7 реализовал.

    Was originally scaffold (NotImplementedError). After Sibling Sprint 7
    implementation, methods return lists. Test now verifies they work
    without raising.
    """
    registry = SkillRegistry()
    assert isinstance(registry.export_to_mcp(), list)
    assert isinstance(registry.export_to_langgraph(), list)
    assert isinstance(registry.export_to_openai_tools(), list)
