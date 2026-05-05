# ruff: noqa: S101
"""Unit-тесты RouteManifestV11 (ADR-043 / ADR-044)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.backend.core.security.capabilities import CapabilityRef
from src.backend.services.routes.manifest_v11 import (
    RouteManifestError,
    RouteManifestV11,
    load_route_manifest,
)

VALID_TOML = """
name = "credit_pipeline"
version = "1.0.0"
requires_core = ">=0.2,<0.3"
tenant_aware = true
feature_flag = "ROUTE_CREDIT_PIPELINE_ENABLED"
tags = ["credit", "tier-1"]
pipelines = ["pipeline.dsl.yaml", "notify_cascade.dsl.yaml"]

[requires_plugins]
credit_pipeline = ">=1.0,<2.0"
bki_connector = ">=0.4,<1.0"

[[capabilities]]
name = "db.read"
scope = "credit_db"

[[capabilities]]
name = "net.outbound"
scope = "*.cbr.ru"
"""


class TestRouteManifestV11:
    def test_minimal_valid(self) -> None:
        m = RouteManifestV11(
            name="x", version="0.1.0", requires_core=">=0.1", pipelines=("p.dsl.yaml",)
        )
        assert m.requires_plugins == {}
        assert m.tenant_aware is False
        assert m.feature_flag is None
        assert m.tags == ()

    def test_full_construction(self) -> None:
        m = RouteManifestV11(
            name="credit",
            version="1.0.0",
            requires_core=">=0.2,<0.3",
            requires_plugins={"credit": ">=1.0,<2.0"},
            tenant_aware=True,
            feature_flag="ROUTE_CREDIT",
            tags=("credit",),
            pipelines=("p.dsl.yaml",),
            capabilities=(CapabilityRef(name="db.read", scope="credit_db"),),
        )
        assert m.feature_flag == "ROUTE_CREDIT"
        assert m.tags == ("credit",)

    def test_pipelines_required_non_empty(self) -> None:
        with pytest.raises(ValidationError):
            RouteManifestV11(
                name="x", version="1.0.0", requires_core=">=0.1", pipelines=()
            )

    def test_invalid_route_name(self) -> None:
        with pytest.raises(ValidationError):
            RouteManifestV11(
                name="Credit-Pipeline",
                version="1.0.0",
                requires_core=">=0.1",
                pipelines=("p.dsl.yaml",),
            )

    @pytest.mark.parametrize("bad_spec", ["NOT_A_SPEC", "@@@"])
    def test_invalid_requires_core(self, bad_spec: str) -> None:
        with pytest.raises(ValidationError):
            RouteManifestV11(
                name="x",
                version="1.0.0",
                requires_core=bad_spec,
                pipelines=("p.dsl.yaml",),
            )

    def test_invalid_requires_plugins_spec(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            RouteManifestV11(
                name="x",
                version="1.0.0",
                requires_core=">=0.1",
                requires_plugins={"foo": "NOT_A_SPEC"},
                pipelines=("p.dsl.yaml",),
            )
        assert "requires_plugins" in str(exc_info.value).lower()

    def test_feature_flag_accepts_bool(self) -> None:
        m = RouteManifestV11(
            name="x",
            version="1.0.0",
            requires_core=">=0.1",
            feature_flag=True,
            pipelines=("p.dsl.yaml",),
        )
        assert m.feature_flag is True

    def test_is_compatible_with_core(self) -> None:
        m = RouteManifestV11(
            name="x",
            version="1.0.0",
            requires_core=">=0.2,<0.3",
            pipelines=("p.dsl.yaml",),
        )
        assert m.is_compatible_with_core("0.2.5") is True
        assert m.is_compatible_with_core("0.3.0") is False

    def test_missing_plugins_returns_unmet(self) -> None:
        m = RouteManifestV11(
            name="x",
            version="1.0.0",
            requires_core=">=0.1",
            requires_plugins={"a": ">=1.0,<2.0", "b": ">=0.5"},
            pipelines=("p.dsl.yaml",),
        )
        # plugin "a" — installed and compatible; "b" — installed but
        # too low; "missing" doesn't exist.
        unmet = m.missing_plugins({"a": "1.5.0", "b": "0.4.0"})
        assert "a" not in unmet
        assert unmet["b"] == ">=0.5"

    def test_extra_field_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            RouteManifestV11.model_validate(
                {
                    "name": "x",
                    "version": "1.0.0",
                    "requires_core": ">=0.1",
                    "pipelines": ["p.dsl.yaml"],
                    "unknown": "boom",
                }
            )


class TestLoadRouteManifest:
    def test_load_valid_toml(self, tmp_path: Path) -> None:
        path = tmp_path / "route.toml"
        path.write_text(VALID_TOML, encoding="utf-8")
        m = load_route_manifest(path)
        assert m.name == "credit_pipeline"
        assert m.tenant_aware is True
        assert m.feature_flag == "ROUTE_CREDIT_PIPELINE_ENABLED"
        assert "credit_pipeline" in m.requires_plugins
        assert m.pipelines == ("pipeline.dsl.yaml", "notify_cascade.dsl.yaml")
        assert m.capabilities[1].name == "net.outbound"

    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(RouteManifestError, match="not found"):
            load_route_manifest(tmp_path / "absent.toml")

    def test_invalid_toml_syntax(self, tmp_path: Path) -> None:
        path = tmp_path / "route.toml"
        path.write_text("[broken", encoding="utf-8")
        with pytest.raises(RouteManifestError, match="Invalid TOML"):
            load_route_manifest(path)

    def test_invalid_schema(self, tmp_path: Path) -> None:
        path = tmp_path / "route.toml"
        path.write_text(
            'name = "x"\nversion = "1.0.0"\nrequires_core = ">=0.1"\n', encoding="utf-8"
        )
        with pytest.raises(RouteManifestError, match="validation failed"):
            load_route_manifest(path)
