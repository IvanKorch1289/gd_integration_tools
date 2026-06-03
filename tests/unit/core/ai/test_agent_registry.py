"""Unit tests for src.backend.core.ai.agent_registry."""

from __future__ import annotations

import pytest

from src.backend.core.ai.agent_registry import AgentRegistry
from src.backend.core.ai.agent_spec import AgentSpec


class TestRegisterAndGet:
    def test_register_and_get(self) -> None:
        reg = AgentRegistry()
        spec = AgentSpec(id="a1", version="1.0.0", model="m")
        reg.register(spec)
        assert reg.get_agent("a1") is spec

    def test_get_missing(self) -> None:
        reg = AgentRegistry()
        with pytest.raises(KeyError, match="a1"):
            reg.get_agent("a1")


class TestListAgents:
    def test_sorted(self) -> None:
        reg = AgentRegistry()
        s1 = AgentSpec(id="b", version="1", model="m")
        s2 = AgentSpec(id="a", version="1", model="m")
        reg.register(s1)
        reg.register(s2)
        assert reg.list_agents() == [s2, s1]

    def test_empty(self) -> None:
        reg = AgentRegistry()
        assert reg.list_agents() == []


class TestFromTOMLManifest:
    def test_success(self, tmp_path) -> None:
        toml = tmp_path / "plugin.toml"
        toml.write_text(
            '''
[[agent]]
id = "credit_advisor"
version = "1.0.0"
model = "openai:gpt-4"
prompt_ref = "p.j2"
skills = ["s1"]
tools = ["t1"]
memory_mode = "scoped"
memory_write = ["episodic"]
handoff_max = 3
handoff_allow_revisit = true
policy_ref = "strict"
max_turns = 15
timeout_s = 90.0
tenant_aware = false
feature_flag = "F1"
''',
            encoding="utf-8",
        )
        reg = AgentRegistry()
        specs = reg.from_toml_manifest(toml)
        assert len(specs) == 1
        spec = specs[0]
        assert spec.id == "credit_advisor"
        assert spec.version == "1.0.0"
        assert spec.model == "openai:gpt-4"
        assert spec.prompt_ref == "p.j2"
        assert spec.skills == ("s1",)
        assert spec.tools == ("t1",)
        assert spec.memory.mode == "scoped"
        assert spec.memory.write == ("episodic",)
        assert spec.handoff.max_handoffs == 3
        assert spec.handoff.allow_revisit is True
        assert spec.policy_ref == "strict"
        assert spec.max_turns == 15
        assert spec.timeout_s == 90.0
        assert spec.tenant_aware is False
        assert spec.feature_flag == "F1"
        assert reg.get_agent("credit_advisor") is spec

    def test_missing_required_field(self, tmp_path) -> None:
        toml = tmp_path / "plugin.toml"
        toml.write_text(
            '''
[[agent]]
id = "a1"
''',
            encoding="utf-8",
        )
        reg = AgentRegistry()
        with pytest.raises(ValueError, match="missing required field"):
            reg.from_toml_manifest(toml)

    def test_no_agent_section(self, tmp_path) -> None:
        toml = tmp_path / "plugin.toml"
        toml.write_text("[other]\nkey = 1\n", encoding="utf-8")
        reg = AgentRegistry()
        assert reg.from_toml_manifest(toml) == []

    def test_empty_agent_section(self, tmp_path) -> None:
        toml = tmp_path / "plugin.toml"
        toml.write_text("agent = []\n", encoding="utf-8")
        reg = AgentRegistry()
        assert reg.from_toml_manifest(toml) == []

    def test_retry_policy(self, tmp_path) -> None:
        toml = tmp_path / "plugin.toml"
        toml.write_text(
            '''
[[agent]]
id = "a1"
version = "1"
model = "m"
retry_max_attempts = 5
retry_initial_interval_s = 2.0
retry_backoff_coefficient = 3.0
''',
            encoding="utf-8",
        )
        reg = AgentRegistry()
        specs = reg.from_toml_manifest(toml)
        assert specs[0].retry_policy is not None
        assert specs[0].retry_policy.max_attempts == 5


class TestHotReload:
    @pytest.mark.asyncio
    async def test_not_implemented(self, tmp_path) -> None:
        reg = AgentRegistry()
        with pytest.raises(NotImplementedError):
            await reg.hot_reload(tmp_path / "x.toml")
