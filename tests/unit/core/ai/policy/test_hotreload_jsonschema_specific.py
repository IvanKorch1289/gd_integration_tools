"""S77 W4 — tests для hot-reload + JSON-Schema + specificity-based resolution
(FINAL_REPORT_V2 P0-C closure, ADR-0067)."""
from __future__ import annotations

import asyncio
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

from src.backend.core.ai.policy.spec import (
    AIPolicySpec,
    ModelRouterSpec,
    ToolsSpec,
)
from src.backend.core.ai.policy.jsonschema_export import (
    export_aipolicy_json_schema,
    export_default_policy_yaml,
    validate_aipolicy_dict,
)
from src.backend.core.ai.policy.specificity import (
    compute_specificity,
    find_specific_match,
)


# JSON-Schema export tests
# ============================================================================


def test_json_schema_is_valid_object() -> None:
    """export_aipolicy_json_schema returns valid JSON Schema object."""
    schema = export_aipolicy_json_schema()
    assert schema["type"] == "object"
    assert "properties" in schema
    assert "required" in schema
    # All required fields present
    for req in ["name", "workflow_pattern", "model_router"]:
        assert req in schema["required"]


def test_json_schema_includes_tools_subschema() -> None:
    """JSON Schema includes tools sub-schema (S76 ToolsSpec)."""
    schema = export_aipolicy_json_schema()
    # Either direct or via $defs
    assert "tools" in schema["properties"]
    # Pydantic uses $defs for sub-models
    assert "$defs" in schema or "definitions" in schema


def test_json_schema_includes_budget_subschema() -> None:
    """JSON Schema includes budget sub-schema."""
    schema = export_aipolicy_json_schema()
    assert "budget" in schema["properties"]


def test_validate_aipolicy_dict_round_trip() -> None:
    """validate_aipolicy_dict accepts dict matching schema."""
    data = {
        "name": "test_policy",
        "workflow_pattern": "test_*",
        "tenant_pattern": "*",
        "model_router": {
            "primary": "openai/gpt-4",
            "fallback": ["openai/gpt-4o-mini"],
            "timeout_s": 30.0,
        },
        "tools": {
            "whitelist": ["db.read", "ai.invoke"],
            "blacklist": ["fs.write"],
            "on_violation": "fail",
        },
    }
    spec = validate_aipolicy_dict(data)
    assert spec.name == "test_policy"
    assert spec.tools.whitelist == ["db.read", "ai.invoke"]
    assert spec.tools.on_violation == "fail"


def test_validate_aipolicy_dict_invalid_raises() -> None:
    """validate_aipolicy_dict raises on invalid data."""
    data = {
        "name": "missing_workflow",
        "model_router": {"primary": "openai/gpt-4"},
        # Missing required 'workflow_pattern'
    }
    with pytest.raises(Exception):  # Pydantic ValidationError
        validate_aipolicy_dict(data)


def test_export_default_policy_yaml() -> None:
    """Default YAML template is valid YAML и loadable."""
    yaml_str = export_default_policy_yaml()
    assert "name: my_workflow_policy" in yaml_str
    assert "workflow_pattern: my_workflow_*" in yaml_str
    assert "tools:" in yaml_str
    assert "whitelist: []" in yaml_str
    # Roundtrip — load YAML, validate
    parsed = yaml.safe_load(yaml_str)
    spec = validate_aipolicy_dict(parsed)
    assert spec.name == "my_workflow_policy"
    assert spec.tools.on_violation == "fail"


# Specificity tests
# ============================================================================


def test_compute_specificity_exact() -> None:
    """Exact match → score = len(pattern)."""
    assert compute_specificity("premium_user", "premium_user") == 12
    assert compute_specificity("credit_check_v2", "credit_check_v2") == 15


