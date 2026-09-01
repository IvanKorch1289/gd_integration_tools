"""Unit-тесты ``core.api.storage`` — coverage ratchet (S48 W19).

core/api/storage.py — Sprint 38 facade: re-exports
infrastructure.clients.storage (clickhouse, clickhouse_admin_client,
redis) для устранения services → infrastructure layer violations.
5 statements, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + module identity.
"""

from __future__ import annotations

import pytest

from src.backend.core.api import storage
from src.backend.core.api.storage import (
    Clickhouse,
    _redis,
    clickhouse,
    clickhouse_admin_client,
)


@pytest.mark.unit
class TestStorageFacadeAllExports:
    """``__all__`` audit + module identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        ["clickhouse", "clickhouse_admin_client", "_redis", "Clickhouse"],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(storage, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in storage.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 4 символа."""
        assert len(storage.__all__) == 4

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает Sprint 38 R13 FIX."""
        assert storage.__doc__ is not None
        assert "Sprint 38" in storage.__doc__


@pytest.mark.unit
class TestStorageFacadeIdentity:
    """Identity checks для re-exports."""

    def test_clickhouse_aliases_module(self) -> None:
        """``Clickhouse`` (capitalized) aliases ``clickhouse`` module."""
        assert Clickhouse is clickhouse

    def test_redis_module_importable(self) -> None:
        """``_redis`` module имеет стандартные атрибуты Redis-клиента."""
        # Не проверяем конкретные attrs (depends on redis version) — только
        # что модуль не None и importable.
        assert _redis is not None

    def test_clickhouse_module_importable(self) -> None:
        """``clickhouse`` module importable + has expected attrs."""
        assert clickhouse is not None
        assert hasattr(clickhouse, "get_clickhouse_client")

    def test_clickhouse_admin_client_module(self) -> None:
        """``clickhouse_admin_client`` module importable + has admin client."""
        assert clickhouse_admin_client is not None
        assert hasattr(clickhouse_admin_client, "get_admin_clickhouse_client")
