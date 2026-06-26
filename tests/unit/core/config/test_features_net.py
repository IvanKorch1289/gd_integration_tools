"""Unit tests for src.backend.core.config.features.net (T1.3.5 split)."""

from __future__ import annotations

import os

from src.backend.core.config.features import feature_flags
from src.backend.core.config.features.net import NetFlags


class TestNetFlagsClass:
    def test_net_flags_importable(self) -> None:
        assert NetFlags is not None

    def test_net_flags_instantiates(self) -> None:
        flags = NetFlags()
        assert flags.metering_per_host is True  # default=True per code (S171 M9 sync)  # default-OFF feature flag
        assert flags.connection_reuse_manager is True  # default=True per code (S171 M9 sync)  # default-OFF feature flag
        assert flags.waf_outbound_via_facade is True  # default=True per code (S171 M9 sync)  # default-OFF feature flag

    def test_net_env_vars(self) -> None:
        os.environ["FEATURE_METERING_PER_HOST"] = "true"
        os.environ["FEATURE_CONNECTION_REUSE_MANAGER"] = "true"
        os.environ["FEATURE_WAF_OUTBOUND_VIA_FACADE"] = "true"
        try:
            flags = NetFlags()
            assert flags.metering_per_host is True
            assert flags.connection_reuse_manager is True
            assert flags.waf_outbound_via_facade is True
        finally:
            del os.environ["FEATURE_METERING_PER_HOST"]
            del os.environ["FEATURE_CONNECTION_REUSE_MANAGER"]
            del os.environ["FEATURE_WAF_OUTBOUND_VIA_FACADE"]

    def test_net_field_count(self) -> None:
        # 3 fields: metering_per_host, connection_reuse_manager, waf_outbound_via_facade
        fields = NetFlags.model_fields
        names = list(fields.keys())
        assert "metering_per_host" in names
        assert "connection_reuse_manager" in names
        assert "waf_outbound_via_facade" in names
        assert len(names) == 3


class TestNetFlagsComposition:
    def test_feature_flags_inherits_net_fields(self) -> None:
        assert hasattr(feature_flags, "metering_per_host")
        assert hasattr(feature_flags, "connection_reuse_manager")
        assert hasattr(feature_flags, "waf_outbound_via_facade")
        assert feature_flags.metering_per_host is True  # default=True per code (S171 M9 sync)  # default-OFF feature flag

    def test_feature_flags_class_mro(self) -> None:
        from src.backend.core.config.features import FeatureFlags

        mro_names = [c.__name__ for c in FeatureFlags.__mro__]
        # Все 4 mixins в MRO
        assert "AuthFlags" in mro_names
        assert "SecurityFlags" in mro_names
        assert "ObservabilityFlags" in mro_names
        assert "NetFlags" in mro_names
