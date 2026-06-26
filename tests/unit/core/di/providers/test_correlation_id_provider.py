"""TDD: infrastructure_facade.get_correlation_id должен возвращать value (S171 M12 R4 #3).

Per D102 (single-source-of-truth through facade), infrastructure_facade
должен возвращать value из underlying function, а не саму function.

Текущий bug (M12 R4 #3): facade.get_correlation_id() возвращает
``<function get_correlation_id>`` вместо строки, что ломает audit_service.emit
(test_emit_uses_correlation_id_from_contextvar).
"""
# ruff: noqa: S101
from __future__ import annotations

import pytest


class TestCorrelationIdProvider:
    def test_returns_string_not_function(self) -> None:
        """Facade должен возвращать str, а не callable."""
        from src.backend.core.di.providers.infrastructure_facade import (
            get_correlation_id,
        )
        result = get_correlation_id()
        assert isinstance(result, str), (
            f"facade должен возвращать str, получил {type(result).__name__}: {result!r}"
        )

    def test_returns_default_when_no_context(self) -> None:
        """Без contextvar — возвращает default ('' по умолчанию)."""
        from src.backend.core.di.providers.infrastructure_facade import (
            get_correlation_id,
        )
        result = get_correlation_id()
        # Default в correlation_id_var — пустая строка
        assert result == ""

    def test_returns_contextvar_value(self) -> None:
        """С contextvar 'corr-xyz' — возвращает 'corr-xyz'."""
        from src.backend.core.di.providers.infrastructure_facade import (
            get_correlation_id,
        )
        from src.backend.infrastructure.observability.correlation import (
            correlation_id_var,
        )
        token = correlation_id_var.set("corr-xyz")
        try:
            assert get_correlation_id() == "corr-xyz"
        finally:
            correlation_id_var.reset(token)