def test_compute_specificity_wildcard() -> None:
    """Wildcard match → score = non-wildcard prefix length."""
    assert compute_specificity("*", "any") == 0
    assert compute_specificity("premium_*", "premium_user") == 8  # len "premium_"
    assert compute_specificity("credit_*", "credit_check") == 7  # len "credit_"


def test_compute_specificity_no_match() -> None:
    """No match → score = -1."""
    assert compute_specificity("premium_*", "basic_user") == -1
    assert compute_specificity("credit_*", "fraud_check") == -1


def test_compute_specificity_wildcard_only_suffix() -> None:
    """Pattern with only leading non-wildcard prefix → score = prefix len."""
    assert compute_specificity("a*b", "axxxb") == 1
    assert compute_specificity("test_*", "test_123") == 5  # len "test_"


def test_find_specific_match_empty() -> None:
    """Empty policies list → None."""
    assert find_specific_match([], "credit", "user") is None


def test_find_specific_match_no_match() -> None:
    """No matching policies → None."""
    policies = [
        AIPolicySpec(
            name="credit",
            workflow_pattern="credit_*",
            tenant_pattern="*",
            model_router=ModelRouterSpec(primary="openai/gpt-4"),
        ),
    ]
    assert find_specific_match(policies, "fraud_check", "user") is None


def test_find_specific_match_picks_most_specific() -> None:
    """Most specific tenant_pattern wins."""
    global_policy = AIPolicySpec(
        name="global",
        workflow_pattern="credit_*",
        tenant_pattern="*",
        model_router=ModelRouterSpec(primary="openai/gpt-4"),
    )
    premium_policy = AIPolicySpec(
        name="premium",
        workflow_pattern="credit_*",
        tenant_pattern="premium_*",
        model_router=ModelRouterSpec(primary="openai/gpt-4o"),
    )
    # premium_* more specific than *
    result = find_specific_match(
        [global_policy, premium_policy],
        "credit_check",
        "premium_user",
    )
    assert result is not None
    assert result.name == "premium"


def test_find_specific_match_falls_back_to_global() -> None:
    """If no specific policy matches, fall back to global."""
    global_policy = AIPolicySpec(
        name="global",
        workflow_pattern="credit_*",
        tenant_pattern="*",
        model_router=ModelRouterSpec(primary="openai/gpt-4"),
    )
    premium_policy = AIPolicySpec(
        name="premium",
        workflow_pattern="credit_*",
        tenant_pattern="premium_*",
        model_router=ModelRouterSpec(primary="openai/gpt-4o"),
    )
    # basic_user doesn't match premium_*
    result = find_specific_match(
        [global_policy, premium_policy],
        "credit_check",
        "basic_user",
    )
    assert result is not None
    assert result.name == "global"


def test_find_specific_match_tenant_priority_over_workflow() -> None:
    """tenant_pattern specificity prioritized over workflow_pattern."""
    # Two policies: one with specific workflow + global tenant,
    # one with global workflow + specific tenant.
    # Specific tenant should win (tenant > workflow priority).
    specific_workflow_global_tenant = AIPolicySpec(
        name="specific_workflow",
        workflow_pattern="credit_check_v2",
        tenant_pattern="*",
        model_router=ModelRouterSpec(primary="openai/gpt-4"),
    )
    global_workflow_specific_tenant = AIPolicySpec(
        name="specific_tenant",
        workflow_pattern="credit_*",
        tenant_pattern="premium_user",
        model_router=ModelRouterSpec(primary="openai/gpt-4o"),
    )
    result = find_specific_match(
        [specific_workflow_global_tenant, global_workflow_specific_tenant],
        "credit_check_v2",
        "premium_user",
    )
    # Both match. specific_tenant should win (tenant_pattern more specific).
    assert result is not None
    assert result.name == "specific_tenant"


# PolicyResolver integration tests
# ============================================================================


