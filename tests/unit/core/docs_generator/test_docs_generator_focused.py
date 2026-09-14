"""Focused tests for ``core.docs_generator`` (Wave 2 DX #60)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.backend.core.docs_generator import DocsGenerator, get_docs_generator
from src.backend.core.docs_generator.generator import reset_docs_generator
from src.backend.core.registry_explorer import (
    ActionEntry,
    ConnectorEntry,
    RegistryExplorer,
    RouteEntry,
)


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_docs_generator()


@pytest.fixture
def populated_explorer() -> RegistryExplorer:
    """Registry with sample data."""
    e = RegistryExplorer()
    e.register_route(RouteEntry(
        id="order-create", source="timer:60s", owner="team-payments",
        timeout_seconds=30.0, tags=["prod", "critical"], tenant_id="t1",
    ))
    e.register_route(RouteEntry(
        id="dadata-enrich", source="action:order-create",
        owner="team-payments", timeout_seconds=5.0, tags=["prod"],
    ))
    e.register_route(RouteEntry(
        id="health-check", source="http://health",
        owner="team-sre", timeout_seconds=1.0, tags=["ops"],
    ))
    e.register_connector(ConnectorEntry(
        name="skb", category="external", auth="oauth2",
        base_url="https://skb.example.com/v1",
        version="1.0.0", owner="team-payments", tags=["prod", "critical"],
    ))
    e.register_connector(ConnectorEntry(
        name="dadata", category="external", auth="api_key",
        version="2.1.0", owner="team-payments", tags=["prod"],
    ))
    e.register_connector(ConnectorEntry(
        name="postgres", category="db", auth="none",
        version="15.0", owner="team-data", tags=["prod"],
    ))
    e.register_action(ActionEntry(
        name="orders.create", side_effect="write",
        owner="team-payments", params=["order_id", "amount"],
        tags=["write"],
    ))
    e.register_action(ActionEntry(
        name="customers.get_profile", side_effect="read",
        owner="team-payments", params=["customer_id"],
    ))
    return e


class TestDocsGeneratorInit:
    def test_init(self) -> None:
        g = DocsGenerator()
        assert g is not None


class TestGenerateRoutesMd:
    def test_empty(self) -> None:
        g = DocsGenerator()
        e = RegistryExplorer()
        md = g.generate_routes_md(e)
        assert "Total routes: **0**" in md
        assert "# Routes" in md

    def test_populated(self, populated_explorer: RegistryExplorer) -> None:
        g = DocsGenerator()
        md = g.generate_routes_md(populated_explorer)
        assert "Total routes: **3**" in md
        # Grouped by owner.
        assert "team-payments" in md
        assert "team-sre" in md
        # Contains route IDs.
        assert "order-create" in md
        assert "dadata-enrich" in md
        assert "health-check" in md

    def test_includes_auto_generated_marker(self, populated_explorer) -> None:
        g = DocsGenerator()
        md = g.generate_routes_md(populated_explorer)
        assert "Auto-generated" in md

    def test_includes_search_example(self, populated_explorer) -> None:
        g = DocsGenerator()
        md = g.generate_routes_md(populated_explorer)
        assert "```python" in md
        assert "search_routes" in md


class TestGenerateConnectorsMd:
    def test_empty(self) -> None:
        g = DocsGenerator()
        e = RegistryExplorer()
        md = g.generate_connectors_md(e)
        assert "Total connectors: **0**" in md

    def test_populated(self, populated_explorer) -> None:
        g = DocsGenerator()
        md = g.generate_connectors_md(populated_explorer)
        assert "Total connectors: **3**" in md
        # Grouped by category.
        assert "external" in md
        assert "db" in md
        # Connector names.
        assert "skb" in md
        assert "dadata" in md
        assert "postgres" in md

    def test_auth_rendered(self, populated_explorer) -> None:
        g = DocsGenerator()
        md = g.generate_connectors_md(populated_explorer)
        assert "oauth2" in md
        assert "api_key" in md


class TestGenerateActionsMd:
    def test_empty(self) -> None:
        g = DocsGenerator()
        e = RegistryExplorer()
        md = g.generate_actions_md(e)
        assert "Total actions: **0**" in md

    def test_populated(self, populated_explorer) -> None:
        g = DocsGenerator()
        md = g.generate_actions_md(populated_explorer)
        assert "Total actions: **2**" in md
        assert "orders.create" in md
        assert "customers.get_profile" in md
        assert "write" in md
        assert "read" in md

    def test_includes_params(self, populated_explorer) -> None:
        g = DocsGenerator()
        md = g.generate_actions_md(populated_explorer)
        assert "order_id" in md
        assert "amount" in md


class TestGenerateIndex:
    def test_index_with_sections(self) -> None:
        g = DocsGenerator()
        sections = {
            "routes": "# Routes\n\nAll routes.",
            "connectors": "# Connectors\n\nAll connectors.",
        }
        index = g.generate_index(sections)
        assert "# Generated Docs" in index
        assert "[Routes](routes/index.md)" in index
        assert "[Connectors](connectors/index.md)" in index


class TestExportDocs:
    def test_export(self, tmp_path: Path, populated_explorer) -> None:
        g = DocsGenerator()
        sections = {
            "routes": g.generate_routes_md(populated_explorer),
            "connectors": g.generate_connectors_md(populated_explorer),
            "actions": g.generate_actions_md(populated_explorer),
        }
        target = tmp_path / "docs" / "generated"
        written = g.export_docs(sections, target)
        # 3 section files + 1 top-level index.
        assert len(written) == 4
        assert (target / "routes" / "index.md").exists()
        assert (target / "connectors" / "index.md").exists()
        assert (target / "actions" / "index.md").exists()
        assert (target / "index.md").exists()

    def test_export_single_section(self, tmp_path: Path, populated_explorer) -> None:
        g = DocsGenerator()
        sections = {"routes": g.generate_routes_md(populated_explorer)}
        target = tmp_path / "docs"
        written = g.export_docs(sections, target)
        # 1 section, no top-level index.
        assert len(written) == 1
        assert not (target / "index.md").exists()

    def test_export_creates_dirs(self, tmp_path: Path, populated_explorer) -> None:
        g = DocsGenerator()
        sections = {"routes": g.generate_routes_md(populated_explorer)}
        target = tmp_path / "deeply" / "nested" / "out"
        g.export_docs(sections, target)
        assert (target / "routes" / "index.md").exists()


class TestSingleton:
    def test_singleton(self) -> None:
        g1 = get_docs_generator()
        g2 = get_docs_generator()
        assert g1 is g2

    def test_reset(self) -> None:
        g1 = get_docs_generator()
        reset_docs_generator()
        g2 = get_docs_generator()
        assert g1 is not g2


class TestExports:
    def test_module_all(self) -> None:
        from src.backend.core import docs_generator

        assert len(docs_generator.__all__) == 2


class TestRealisticExample:
    """End-to-end: populate explorer → generate docs → verify file contents."""

    def test_full_pipeline(self, tmp_path: Path) -> None:
        explorer = RegistryExplorer()
        # Routes.
        explorer.register_route(RouteEntry(
            id="order-create", source="timer:60s",
            owner="team-payments", timeout_seconds=30.0,
            tags=["prod"],
        ))
        # Connectors.
        explorer.register_connector(ConnectorEntry(
            name="skb", category="external", auth="oauth2",
            version="1.0", owner="team-payments",
        ))
        # Actions.
        explorer.register_action(ActionEntry(
            name="orders.create", side_effect="write",
            owner="team-payments",
        ))

        gen = DocsGenerator()
        sections = {
            "routes": gen.generate_routes_md(explorer),
            "connectors": gen.generate_connectors_md(explorer),
            "actions": gen.generate_actions_md(explorer),
        }
        target = tmp_path / "docs" / "generated"
        gen.export_docs(sections, target)

        # Verify file contents.
        routes_md = (target / "routes" / "index.md").read_text()
        assert "order-create" in routes_md
        assert "team-payments" in routes_md

        connectors_md = (target / "connectors" / "index.md").read_text()
        assert "skb" in connectors_md
        assert "oauth2" in connectors_md

        actions_md = (target / "actions" / "index.md").read_text()
        assert "orders.create" in actions_md

        index_md = (target / "index.md").read_text()
        assert "[Routes](routes/index.md)" in index_md
        assert "[Connectors](connectors/index.md)" in index_md
        assert "[Actions](actions/index.md)" in index_md
