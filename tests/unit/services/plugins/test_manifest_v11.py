# ruff: noqa: S101
"""Unit-тесты PluginManifestV11 + CapabilityRef (ADR-042 / ADR-044)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.core.security.capabilities import CAPABILITY_NAME_PATTERN, CapabilityRef
from src.services.plugins.manifest_v11 import (
    PluginManifestError,
    PluginManifestV11,
    PluginProvides,
    load_plugin_manifest,
)

VALID_TOML = """
name = "credit_pipeline"
version = "1.0.0"
requires_core = ">=0.2,<0.3"
entry_class = "extensions.credit_pipeline.plugin.CreditPipelinePlugin"
tenant_aware = true
description = "Кредитный конвейер"

[[capabilities]]
name = "db.read"
scope = "credit_db"

[[capabilities]]
name = "secrets.read"
scope = "vault://credit/*"

[provides]
actions = ["credit.score_application"]
processors = ["bki_normalizer"]

[config]
default_timeout_ms = 30000
"""


# ── CapabilityRef ─────────────────────────────────────────────────────


class TestCapabilityRef:
    def test_valid_name_with_scope(self) -> None:
        ref = CapabilityRef(name="db.read", scope="credit_db")
        assert ref.name == "db.read"
        assert ref.scope == "credit_db"

    def test_valid_name_without_scope(self) -> None:
        ref = CapabilityRef(name="net.outbound")
        assert ref.scope is None

    @pytest.mark.parametrize(
        "bad_name",
        [
            "db",  # нет verb
            "db.READ",  # uppercase
            "Db.read",  # uppercase resource
            ".read",  # пустой resource
            "db.",  # пустой verb
            "db..read",  # пустая часть
            "1db.read",  # начинается с цифры
            "db read",  # пробел
            "db.read.write",  # три сегмента
        ],
    )
    def test_invalid_name_grammar(self, bad_name: str) -> None:
        with pytest.raises(ValidationError) as exc_info:
            CapabilityRef(name=bad_name)
        assert (
            CAPABILITY_NAME_PATTERN in str(exc_info.value)
            or "match" in str(exc_info.value).lower()
        )

    def test_empty_scope_string_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CapabilityRef(name="db.read", scope="   ")

    def test_frozen(self) -> None:
        ref = CapabilityRef(name="db.read", scope="x")
        with pytest.raises(ValidationError):
            ref.scope = "y"  # type: ignore[misc]

    def test_extra_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            CapabilityRef.model_validate(
                {"name": "db.read", "scope": "x", "extra_key": "boom"}
            )


# ── PluginManifestV11 ─────────────────────────────────────────────────


class TestPluginManifestV11:
    def test_minimal_valid(self) -> None:
        m = PluginManifestV11(
            name="x", version="0.1.0", requires_core=">=0.1", entry_class="ext.x.Plugin"
        )
        assert m.tenant_aware is False
        assert m.capabilities == ()
        assert isinstance(m.provides, PluginProvides)
        assert m.config == {}

    def test_full_construction(self) -> None:
        m = PluginManifestV11(
            name="credit",
            version="1.0.0",
            requires_core=">=0.2,<0.3",
            entry_class="ext.credit.Plugin",
            tenant_aware=True,
            capabilities=(
                CapabilityRef(name="db.read", scope="credit_db"),
                CapabilityRef(name="net.outbound", scope="*.cbr.ru"),
            ),
            provides=PluginProvides(
                actions=("credit.score",), processors=("bki_normalizer",)
            ),
            config={"timeout": 30000},
        )
        assert len(m.capabilities) == 2
        assert m.provides.actions == ("credit.score",)

    @pytest.mark.parametrize(
        "bad_name", ["", "Credit", "credit-pipeline", "1credit", "credit pipeline"]
    )
    def test_invalid_plugin_name(self, bad_name: str) -> None:
        with pytest.raises(ValidationError):
            PluginManifestV11(
                name=bad_name,
                version="1.0.0",
                requires_core=">=0.1",
                entry_class="ext.x.Plugin",
            )

    @pytest.mark.parametrize(
        "bad_spec", ["NOT_A_SPEC", ">>>0.1", "@@1.0", "0.1.0..0.2.0"]
    )
    def test_invalid_requires_core(self, bad_spec: str) -> None:
        with pytest.raises(ValidationError) as exc_info:
            PluginManifestV11(
                name="x",
                version="1.0.0",
                requires_core=bad_spec,
                entry_class="ext.x.Plugin",
            )
        assert "requires_core" in str(exc_info.value).lower()

    def test_is_compatible_with_core_within_range(self) -> None:
        m = PluginManifestV11(
            name="x",
            version="1.0.0",
            requires_core=">=0.2,<0.3",
            entry_class="ext.x.Plugin",
        )
        assert m.is_compatible_with_core("0.2.5") is True
        assert m.is_compatible_with_core("0.3.0") is False
        assert m.is_compatible_with_core("0.1.9") is False

    def test_extra_field_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            PluginManifestV11.model_validate(
                {
                    "name": "x",
                    "version": "1.0.0",
                    "requires_core": ">=0.1",
                    "entry_class": "ext.x.Plugin",
                    "unknown": "value",
                }
            )


# ── load_plugin_manifest (TOML round-trip) ────────────────────────────


class TestLoadPluginManifest:
    def test_load_valid_toml(self, tmp_path: Path) -> None:
        path = tmp_path / "plugin.toml"
        path.write_text(VALID_TOML, encoding="utf-8")
        m = load_plugin_manifest(path)
        assert m.name == "credit_pipeline"
        assert m.tenant_aware is True
        assert m.is_compatible_with_core("0.2.0") is True
        assert m.capabilities[0].name == "db.read"
        assert m.provides.actions == ("credit.score_application",)

    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(PluginManifestError, match="not found"):
            load_plugin_manifest(tmp_path / "does_not_exist.toml")

    def test_invalid_toml_syntax(self, tmp_path: Path) -> None:
        path = tmp_path / "plugin.toml"
        path.write_text("name = 'x\nbad = ", encoding="utf-8")
        with pytest.raises(PluginManifestError, match="Invalid TOML"):
            load_plugin_manifest(path)

    def test_invalid_schema(self, tmp_path: Path) -> None:
        path = tmp_path / "plugin.toml"
        path.write_text(
            'name = "x"\nversion = "1.0.0"\n',  # no requires_core / entry_class
            encoding="utf-8",
        )
        with pytest.raises(PluginManifestError, match="validation failed"):
            load_plugin_manifest(path)

    def test_capability_name_grammar_in_toml(self, tmp_path: Path) -> None:
        path = tmp_path / "plugin.toml"
        path.write_text(
            'name = "x"\nversion = "1.0.0"\n'
            'requires_core = ">=0.1"\nentry_class = "ext.x.Plugin"\n'
            '[[capabilities]]\nname = "BAD_NAME"\nscope = "x"\n',
            encoding="utf-8",
        )
        with pytest.raises(PluginManifestError, match="validation failed"):
            load_plugin_manifest(path)
