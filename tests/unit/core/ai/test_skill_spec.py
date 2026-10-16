"""Tests for ``src.backend.core.ai.skill_spec``.

S66 M2-#8: Pydantic v2 model для AI skill declaration.
Маппится 1:1 на TOML-секцию ``[[skill]]`` из plugin.toml V11.2.

Тесты фиксируют контракт Pydantic-модели:
- required fields (id, version, handler)
- defaults (description="", capabilities=[], protocols=["all"],
  timeout_s=30.0, tenant_aware=False, feature_flag=None)
- constraints (timeout_s >= 0.1, protocols — Literal)
- immutability-by-default (Pydantic v2 frozen=False → mutable)
- serialization (model_dump, model_dump_json)
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.backend.core.ai.skill_spec import SkillSpec


class TestSkillSpecRequired:
    """Required поля: id, version, handler."""

    def test_minimal_construction(self) -> None:
        spec = SkillSpec(
            id="credit.score.calculate",
            version="1.2.0",
            handler="extensions.credit.handler:score_calculate",
        )
        assert spec.id == "credit.score.calculate"
        assert spec.version == "1.2.0"
        assert spec.handler == "extensions.credit.handler:score_calculate"

    def test_missing_id_raises(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            SkillSpec(version="1.0.0", handler="m:f")  # type: ignore[call-arg]
        assert "id" in str(exc_info.value)

    def test_missing_version_raises(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            SkillSpec(id="x", handler="m:f")  # type: ignore[call-arg]
        assert "version" in str(exc_info.value)

    def test_missing_handler_raises(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            SkillSpec(id="x", version="1.0.0")  # type: ignore[call-arg]
        assert "handler" in str(exc_info.value)


class TestSkillSpecDefaults:
    """Defaults для optional полей."""

    def test_description_default_empty(self) -> None:
        spec = SkillSpec(id="x", version="1.0.0", handler="m:f")
        assert spec.description == ""

    def test_description_set(self) -> None:
        spec = SkillSpec(
            id="x",
            version="1.0.0",
            handler="m:f",
            description="Credit score calculation handler",
        )
        assert spec.description == "Credit score calculation handler"

    def test_input_output_schema_default_none(self) -> None:
        spec = SkillSpec(id="x", version="1.0.0", handler="m:f")
        assert spec.input_schema is None
        assert spec.output_schema is None

    def test_capabilities_default_empty(self) -> None:
        spec = SkillSpec(id="x", version="1.0.0", handler="m:f")
        assert spec.capabilities == []

    def test_policy_ref_default_none(self) -> None:
        spec = SkillSpec(id="x", version="1.0.0", handler="m:f")
        assert spec.policy_ref is None

    def test_protocols_default_all(self) -> None:
        """Default protocols — ``['all']`` (auto-export во все протоколы)."""
        spec = SkillSpec(id="x", version="1.0.0", handler="m:f")
        assert spec.protocols == ["all"]

    def test_timeout_s_default_30(self) -> None:
        spec = SkillSpec(id="x", version="1.0.0", handler="m:f")
        assert spec.timeout_s == 30.0

    def test_tenant_aware_default_false(self) -> None:
        spec = SkillSpec(id="x", version="1.0.0", handler="m:f")
        assert spec.tenant_aware is False

    def test_tenant_allowlist_default_none(self) -> None:
        spec = SkillSpec(id="x", version="1.0.0", handler="m:f")
        assert spec.tenant_allowlist is None

    def test_feature_flag_default_none(self) -> None:
        spec = SkillSpec(id="x", version="1.0.0", handler="m:f")
        assert spec.feature_flag is None


class TestSkillSpecConstraints:
    """Pydantic field constraints."""

    def test_timeout_s_ge_constraint(self) -> None:
        """timeout_s >= 0.1 — слишком маленький таймаут не имеет смысла."""
        with pytest.raises(ValidationError) as exc_info:
            SkillSpec(id="x", version="1.0.0", handler="m:f", timeout_s=0.05)
        assert "timeout_s" in str(exc_info.value)

    def test_timeout_s_zero_raises(self) -> None:
        with pytest.raises(ValidationError):
            SkillSpec(id="x", version="1.0.0", handler="m:f", timeout_s=0.0)

    def test_timeout_s_negative_raises(self) -> None:
        with pytest.raises(ValidationError):
            SkillSpec(id="x", version="1.0.0", handler="m:f", timeout_s=-1.0)

    def test_timeout_s_minimum_accepted(self) -> None:
        """Граничный случай 0.1 — допустим."""
        spec = SkillSpec(id="x", version="1.0.0", handler="m:f", timeout_s=0.1)
        assert spec.timeout_s == 0.1

    def test_timeout_s_large_accepted(self) -> None:
        """Большие таймауты OK (нет upper bound)."""
        spec = SkillSpec(id="x", version="1.0.0", handler="m:f", timeout_s=3600.0)
        assert spec.timeout_s == 3600.0

    def test_protocols_invalid_value_raises(self) -> None:
        """protocols — Literal, не 'graphql' или другие значения."""
        with pytest.raises(ValidationError) as exc_info:
            SkillSpec(
                id="x",
                version="1.0.0",
                handler="m:f",
                protocols=["graphql"],  # type: ignore[list-item]
            )
        assert "protocols" in str(exc_info.value)

    def test_protocols_valid_values(self) -> None:
        """Все 4 допустимых значения Literal работают."""
        for proto in ("mcp", "langgraph", "openai_tools", "all"):
            spec = SkillSpec(
                id="x",
                version="1.0.0",
                handler="m:f",
                protocols=[proto],  # type: ignore[list-item]
            )
            assert spec.protocols == [proto]


class TestSkillSpecCapabilities:
    """capabilities — list[str] с default factory."""

    def test_capabilities_list_set(self) -> None:
        spec = SkillSpec(
            id="x",
            version="1.0.0",
            handler="m:f",
            capabilities=["db.read.orders", "ai.invoke.credit_check"],
        )
        assert spec.capabilities == [
            "db.read.orders",
            "ai.invoke.credit_check",
        ]

    def test_capabilities_factory_isolation(self) -> None:
        """``default_factory=list`` — каждый инстанс получает свой list."""
        s1 = SkillSpec(id="a", version="1.0.0", handler="m:f")
        s2 = SkillSpec(id="b", version="1.0.0", handler="m:f")
        s1.capabilities.append("x")
        assert s2.capabilities == []


class TestSkillSpecTenantAllowlist:
    """tenant_allowlist — опциональный whitelist тенантов."""

    def test_tenant_allowlist_set(self) -> None:
        spec = SkillSpec(
            id="x",
            version="1.0.0",
            handler="m:f",
            tenant_aware=True,
            tenant_allowlist=["tenant-A", "tenant-B"],
        )
        assert spec.tenant_allowlist == ["tenant-A", "tenant-B"]

    def test_tenant_allowlist_empty_list(self) -> None:
        """Пустой list ≠ None: ``[]`` — нет разрешённых тенантов, ``None`` — все."""
        spec = SkillSpec(
            id="x",
            version="1.0.0",
            handler="m:f",
            tenant_allowlist=[],
        )
        assert spec.tenant_allowlist == []


class TestSkillSpecSerialization:
    """Pydantic v2 сериализация."""

    def test_model_dump(self) -> None:
        spec = SkillSpec(
            id="credit.score.calculate",
            version="1.2.0",
            handler="extensions.credit:score",
        )
        data = spec.model_dump()
        assert data["id"] == "credit.score.calculate"
        assert data["version"] == "1.2.0"
        assert data["handler"] == "extensions.credit:score"
        assert data["timeout_s"] == 30.0
        assert data["tenant_aware"] is False
        assert data["protocols"] == ["all"]

    def test_model_dump_json(self) -> None:
        """JSON-сериализация для TOML/JSON storage."""
        import json

        spec = SkillSpec(
            id="x",
            version="1.0.0",
            handler="m:f",
            capabilities=["a", "b"],
        )
        json_str = spec.model_dump_json()
        parsed = json.loads(json_str)
        assert parsed["id"] == "x"
        assert parsed["capabilities"] == ["a", "b"]

    def test_model_validate_from_dict(self) -> None:
        """Round-trip: dict → SkillSpec (для загрузки из TOML/JSON)."""
        data = {
            "id": "x",
            "version": "1.0.0",
            "handler": "m:f",
            "capabilities": ["a", "b"],
            "protocols": ["mcp"],
        }
        spec = SkillSpec.model_validate(data)
        assert spec.id == "x"
        assert spec.capabilities == ["a", "b"]
        assert spec.protocols == ["mcp"]


class TestSkillSpecEquality:
    """Pydantic v2 BaseModel: __eq__ по полям."""

    def test_equal_same_fields(self) -> None:
        s1 = SkillSpec(id="x", version="1.0.0", handler="m:f")
        s2 = SkillSpec(id="x", version="1.0.0", handler="m:f")
        assert s1 == s2

    def test_not_equal_different_id(self) -> None:
        s1 = SkillSpec(id="x", version="1.0.0", handler="m:f")
        s2 = SkillSpec(id="y", version="1.0.0", handler="m:f")
        assert s1 != s2


class TestSkillSpecRepr:
    """Pydantic v2 __repr__/__str__ содержат основные поля."""

    def test_repr_contains_id(self) -> None:
        spec = SkillSpec(id="credit.score", version="1.0.0", handler="m:f")
        text = repr(spec)
        assert "credit.score" in text
