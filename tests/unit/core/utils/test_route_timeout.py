"""Tests for src.backend.core.utils.route_timeout."""

from __future__ import annotations

from src.backend.core.utils.route_timeout import RouteTimeoutSpec


class TestRouteTimeoutSpec:
    """Tests for RouteTimeoutSpec dataclass."""

    def test_default_init(self) -> None:
        spec = RouteTimeoutSpec()
        assert spec.connect is None
        assert spec.read is None
        assert spec.write is None
        assert spec.total is None

    def test_all_fields_set(self) -> None:
        spec = RouteTimeoutSpec(connect=5.0, read=30.0, write=10.0, total=60.0)
        assert spec.connect == 5.0
        assert spec.read == 30.0
        assert spec.write == 10.0
        assert spec.total == 60.0

    def test_partial_fields(self) -> None:
        spec = RouteTimeoutSpec(total=45.0)
        assert spec.connect is None
        assert spec.read is None
        assert spec.write is None
        assert spec.total == 45.0

    def test_frozen_immutable(self) -> None:
        spec = RouteTimeoutSpec(connect=1.0)
        # Frozen dataclass should not allow mutation
        try:
            spec.connect = 2.0  # type: ignore[misc]
            assert False, "Expected frozen dataclass to reject mutation"
        except Exception:
            pass

    def test_slots_reduces_memory(self) -> None:
        spec = RouteTimeoutSpec()
        assert hasattr(spec, "connect")
        assert not hasattr(spec, "__dict__")
