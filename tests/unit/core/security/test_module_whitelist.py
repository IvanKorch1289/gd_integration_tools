"""Unit-тесты общей проверки module whitelist."""

from __future__ import annotations

import pytest

from src.backend.core.security.module_whitelist import validate_module_whitelist


@pytest.mark.unit
class TestValidateModuleWhitelist:
    """Проверяет exact-match, namespace wildcard и fail-closed режимы."""

    def test_exact_module_match_is_allowed(self) -> None:
        """Точное имя модуля из whitelist разрешается."""
        validate_module_whitelist(
            "extensions.credit.functions", ["extensions.credit.functions"]
        )

    def test_namespace_wildcard_allows_only_descendants(self) -> None:
        """Шаблон ``prefix.*`` не разрешает сам prefix и соседний namespace."""
        validate_module_whitelist(
            "extensions.credit.functions", ["extensions.credit.*"]
        )

        with pytest.raises(PermissionError, match="not in whitelist"):
            validate_module_whitelist("extensions.credit", ["extensions.credit.*"])
        with pytest.raises(PermissionError, match="not in whitelist"):
            validate_module_whitelist(
                "extensions.credits.functions", ["extensions.credit.*"]
            )

    def test_empty_whitelist_can_preserve_explicit_dev_fallback(self) -> None:
        """Режим ``empty_mode=allow`` сохраняет явный dev fallback."""
        validate_module_whitelist("anything.module", [], empty_mode="allow")

    def test_empty_whitelist_uses_caller_error_contract(self) -> None:
        """Вызывающий код может сохранить свой тип и текст ошибки."""
        with pytest.raises(ValueError, match="skill-1"):
            validate_module_whitelist(
                "anything.module",
                [],
                context="SkillRegistry._validate_module_whitelist",
                empty_error=ValueError,
                empty_message="empty whitelist for skill-1",
            )

    def test_denial_keeps_context_and_suffix(self) -> None:
        """Отказ содержит контекст вызывающего слоя и его идентификатор."""
        with pytest.raises(PermissionError, match=r"skill-1"):
            validate_module_whitelist(
                "extensions.untrusted",
                ["extensions.trusted"],
                context="SkillRegistry.invoke",
                denied_suffix=" (skill-1)",
            )
