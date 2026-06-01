"""Unit-тесты :class:`RouteTimeoutSpec` + manifest [timeout] + PolicyChain (S18 W6).

Покрытие:
    * RouteTimeoutSpec frozen dataclass (immutable, slots).
    * RouteManifestV11 парсит ``[timeout]`` секцию.
    * RouteManifestV11 без ``[timeout]`` → ``manifest.timeout is None``.
    * Невалидный timeout (отрицательный) → RouteManifestError.
    * PolicyChain.timeout(seconds=X) — backward-compat alias для total.
    * PolicyChain.timeout(total=X) — основной keyword.
    * PolicyChain.timeout(connect=, read=, write=, total=) — все 4 поля.
    * PolicyChain.timeout(seconds=X, total=Y) — ValueError (mutually exclusive).
"""

# ruff: noqa: S101

from __future__ import annotations

from pathlib import Path

import pytest

from src.backend.core.config.features import feature_flags
from src.backend.core.utils.route_timeout import RouteTimeoutSpec
from src.backend.services.routes.manifest_v11 import (
    RouteManifestError,
    load_route_manifest,
)

# ----------------------------- RouteTimeoutSpec ----------------------------


class TestRouteTimeoutSpec:
    """Frozen dataclass: 4 optional float fields."""

    def test_default_all_none(self) -> None:
        spec = RouteTimeoutSpec()
        assert spec.connect is None
        assert spec.read is None
        assert spec.write is None
        assert spec.total is None

    def test_partial_init(self) -> None:
        spec = RouteTimeoutSpec(total=30.0)
        assert spec.total == 30.0
        assert spec.connect is None

    def test_frozen(self) -> None:
        spec = RouteTimeoutSpec(total=10.0)
        with pytest.raises((AttributeError, TypeError)):
            spec.total = 20.0  # type: ignore[misc]


# ----------------------------- manifest [timeout] --------------------------


_VALID_MANIFEST = """
name = "demo_route"
version = "1.0.0"
requires_core = ">=0.1,<2.0"
pipelines = ["demo.dsl.yaml"]

[timeout]
connect = 1.0
read = 5.0
write = 5.0
total = 30.0
"""

_MANIFEST_WITHOUT_TIMEOUT = """
name = "no_timeout"
version = "1.0.0"
requires_core = ">=0.1,<2.0"
pipelines = ["demo.dsl.yaml"]
"""

_MANIFEST_NEGATIVE_TIMEOUT = """
name = "bad_timeout"
version = "1.0.0"
requires_core = ">=0.1,<2.0"
pipelines = ["demo.dsl.yaml"]

[timeout]
total = -5.0
"""


def _write_manifest(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "route.toml"
    p.write_text(content, encoding="utf-8")
    return p


class TestManifestTimeoutParsing:
    """RouteManifestV11.timeout parsing из ``route.toml``."""

    def test_parses_full_timeout_block(self, tmp_path: Path) -> None:
        path = _write_manifest(tmp_path, _VALID_MANIFEST)
        manifest = load_route_manifest(path)
        assert manifest.timeout is not None
        assert manifest.timeout.connect == 1.0
        assert manifest.timeout.read == 5.0
        assert manifest.timeout.write == 5.0
        assert manifest.timeout.total == 30.0

    def test_to_spec_conversion(self, tmp_path: Path) -> None:
        """_RouteTimeoutModel.to_spec() конвертирует в RouteTimeoutSpec."""
        path = _write_manifest(tmp_path, _VALID_MANIFEST)
        manifest = load_route_manifest(path)
        assert manifest.timeout is not None
        spec = manifest.timeout.to_spec()
        assert isinstance(spec, RouteTimeoutSpec)
        assert spec.total == 30.0

    def test_missing_timeout_block_is_none(self, tmp_path: Path) -> None:
        path = _write_manifest(tmp_path, _MANIFEST_WITHOUT_TIMEOUT)
        manifest = load_route_manifest(path)
        assert manifest.timeout is None

    def test_negative_timeout_rejected(self, tmp_path: Path) -> None:
        path = _write_manifest(tmp_path, _MANIFEST_NEGATIVE_TIMEOUT)
        with pytest.raises(RouteManifestError):
            load_route_manifest(path)


# ----------------------------- PolicyChain.timeout -------------------------


class TestPolicyChainTimeout:
    """PolicyChain.timeout extended signature + backward-compat."""

    @pytest.fixture(autouse=True)
    def _enable_chainable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            feature_flags, "policy_chainable_enabled", True
        )

    def _builder(self) -> object:
        # Минимальный stub builder с _processors атрибутом.
        from src.backend.dsl.builders.policy_mixin import PolicyChain

        class _Stub:
            def __init__(self) -> None:
                self._processors: list = []

        stub = _Stub()
        return PolicyChain(stub)  # type: ignore[arg-type]

    def test_legacy_seconds_alias(self) -> None:
        """S5 W7 backward-compat: .timeout(seconds=X) → total=X."""
        chain = self._builder()
        builder = chain.timeout(seconds=10.0)
        marker = builder._processors[-1]
        assert marker.policy_name == "timeout"
        assert marker.params["total"] == 10.0
        assert marker.params["seconds"] == 10.0  # legacy field name

    def test_total_kwarg(self) -> None:
        chain = self._builder()
        builder = chain.timeout(total=20.0)
        marker = builder._processors[-1]
        assert marker.params["total"] == 20.0

    def test_all_four_fields(self) -> None:
        chain = self._builder()
        builder = chain.timeout(connect=1.0, read=5.0, write=5.0, total=30.0)
        marker = builder._processors[-1]
        assert marker.params["connect"] == 1.0
        assert marker.params["read"] == 5.0
        assert marker.params["write"] == 5.0
        assert marker.params["total"] == 30.0

    def test_seconds_and_total_mutually_exclusive(self) -> None:
        chain = self._builder()
        with pytest.raises(ValueError, match="seconds.*total"):
            chain.timeout(seconds=10.0, total=20.0)

    def test_no_args_default_30s(self) -> None:
        """Backward-compat: legacy signature `timeout()` без args → 30.0s."""
        chain = self._builder()
        builder = chain.timeout()
        marker = builder._processors[-1]
        assert marker.params["total"] == 30.0
        assert marker.params["seconds"] == 30.0
