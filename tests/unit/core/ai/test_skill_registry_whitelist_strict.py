"""S177 #5: тесты strict whitelist enforcement в SkillRegistry.invoke().

Проверяет:
- whitelist=None + call_function_whitelist_strict=True (default) → PermissionError
- whitelist=None + call_function_whitelist_strict=False → backward-compat (legacy)
- whitelist passed → валидация работает (уже было, backward-compat)
- whitelist={"mod"} exact match → ok
- whitelist={"mod.*"} glob match → ok для sub-modules

Этот файл дополняет существующий tests/unit/core/ai/test_skill_registry.py
новыми тестами на S177 #5 enforcement.
"""

# ruff: noqa: S101

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.backend.core.ai.skill_registry import SkillRegistry, SkillSpec


class TestWhitelistStrictEnforcement:
    """S177 #5: enforce whitelist через call_function_whitelist_strict flag."""

    @pytest.mark.asyncio
    async def test_strict_default_raises_without_whitelist(self) -> None:
        """Default strict=True → whitelist=None → PermissionError."""
        from src.backend.core.config.features import feature_flags

        # Default flag — True (см. Sprints_15_17 config).
        assert feature_flags.call_function_whitelist_strict is True

        reg = SkillRegistry()
        reg._skills["s1"] = SkillSpec(id="s1", version="1", handler="mod:fn")

        with pytest.raises(PermissionError, match="whitelist required"):
            await reg.invoke("s1")

    @pytest.mark.asyncio
    async def test_strict_false_allows_no_whitelist(self) -> None:
        """strict=False → whitelist=None → backward-compat (legacy)."""
        from src.backend.core.config.features import feature_flags

        original = feature_flags.call_function_whitelist_strict
        feature_flags.call_function_whitelist_strict = False
        try:
            reg = SkillRegistry()
            reg._skills["s1"] = SkillSpec(
                id="s1", version="1", handler="any.module:fn"
            )
            fake_mod = MagicMock()
            fake_mod.fn = MagicMock(return_value="legacy_ok")
            with patch("importlib.import_module", return_value=fake_mod):
                result = await reg.invoke("s1")
            assert result == "legacy_ok"
        finally:
            feature_flags.call_function_whitelist_strict = original

    @pytest.mark.asyncio
    async def test_strict_with_whitelist_passes(self) -> None:
        """strict=True + whitelist передан → валидация работает."""
        reg = SkillRegistry()
        reg._skills["s1"] = SkillSpec(id="s1", version="1", handler="mod:fn")
        fake_mod = MagicMock()
        fake_mod.fn = MagicMock(return_value=42)
        with patch("importlib.import_module", return_value=fake_mod):
            result = await reg.invoke("s1", whitelist={"mod"})
        assert result == 42

    @pytest.mark.asyncio
    async def test_strict_with_whitelist_glob_match(self) -> None:
        """strict=True + whitelist glob-pattern → sub-modules разрешены."""
        reg = SkillRegistry()
        reg._skills["s1"] = SkillSpec(
            id="s1", version="1", handler="extensions.credit.sub:fn"
        )
        fake_mod = MagicMock()
        fake_mod.fn = MagicMock(return_value="glob_ok")
        with patch("importlib.import_module", return_value=fake_mod):
            result = await reg.invoke("s1", whitelist={"extensions.*"})
        assert result == "glob_ok"

    @pytest.mark.asyncio
    async def test_strict_with_whitelist_denies_non_whitelisted(self) -> None:
        """strict=True + whitelist → не-listed module → PermissionError."""
        reg = SkillRegistry()
        reg._skills["s1"] = SkillSpec(
            id="s1", version="1", handler="evil.module:fn"
        )
        # import НЕ должен вызваться.
        with patch("importlib.import_module") as mock_imp:
            with pytest.raises(PermissionError, match="not in whitelist"):
                await reg.invoke("s1", whitelist={"trusted.*"})
        mock_imp.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_whitelist_strict_raises_value_error(self) -> None:
        """strict=True + whitelist=set() → ValueError (не PermissionError)."""
        reg = SkillRegistry()
        reg._skills["s1"] = SkillSpec(id="s1", version="1", handler="mod:fn")
        with pytest.raises(ValueError, match="empty whitelist"):
            await reg.invoke("s1", whitelist=set())

    @pytest.mark.asyncio
    async def test_permission_error_message_mentions_skill_id(self) -> None:
        """Error message включает skill_id для debugging."""
        reg = SkillRegistry()
        reg._skills["my_skill"] = SkillSpec(
            id="my_skill", version="1", handler="mod:fn"
        )
        with pytest.raises(PermissionError, match="my_skill"):
            await reg.invoke("my_skill")