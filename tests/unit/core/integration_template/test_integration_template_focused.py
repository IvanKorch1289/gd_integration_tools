"""Focused tests for ``core.integration_template`` (Wave 2 DX #58-#59)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.backend.core.integration_template import (
    GenerationResult,
    Template,
    TemplateCatalog,
    TemplateFile,
    TemplateGenerator,
    get_template_catalog,
    get_template_generator,
)
from src.backend.core.integration_template.catalog import (
    reset_template_catalog,
)
from src.backend.core.integration_template.generator import (
    GeneratedFile,
    reset_template_generator,
)


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_template_catalog()
    reset_template_generator()


class TestTemplateFile:
    def test_init_defaults(self) -> None:
        f = TemplateFile(path="x.txt", content="hello")
        assert f.executable is False

    def test_init_executable(self) -> None:
        f = TemplateFile(path="run.sh", content="#!/bin/sh", executable=True)
        assert f.executable is True


class TestTemplate:
    def test_init_defaults(self) -> None:
        t = Template(name="t", description="d", category="c")
        assert t.files == []
        assert t.variables == []
        assert t.tags == []

    def test_init_with_all(self) -> None:
        t = Template(
            name="t",
            description="d",
            category="c",
            files=[TemplateFile(path="x", content="y")],
            variables=["a", "b"],
            tags=["t1"],
        )
        assert len(t.files) == 1
        assert t.variables == ["a", "b"]


class TestTemplateCatalogInit:
    def test_init_empty(self) -> None:
        c = TemplateCatalog()
        assert c.size() == 0


class TestCatalogRegister:
    def test_register(self) -> None:
        c = TemplateCatalog()
        t = Template(name="t1", description="d", category="c")
        c.register(t)
        assert c.size() == 1

    def test_register_overwrite(self) -> None:
        c = TemplateCatalog()
        t1 = Template(name="dup", description="d1", category="c")
        t2 = Template(name="dup", description="d2", category="c")
        c.register(t1)
        c.register(t2)
        assert c.size() == 1
        assert c.get("dup").description == "d2"


class TestCatalogGet:
    def test_get_existing(self) -> None:
        c = TemplateCatalog()
        t = Template(name="t", description="d", category="c")
        c.register(t)
        assert c.get("t") is t

    def test_get_missing(self) -> None:
        c = TemplateCatalog()
        assert c.get("missing") is None


class TestCatalogList:
    def test_list_all(self) -> None:
        c = TemplateCatalog()
        c.register(Template(name="a", description="d", category="c"))
        c.register(Template(name="b", description="d", category="c"))
        assert len(c.list_all()) == 2

    def test_list_by_category(self) -> None:
        c = TemplateCatalog()
        c.register(Template(name="a", description="d", category="api"))
        c.register(Template(name="b", description="d", category="cdc"))
        result = c.list_by_category("api")
        assert len(result) == 1

    def test_list_by_tag(self) -> None:
        c = TemplateCatalog()
        c.register(Template(name="a", description="d", category="c", tags=["t1"]))
        c.register(Template(name="b", description="d", category="c", tags=["t2"]))
        result = c.list_by_tag("t1")
        assert len(result) == 1


class TestCatalogClear:
    def test_clear(self) -> None:
        c = TemplateCatalog()
        c.register(Template(name="a", description="d", category="c"))
        c.clear()
        assert c.size() == 0


class TestCatalogDefaultTemplates:
    """Singleton ``get_template_catalog()`` returns default templates."""

    def test_default_registration(self) -> None:
        catalog = get_template_catalog()
        assert catalog.size() >= 4  # api_ingest, cdc_enrich, file_watch, saga
        assert catalog.get("api_ingest") is not None
        assert catalog.get("cdc_enrich") is not None
        assert catalog.get("file_watch") is not None
        assert catalog.get("saga_compensation") is not None


class TestGeneratorRender:
    def test_render_basic(self) -> None:
        gen = TemplateGenerator()
        result = gen._render("Hello {{name}}!", {"name": "World"})
        assert result == "Hello World!"

    def test_render_with_whitespace(self) -> None:
        gen = TemplateGenerator()
        result = gen._render("{{ a }}", {"a": "x"})
        assert result == "x"

    def test_render_missing_raises(self) -> None:
        gen = TemplateGenerator()
        with pytest.raises(KeyError):
            gen._render("{{missing}}", {})

    def test_render_no_vars(self) -> None:
        gen = TemplateGenerator()
        assert gen._render("no vars here", {}) == "no vars here"


class TestGeneratorGenerate:
    def test_basic_generation(self, tmp_path: Path) -> None:
        gen = TemplateGenerator()
        template = Template(
            name="t",
            description="d",
            category="test",
            variables=["route_id", "owner"],
            files=[
                TemplateFile(
                    path="route.toml",
                    content="id = \"{{route_id}}\"\nowner = \"{{owner}}\"\n",
                ),
                TemplateFile(
                    path="README.md",
                    content="# {{route_id}}\nOwner: {{owner}}\n",
                ),
            ],
        )
        result = gen.generate(
            template=template,
            variables={"route_id": "r1", "owner": "team-x"},
            target_dir=tmp_path / "out",
        )
        assert result.success is True
        assert len(result.files) == 2
        assert (tmp_path / "out" / "route.toml").exists()
        assert (tmp_path / "out" / "README.md").exists()
        # Verify content.
        assert "r1" in (tmp_path / "out" / "route.toml").read_text()
        assert "team-x" in (tmp_path / "out" / "README.md").read_text()

    def test_missing_variables(self, tmp_path: Path) -> None:
        gen = TemplateGenerator()
        template = Template(
            name="t",
            description="d",
            category="test",
            variables=["route_id"],
            files=[TemplateFile(path="x", content="y")],
        )
        result = gen.generate(
            template=template, variables={}, target_dir=tmp_path / "out"
        )
        assert result.success is False
        assert "route_id" in result.missing_variables

    def test_skip_existing_no_overwrite(self, tmp_path: Path) -> None:
        gen = TemplateGenerator()
        existing = tmp_path / "existing.txt"
        existing.write_text("original")
        template = Template(
            name="t",
            description="d",
            category="test",
            variables=[],
            files=[TemplateFile(path="existing.txt", content="new")],
        )
        result = gen.generate(
            template=template, variables={}, target_dir=tmp_path, overwrite=False
        )
        # Existing file unchanged.
        assert existing.read_text() == "original"

    def test_overwrite(self, tmp_path: Path) -> None:
        gen = TemplateGenerator()
        existing = tmp_path / "existing.txt"
        existing.write_text("original")
        template = Template(
            name="t",
            description="d",
            category="test",
            variables=[],
            files=[TemplateFile(path="existing.txt", content="new")],
        )
        result = gen.generate(
            template=template, variables={}, target_dir=tmp_path, overwrite=True
        )
        assert existing.read_text() == "new"

    def test_nested_path(self, tmp_path: Path) -> None:
        gen = TemplateGenerator()
        template = Template(
            name="t",
            description="d",
            category="test",
            variables=[],
            files=[TemplateFile(path="subdir/nested/file.txt", content="data")],
        )
        result = gen.generate(
            template=template, variables={}, target_dir=tmp_path
        )
        assert (tmp_path / "subdir" / "nested" / "file.txt").exists()

    def test_executable(self, tmp_path: Path) -> None:
        gen = TemplateGenerator()
        template = Template(
            name="t",
            description="d",
            category="test",
            variables=[],
            files=[TemplateFile(path="run.sh", content="#!/bin/sh\necho", executable=True)],
        )
        result = gen.generate(
            template=template, variables={}, target_dir=tmp_path
        )
        f = tmp_path / "run.sh"
        assert f.exists()
        # Executable bit set.
        import stat
        assert f.stat().st_mode & stat.S_IXUSR


class TestGeneratedFile:
    def test_defaults(self) -> None:
        f = GeneratedFile(
            path="x", absolute_path="/abs/x", size_bytes=100
        )
        assert f.executable is False


class TestGenerationResult:
    def test_defaults(self) -> None:
        r = GenerationResult(template_name="t", target_dir="/tmp")
        assert r.files == []
        assert r.missing_variables == []
        assert r.success is True


class TestSingleton:
    def test_catalog_singleton(self) -> None:
        c1 = get_template_catalog()
        c2 = get_template_catalog()
        assert c1 is c2

    def test_generator_singleton(self) -> None:
        g1 = get_template_generator()
        g2 = get_template_generator()
        assert g1 is g2


class TestExports:
    def test_module_all(self) -> None:
        from src.backend.core import integration_template

        assert len(integration_template.__all__) == 7


class TestRealisticExample:
    def test_generate_api_ingest_route(self, tmp_path: Path) -> None:
        """End-to-end: get template → render → verify files."""
        catalog = get_template_catalog()
        generator = get_template_generator()

        template = catalog.get("api_ingest")
        assert template is not None

        result = generator.generate(
            template=template,
            variables={
                "route_id": "order-create",
                "owner": "team-payments",
                "source_url": "https://api.example.com/orders",
                "webhook_url": "https://hooks.example.com/notify",
            },
            target_dir=tmp_path / "extensions" / "order-create",
        )
        assert result.success is True
        # route.toml + test + README = 3 files.
        assert len(result.files) == 3

        # Verify route.toml.
        route_toml = (tmp_path / "extensions" / "order-create" / "route.toml").read_text()
        assert "order-create" in route_toml
        assert "team-payments" in route_toml
        assert "https://api.example.com/orders" in route_toml
        assert "events.order-create.dlq" in route_toml

        # Verify test file.
        test_file = (tmp_path / "extensions" / "order-create" / "test_order-create.py").read_text()
        assert "order-create" in test_file
