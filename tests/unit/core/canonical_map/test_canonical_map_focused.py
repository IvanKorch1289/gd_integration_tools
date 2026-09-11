"""Focused tests for ``core.canonical_map`` (Wave 1 P0 #61)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.backend.core.canonical_map import (
    CanonicalMap,
    ImportRule,
    LayerRule,
    PathEntry,
    get_canonical_map,
)
from src.backend.core.canonical_map.map import reset_canonical_map


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_canonical_map()


class TestPathEntry:
    def test_init_defaults(self) -> None:
        e = PathEntry(path="x", responsibility="r")
        assert e.public_api == []
        assert e.layer == ""
        assert e.forbidden_imports == []
        assert e.tags == []

    def test_init_with_all(self) -> None:
        e = PathEntry(
            path="src/backend/core/idempotency",
            responsibility="Idempotency",
            public_api=["IdempotencyService"],
            layer="core",
            forbidden_imports=["src.backend.infrastructure.*"],
            tags=["core", "platform"],
        )
        assert e.public_api == ["IdempotencyService"]
        assert e.tags == ["core", "platform"]


class TestImportRule:
    def test_init_defaults(self) -> None:
        r = ImportRule(pattern="extensions.*")
        assert r.forbidden_imports == []
        assert r.reason == ""

    def test_init_with_values(self) -> None:
        r = ImportRule(
            pattern="extensions.*",
            forbidden_imports=["src.backend.infrastructure.*"],
            reason="extensions must go через core facade",
        )
        assert r.reason == "extensions must go через core facade"


class TestLayerRule:
    def test_init_defaults(self) -> None:
        r = LayerRule(name="core")
        assert r.allowed_imports == []
        assert r.forbidden_imports == []
        assert r.description == ""


class TestCanonicalMapInit:
    def test_init_empty(self) -> None:
        m = CanonicalMap()
        assert m.size() == 0
        assert m.rule_count() == 0
        assert m.layer_count() == 0


class TestRegisterPath:
    def test_register_basic(self) -> None:
        m = CanonicalMap()
        m.register_path(
            path="src/backend/core/idempotency",
            responsibility="Idempotency Service",
        )
        assert m.size() == 1
        assert m.get_path("src/backend/core/idempotency") is not None

    def test_register_with_all(self) -> None:
        m = CanonicalMap()
        m.register_path(
            path="x",
            responsibility="r",
            public_api=["A", "B"],
            layer="core",
            forbidden_imports=["y"],
            tags=["t1"],
        )
        entry = m.get_path("x")
        assert entry.public_api == ["A", "B"]
        assert entry.layer == "core"


class TestGetPath:
    def test_get_existing(self) -> None:
        m = CanonicalMap()
        m.register_path(path="x", responsibility="r")
        assert m.get_path("x") is not None

    def test_get_missing(self) -> None:
        m = CanonicalMap()
        assert m.get_path("missing") is None


class TestListPaths:
    def test_list_no_filters(self) -> None:
        m = CanonicalMap()
        m.register_path(path="a", responsibility="r")
        m.register_path(path="b", responsibility="r")
        assert len(m.list_paths()) == 2

    def test_list_filter_layer(self) -> None:
        m = CanonicalMap()
        m.register_path(path="a", responsibility="r", layer="core")
        m.register_path(path="b", responsibility="r", layer="infra")
        result = m.list_paths(layer="core")
        assert len(result) == 1
        assert result[0].path == "a"

    def test_list_filter_tag(self) -> None:
        m = CanonicalMap()
        m.register_path(path="a", responsibility="r", tags=["t1"])
        m.register_path(path="b", responsibility="r", tags=["t2"])
        result = m.list_paths(tag="t1")
        assert len(result) == 1


class TestAddRule:
    def test_add(self) -> None:
        m = CanonicalMap()
        m.add_rule(ImportRule(pattern="extensions.*"))
        assert m.rule_count() == 1


class TestAddLayer:
    def test_add(self) -> None:
        m = CanonicalMap()
        m.add_layer(LayerRule(name="core", description="Core layer"))
        assert m.layer_count() == 1

    def test_get_layer(self) -> None:
        m = CanonicalMap()
        m.add_layer(LayerRule(name="core"))
        assert m.get_layer("core") is not None
        assert m.get_layer("missing") is None


class TestCheckImport:
    def test_no_violations_no_rules(self) -> None:
        m = CanonicalMap()
        violations = m.check_import("extensions.x", "src.backend.infrastructure.y")
        assert violations == []

    def test_rule_match_forbidden(self) -> None:
        m = CanonicalMap()
        m.add_rule(
            ImportRule(
                pattern="^extensions\\..*",
                forbidden_imports=["^src\\.backend\\.infrastructure\\..*"],
                reason="extensions → infrastructure",
            )
        )
        violations = m.check_import(
            "extensions.my_plugin.x",
            "src.backend.infrastructure.foo",
        )
        assert len(violations) == 1
        assert "forbidden" in violations[0]
        assert "extensions → infrastructure" in violations[0]

    def test_rule_pattern_no_match(self) -> None:
        m = CanonicalMap()
        m.add_rule(ImportRule(pattern="^extensions\\..*", forbidden_imports=["x"]))
        violations = m.check_import("core.x", "y")
        assert violations == []

    def test_multiple_violations(self) -> None:
        m = CanonicalMap()
        m.add_rule(ImportRule(pattern="a", forbidden_imports=["b", "c"]))
        m.add_rule(ImportRule(pattern="a", forbidden_imports=["d"]))
        violations = m.check_import("a.x", "b.y")
        # 1 violation: rule1 (b). Rule2 (d) doesn't match b.y.
        assert len(violations) == 1
        # Target matching d → both rules trigger.
        violations2 = m.check_import("a.x", "d.y")
        assert len(violations2) == 1  # rule2 only (rule1's forbidden don't match d).


class TestCheckImportsOnDisk:
    def test_check_imports_empty_repo(self, tmp_path: Path) -> None:
        """``check_imports()`` сканирует project tree."""
        m = CanonicalMap()
        # Empty repo: no src/backend → returns empty.
        violations = m.check_imports(project_root=str(tmp_path))
        assert violations == []

    def test_check_imports_no_violations(self, tmp_path: Path) -> None:
        """No imports violate rules."""
        src = tmp_path / "src" / "backend"
        src.mkdir(parents=True)
        # core module without forbidden imports.
        (src / "core.py").write_text("x = 1\n")
        m = CanonicalMap()
        violations = m.check_imports(project_root=str(tmp_path))
        assert violations == []

    def test_check_imports_detects_violation(self, tmp_path: Path) -> None:
        """Import rule violation detected."""
        src = tmp_path / "src" / "backend"
        src.mkdir(parents=True)

        # extensions/plugin/x.py
        ext_dir = src / "extensions" / "plugin"
        ext_dir.mkdir(parents=True)
        (ext_dir / "__init__.py").write_text("")
        (ext_dir / "x.py").write_text(
            "from src.backend.infrastructure.foo import bar\n"
        )

        # infrastructure/foo.py
        infra_dir = src / "infrastructure"
        infra_dir.mkdir(parents=True)
        (infra_dir / "__init__.py").write_text("")
        (infra_dir / "foo.py").write_text("bar = 1\n")

        m = CanonicalMap()
        m.add_rule(
            ImportRule(
                pattern="^src\\.backend\\.extensions\\..*",
                forbidden_imports=["^src\\.backend\\.infrastructure\\..*"],
            )
        )
        violations = m.check_imports(project_root=str(tmp_path))
        assert any("forbidden" in v for v in violations)


class TestClear:
    def test_clear(self) -> None:
        m = CanonicalMap()
        m.register_path(path="x", responsibility="r")
        m.add_rule(ImportRule(pattern="x"))
        m.add_layer(LayerRule(name="core"))
        m.clear()
        assert m.size() == 0
        assert m.rule_count() == 0
        assert m.layer_count() == 0


class TestSingleton:
    def test_singleton(self) -> None:
        m1 = get_canonical_map()
        m2 = get_canonical_map()
        assert m1 is m2

    def test_reset(self) -> None:
        m1 = get_canonical_map()
        reset_canonical_map()
        m2 = get_canonical_map()
        assert m1 is not m2


class TestExports:
    def test_module_all(self) -> None:
        from src.backend.core import canonical_map

        assert len(canonical_map.__all__) == 5


class TestRealisticExample:
    def test_register_wave1_modules(self) -> None:
        """Register все Wave 1 P0 модули с их canonical placements."""
        m = get_canonical_map()

        # Core.
        m.register_path(
            path="src/backend/core/idempotency",
            responsibility="Idempotency Service для retry-safe writes",
            public_api=["IdempotencyService", "InMemoryIdempotencyBackend"],
            layer="core",
            tags=["wave1", "platform"],
        )
        m.register_path(
            path="src/backend/core/inbox",
            responsibility="Inbox pattern для consumer dedupe",
            public_api=["InboxService", "InMemoryInboxStore"],
            layer="core",
        )
        m.register_path(
            path="src/backend/core/dlq_replay",
            responsibility="DLQ Replay Cockpit + Failure Taxonomy",
            public_api=["DLQReplayService", "FailureTaxonomy"],
            layer="core",
        )

        # Layers.
        m.add_layer(LayerRule(
            name="core",
            allowed_imports=["core", "infrastructure"],
            forbidden_imports=["extensions", "services"],
        ))
        m.add_layer(LayerRule(
            name="extensions",
            allowed_imports=["core"],
            forbidden_imports=["infrastructure"],
        ))

        # Rule: extensions → infrastructure is forbidden.
        m.add_rule(ImportRule(
            pattern="^src\\.backend\\.extensions\\..*",
            forbidden_imports=["^src\\.backend\\.infrastructure\\..*"],
            reason="extensions must use core facades",
        ))

        # Lookup.
        idempotency = m.get_path("src/backend/core/idempotency")
        assert idempotency is not None
        assert "IdempotencyService" in idempotency.public_api

        # List core layer.
        core_modules = m.list_paths(layer="core")
        assert len(core_modules) == 3

        # Check violation.
        violations = m.check_import("src.backend.extensions.my.x", "src.backend.infrastructure.foo")
        assert len(violations) == 1