@pytest.fixture
def policy_roots() -> Iterator[tuple[Path, Path]]:
    """Create temp dirs with global + premium policy files."""
    with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
        global_p = AIPolicySpec(
            name="global",
            workflow_pattern="credit_*",
            tenant_pattern="*",
            model_router=ModelRouterSpec(primary="openai/gpt-4"),
        )
        premium_p = AIPolicySpec(
            name="premium",
            workflow_pattern="credit_*",
            tenant_pattern="premium_*",
            model_router=ModelRouterSpec(primary="openai/gpt-4o"),
        )
        Path(d1, "global.policy.yaml").write_text(
            yaml.dump(global_p.model_dump(mode="json"))
        )
        Path(d2, "premium.policy.yaml").write_text(
            yaml.dump(premium_p.model_dump(mode="json"))
        )
        yield Path(d1), Path(d2)


def test_resolver_resolve_specific_integration(policy_roots: tuple[Path, Path]) -> None:
    """PolicyResolver.resolve_specific integration with YAML files."""
    from src.backend.core.ai.policy.resolver import PolicyResolver

    d1, d2 = policy_roots
    # d1 (global) first — but resolve_specific should still pick premium
    r = PolicyResolver(roots=[d1, d2])

    premium_result = asyncio.run(r.resolve_specific("credit_check", "premium_user"))
    basic_result = asyncio.run(r.resolve_specific("credit_check", "basic_user"))

    assert premium_result is not None
    assert premium_result.name == "premium"
    assert basic_result is not None
    assert basic_result.name == "global"


def test_resolver_resolve_still_first_match(policy_roots: tuple[Path, Path]) -> None:
    """resolve() unchanged — first match wins (order matters)."""
    from src.backend.core.ai.policy.resolver import PolicyResolver

    d1, d2 = policy_roots
    r = PolicyResolver(roots=[d1, d2])

    # Global first in roots → wins for both
    basic_result = asyncio.run(r.resolve("credit_check", "basic_user"))
    premium_result = asyncio.run(r.resolve("credit_check", "premium_user"))

    assert basic_result is not None
    assert basic_result.name == "global"
    assert premium_result is not None
    assert premium_result.name == "global"  # First match wins, not specificity


def test_resolver_reload_clears_specific_cache(policy_roots: tuple[Path, Path]) -> None:
    """reload() clears both _cache and _specific_cache."""
    from src.backend.core.ai.policy.resolver import PolicyResolver

    d1, d2 = policy_roots
    r = PolicyResolver(roots=[d1, d2])

    # Populate caches
    asyncio.run(r.resolve("credit_check", "premium_user"))
    asyncio.run(r.resolve_specific("credit_check", "premium_user"))
    assert len(r._cache) > 0
    assert hasattr(r, "_specific_cache") and len(r._specific_cache) > 0

    # Reload — should clear both
    r.reload()
    assert len(r._cache) == 0
    assert hasattr(r, "_specific_cache") and len(r._specific_cache) == 0


# Hot-reload tests (using mock watchfiles, no real FS watching)
# ============================================================================


def test_hotreload_event_dataclass() -> None:
    """PolicyReloadEvent frozen dataclass works."""
    from src.backend.core.ai.policy.hotreload import (
        PolicyReloadEvent,
        PolicyReloadAction,
    )

    event = PolicyReloadEvent(
        path=Path("/policies/test.policy.yaml"),
        action=PolicyReloadAction.MODIFIED,
    )
    assert event.path == Path("/policies/test.policy.yaml")
    assert event.action == PolicyReloadAction.MODIFIED
    # Frozen
    with pytest.raises(Exception):  # FrozenInstanceError
        event.action = PolicyReloadAction.ADDED  # type: ignore[misc]


def test_hotreload_action_enum_values() -> None:
    """PolicyReloadAction enum has expected values."""
    from src.backend.core.ai.policy.hotreload import PolicyReloadAction

    assert PolicyReloadAction.ADDED.value == "added"
    assert PolicyReloadAction.MODIFIED.value == "modified"
    assert PolicyReloadAction.DELETED.value == "deleted"
