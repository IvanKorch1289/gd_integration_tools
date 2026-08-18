"""Coverage tests для module_whitelist (Sprint 5, 2026-08-17).

TDD: edge cases для validate_module_whitelist.
Реальный код в src/backend/core/security/module_whitelist.py.

Coverage targets:
- glob prefix matching (prefix.*)
- denied_suffix в сообщении
- empty_message custom text
- empty_error alternative exception type
- empty_mode="allow" preserves dev fallback
- None whitelist handling (fail-closed)
"""

from __future__ import annotations

import pytest

from src.backend.core.security.module_whitelist import validate_module_whitelist


class TestValidateModuleWhitelistGlob:
    """Glob-style prefix matching: ``src.backend.foo.*`` matches
    ``src.backend.foo.bar.baz``."""

    def test_glob_prefix_match(self) -> None:
        validate_module_whitelist(
            "src.backend.foo.bar.baz",
            whitelist=["src.backend.foo.*"],
            context="test",
        )

    def test_glob_prefix_no_match(self) -> None:
        with pytest.raises(PermissionError):
            validate_module_whitelist(
                "src.backend.other.x",
                whitelist=["src.backend.foo.*"],
                context="test",
            )

    def test_glob_prefix_does_not_match_sibling(self) -> None:
        """``src.backend.foo.*`` must NOT match ``src.backend.foobar.x``.

        Common security bug — prefix match без границы.
        """
        with pytest.raises(PermissionError):
            validate_module_whitelist(
                "src.backend.foobar.x",
                whitelist=["src.backend.foo.*"],
                context="test",
            )

    def test_multiple_globs(self) -> None:
        validate_module_whitelist(
            "src.backend.foo.x",
            whitelist=["src.backend.foo.*", "src.backend.bar.*"],
            context="test",
        )

    def test_exact_match_takes_priority(self) -> None:
        """Exact match (without ``.*``) — direct equality check."""
        validate_module_whitelist(
            "src.backend.foo",
            whitelist=["src.backend.foo"],
            context="test",
        )


class TestValidateModuleWhitelistEmpty:
    """Empty whitelist handling — fail-closed semantics."""

    def test_empty_list_default_raises_permission_error(self) -> None:
        """Default empty_mode='error' + default empty_error=PermissionError."""
        with pytest.raises(PermissionError, match="empty whitelist"):
            validate_module_whitelist(
                "any.module",
                whitelist=[],
                context="test_default",
            )

    def test_empty_list_with_value_error(self) -> None:
        with pytest.raises(ValueError, match="empty whitelist"):
            validate_module_whitelist(
                "any.module",
                whitelist=[],
                context="test_value_error",
                empty_error=ValueError,
            )

    def test_empty_list_allow_mode_passes(self) -> None:
        """``empty_mode='allow'`` — explicit dev fallback (preserved)."""
        # Should NOT raise
        validate_module_whitelist(
            "any.module",
            whitelist=[],
            context="test_allow",
            empty_mode="allow",
        )

    def test_none_whitelist_treated_as_empty(self) -> None:
        """None → empty set → fail-closed (Sprint 215+ ponytail fix)."""
        with pytest.raises(PermissionError):
            validate_module_whitelist(
                "any.module",
                whitelist=None,
                context="test_none",
            )

    def test_custom_empty_message(self) -> None:
        custom_msg = "Custom empty whitelist message"
        with pytest.raises(PermissionError, match=custom_msg):
            validate_module_whitelist(
                "any.module",
                whitelist=[],
                context="test_custom_msg",
                empty_message=custom_msg,
            )


class TestValidateModuleWhitelistDeniedSuffix:
    """denied_suffix — additional context in error message."""

    def test_denied_suffix_in_error(self) -> None:
        with pytest.raises(PermissionError, match=r"\(called from X\)"):
            validate_module_whitelist(
                "dangerous.module",
                whitelist=["safe.*"],
                context="test",
                denied_suffix=" (called from X)",
            )


class TestValidateModuleWhitelistContextPrefix:
    """context — prefix in error message."""

    def test_context_in_error_message(self) -> None:
        with pytest.raises(PermissionError, match="SkillRegistry"):
            validate_module_whitelist(
                "dangerous.subprocess",
                whitelist=["src.backend.safe.*"],
                context="SkillRegistry.invoke",
            )


class TestValidateModuleWhitelistRejectsNonWhitelisted:
    """Modules not in whitelist → PermissionError."""

    @pytest.mark.parametrize(
        "module_name",
        [
            "subprocess",
            "os.system",
            "pickle.loads",
            "eval",
            "exec",
            "__import__",
        ],
    )
    def test_dangerous_module_rejected(self, module_name: str) -> None:
        """Critical security check: dangerous builtins/modules rejected."""
        with pytest.raises(PermissionError):
            validate_module_whitelist(
                module_name,
                whitelist=["src.backend.safe.*"],
                context="security_test",
            )