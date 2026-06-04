"""Unit tests for src.backend.core.ai.skill_registry."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.core.ai.skill_registry import SkillRegistry, SkillSpec


class TestFromTOMLManifest:
    def test_success(self, tmp_path) -> None:
        toml = tmp_path / "plugin.toml"
        toml.write_text(
            """
[[skill]]
id = "s1"
version = "1.0.0"
handler = "mod:fn"
description = "desc"
capabilities = ["cap1"]
timeout_s = 15.0
tenant_aware = true
""",
            encoding="utf-8",
        )
        reg = SkillRegistry()
        specs = reg.from_toml_manifest(toml)
        assert len(specs) == 1
        assert specs[0].id == "s1"
        assert specs[0].version == "1.0.0"
        assert specs[0].handler == "mod:fn"
        assert specs[0].description == "desc"
        assert specs[0].capabilities == ["cap1"]
        assert specs[0].timeout_s == 15.0
        assert specs[0].tenant_aware is True
        assert reg.list_skills() == specs

    def test_missing_required_field(self, tmp_path) -> None:
        toml = tmp_path / "plugin.toml"
        toml.write_text('[[skill]]\nid = "s1"\n', encoding="utf-8")
        reg = SkillRegistry()
        with pytest.raises(ValueError, match="missing required field"):
            reg.from_toml_manifest(toml)

    def test_no_skill_section(self, tmp_path) -> None:
        toml = tmp_path / "plugin.toml"
        toml.write_text("[other]\nkey = 1\n", encoding="utf-8")
        reg = SkillRegistry()
        assert reg.from_toml_manifest(toml) == []

    def test_empty_skill_section(self, tmp_path) -> None:
        toml = tmp_path / "plugin.toml"
        toml.write_text("skill = []\n", encoding="utf-8")
        reg = SkillRegistry()
        assert reg.from_toml_manifest(toml) == []


class TestInvoke:
    async def test_sync_success(self) -> None:
        reg = SkillRegistry()
        reg._skills["s1"] = SkillSpec(id="s1", version="1", handler="mod:fn")
        fake_mod = MagicMock()
        fake_mod.fn = MagicMock(return_value=42)
        with patch("importlib.import_module", return_value=fake_mod):
            result = await reg.invoke("s1", x=1)
        assert result == 42
        fake_mod.fn.assert_called_once_with(x=1)

    async def test_async_success(self) -> None:
        reg = SkillRegistry()
        reg._skills["s1"] = SkillSpec(id="s1", version="1", handler="mod:fn")
        fake_mod = MagicMock()
        fake_mod.fn = AsyncMock(return_value=99)
        with patch("importlib.import_module", return_value=fake_mod):
            result = await reg.invoke("s1")
        assert result == 99

    async def test_missing_skill(self) -> None:
        reg = SkillRegistry()
        with pytest.raises(KeyError, match="s1"):
            await reg.invoke("s1")

    async def test_bad_handler_format(self) -> None:
        reg = SkillRegistry()
        reg._skills["s1"] = SkillSpec(id="s1", version="1", handler="bad")
        with pytest.raises(ValueError, match="module:fn"):
            await reg.invoke("s1")

    async def test_import_error(self) -> None:
        reg = SkillRegistry()
        reg._skills["s1"] = SkillSpec(id="s1", version="1", handler="mod:fn")
        with patch("importlib.import_module", side_effect=ImportError("no")):
            with pytest.raises(ImportError, match="cannot import"):
                await reg.invoke("s1")

    async def test_attr_error(self) -> None:
        reg = SkillRegistry()
        reg._skills["s1"] = SkillSpec(id="s1", version="1", handler="mod:fn")
        fake_mod = MagicMock()
        fake_mod.fn = None
        with patch("importlib.import_module", return_value=fake_mod):
            with pytest.raises(AttributeError, match="has no attribute"):
                await reg.invoke("s1")


class TestListSkills:
    def test_sorted(self) -> None:
        reg = SkillRegistry()
        s1 = SkillSpec(id="b", version="1", handler="m:f")
        s2 = SkillSpec(id="a", version="1", handler="m:f")
        reg._skills["b"] = s1
        reg._skills["a"] = s2
        assert reg.list_skills() == [s2, s1]

    def test_empty(self) -> None:
        reg = SkillRegistry()
        assert reg.list_skills() == []


class TestNotImplemented:
    @pytest.mark.asyncio
    async def test_hot_reload(self) -> None:
        reg = SkillRegistry()
        with pytest.raises(NotImplementedError):
            await reg.hot_reload()

    def test_from_python_decorator(self) -> None:
        reg = SkillRegistry()
        with pytest.raises(NotImplementedError):
            reg.from_python_decorator(lambda: None)

    def test_export_to_mcp(self) -> None:
        reg = SkillRegistry()
        with pytest.raises(NotImplementedError):
            reg.export_to_mcp()

    def test_export_to_langgraph(self) -> None:
        reg = SkillRegistry()
        with pytest.raises(NotImplementedError):
            reg.export_to_langgraph()

    def test_export_to_openai_tools(self) -> None:
        reg = SkillRegistry()
        with pytest.raises(NotImplementedError):
            reg.export_to_openai_tools()
