"""Smoke-тесты :class:`AgentSpec`, :class:`MemoryScope`, :class:`HandoffPolicy` (S28 W1).

Проверяют:

* AgentSpec Pydantic v2 валидация (через dataclass);
* MemoryScope и HandoffPolicy defaults;
* AgentRegistry empty по умолчанию + TOML loader;
* MemoryScope from TOML manifest.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.backend.core.ai.agent_registry import AgentRegistry
from src.backend.core.ai.agent_spec import AgentSpec, HandoffPolicy, MemoryScope


def test_minimal_agent_spec() -> None:
    """AgentSpec с минимальными required полями валиден."""
    spec = AgentSpec(id="credit_advisor", version="1.0.0", model="minimax:m2")
    assert spec.id == "credit_advisor"
    assert spec.version == "1.0.0"
    assert spec.model == "minimax:m2"
    assert spec.skills == ()
    assert spec.tools == ()
    assert spec.memory.mode == "scoped"
    assert spec.memory.write_strategy == "background"
    assert spec.handoff.max_handoffs == 5
    assert spec.handoff.allow_revisit is False
    assert spec.max_turns == 10
    assert spec.timeout_s == 60.0
    assert spec.tenant_aware is True
    assert spec.feature_flag is None


def test_full_agent_spec() -> None:
    """AgentSpec с полным набором опций."""
    memory = MemoryScope(
        read=("episodic", "semantic"),
        write=("episodic",),
        mode="scoped",
        write_strategy="background",
    )
    handoff = HandoffPolicy(
        max_handoffs=3, allow_revisit=True, escalation_on_max_handoffs="senior_advisor"
    )
    spec = AgentSpec(
        id="credit_advisor",
        version="1.0.0",
        model="minimax:m2",
        prompt_ref="prompts/credit.j2",
        skills=("credit.score.calculate",),
        tools=("actions.credit.fetch",),
        memory=memory,
        handoff=handoff,
        policy_ref="credit_strict",
        max_turns=15,
        timeout_s=90.0,
        tenant_aware=True,
        feature_flag="CREDIT_ADVISOR_V2_ENABLED",
    )
    assert spec.prompt_ref == "prompts/credit.j2"
    assert "credit.score.calculate" in spec.skills
    assert "episodic" in spec.memory.read
    assert spec.handoff.max_handoffs == 3
    assert spec.handoff.escalation_on_max_handoffs == "senior_advisor"
    assert spec.max_turns == 15
    assert spec.timeout_s == 90.0


def test_memory_scope_defaults() -> None:
    """MemoryScope с defaults."""
    scope = MemoryScope()
    assert scope.read == ()
    assert scope.write == ()
    assert scope.mode == "scoped"
    assert scope.write_strategy == "background"


def test_memory_scope_explicit() -> None:
    """MemoryScope с явными значениями."""
    scope = MemoryScope(
        read=("memory_main",),
        write=("episodic",),
        mode="shared",
        write_strategy="hot_path",
    )
    assert scope.read == ("memory_main",)
    assert scope.write == ("episodic",)
    assert scope.mode == "shared"
    assert scope.write_strategy == "hot_path"


def test_handoff_policy_defaults() -> None:
    """HandoffPolicy с defaults."""
    policy = HandoffPolicy()
    assert policy.max_handoffs == 5
    assert policy.allow_revisit is False
    assert policy.escalation_on_max_handoffs is None


def test_agent_registry_empty() -> None:
    """AgentRegistry по умолчанию пуст."""
    registry = AgentRegistry()
    assert registry.list_agents() == []


def test_agent_registry_register() -> None:
    """register() добавляет агента в реестр."""
    registry = AgentRegistry()
    spec = AgentSpec(id="test_agent", version="1.0.0", model="minimax:m2")
    registry.register(spec)
    retrieved = registry.get_agent("test_agent")
    assert retrieved.id == "test_agent"
    assert retrieved.version == "1.0.0"


def test_agent_registry_get_agent_raises_key_error() -> None:
    """get_agent() raises KeyError для неизвестного agent_id."""
    registry = AgentRegistry()
    with pytest.raises(KeyError):
        registry.get_agent("nonexistent")


def test_agent_registry_from_toml_loads_agents(tmp_path: Path) -> None:
    """from_toml_manifest загружает [[agent]] секции из plugin.toml V11.2."""
    registry = AgentRegistry()
    plugin_toml = tmp_path / "plugin.toml"
    plugin_toml.write_text(
        '[[agent]]\nid="credit_advisor"\nversion="1.0.0"\nmodel="minimax:m2"\n'
        'memory_mode="scoped"\nmemory_write=["episodic"]\n'
        "handoff_max=3\n",
        encoding="utf-8",
    )
    specs = registry.from_toml_manifest(plugin_toml)
    assert len(specs) == 1
    assert specs[0].id == "credit_advisor"
    assert specs[0].memory.write == ("episodic",)
    assert specs[0].handoff.max_handoffs == 3


def test_agent_registry_from_toml_multiple_agents(tmp_path: Path) -> None:
    """TOML loader поддерживает несколько [[agent]] секций."""
    registry = AgentRegistry()
    plugin_toml = tmp_path / "plugin.toml"
    plugin_toml.write_text(
        '[[agent]]\nid="agent_one"\nversion="1.0.0"\nmodel="minimax:m2"\n\n'
        '[[agent]]\nid="agent_two"\nversion="2.0.0"\nmodel="openai:gpt-4o"\n',
        encoding="utf-8",
    )
    specs = registry.from_toml_manifest(plugin_toml)
    assert len(specs) == 2
    assert {s.id for s in specs} == {"agent_one", "agent_two"}


def test_agent_registry_from_toml_missing_required_field(tmp_path: Path) -> None:
    """TOML loader поднимает ValueError при missing required field."""
    registry = AgentRegistry()
    plugin_toml = tmp_path / "plugin.toml"
    plugin_toml.write_text(
        '[[agent]]\nid="incomplete"\nversion="1.0.0"\n', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="missing required field: 'model'"):
        registry.from_toml_manifest(plugin_toml)


@pytest.mark.asyncio
async def test_agent_registry_hot_reload_not_implemented() -> None:
    """hot_reload() поднимает NotImplementedError в scaffold-фазе."""
    registry = AgentRegistry()
    with pytest.raises(NotImplementedError):
        await registry.hot_reload(Path("/fake/plugin.toml"))
