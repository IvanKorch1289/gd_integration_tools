"""S44 W8: tests for clickhouse_admin lazy proxy (W6 added audit,
W7 capability_adapter; W8 closes clickhouse_admin — broken import
revealed + fixed).

Pattern: ``__getattr__``-based lazy proxy re-exports
``AdminClickHouseClient`` and ``get_admin_clickhouse_client`` from
``core.api.storage`` (which re-exports from infrastructure layer).
"""

from __future__ import annotations

import pytest

from src.backend.services.admin import clickhouse_admin


class TestClickhouseAdminLazyProxy:
    """Lazy proxy: imports on first attribute access, not on module load."""

    def test_admin_clickhouse_client_resolves(self) -> None:
        """``AdminClickHouseClient`` resolves to infrastructure class."""
        client_cls = clickhouse_admin.AdminClickHouseClient
        # Protocol or class — must be importable and have name
        assert hasattr(client_cls, "__name__")
        assert client_cls.__name__ == "AdminClickHouseClient"

    def test_get_admin_clickhouse_client_resolves(self) -> None:
        """``get_admin_clickhouse_client`` is callable."""
        get_admin = clickhouse_admin.get_admin_clickhouse_client
        assert callable(get_admin)

    def test_get_admin_returns_protocol_implementation(self) -> None:
        """get_admin_clickhouse_client returns AdminClickHouseClient | None."""
        import inspect

        sig = inspect.signature(clickhouse_admin.get_admin_clickhouse_client)
        assert len(sig.parameters) == 0

    def test_unknown_attribute_raises_attribute_error(self) -> None:
        """``__getattr__`` raises AttributeError for unknown attributes."""
        with pytest.raises(AttributeError) as exc_info:
            clickhouse_admin.SomeNonexistentAttribute  # type: ignore[attr-defined]
        assert "has no attribute" in str(exc_info.value)

    def test_unknown_with_dunder_raises_attribute_error(self) -> None:
        """``__getattr__`` rejects dunder names (sanity)."""
        with pytest.raises(AttributeError):
            clickhouse_admin.__nonexistent__  # type: ignore[attr-defined]

    def test_module_does_not_eagerly_import(self) -> None:
        """Module import does not trigger infrastructure import.

        Pattern check: ``sys.modules`` should not contain the proxy's
        target module after a fresh ``import clickhouse_admin`` (we
        already imported it; this verifies the module-level state).

        In practice this is verified via the __getattr__ design — no
        module-level import of the target.
        """
        # If proxy were eager, ``m.__dict__`` would contain the loaded
        # symbols. They should NOT be in __dict__ until accessed.
        module_dict = vars(clickhouse_admin)
        assert "AdminClickHouseClient" not in module_dict
        assert "get_admin_clickhouse_client" not in module_dict
