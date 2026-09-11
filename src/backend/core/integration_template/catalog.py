"""Template Catalog — registry готовых templates."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ("Template", "TemplateCatalog", "TemplateFile", "get_template_catalog")


@dataclass(slots=True)
class TemplateFile:
    """Файл внутри template."""

    path: str  # Relative path внутри target dir.
    content: str  # File content (with {{variables}}).
    executable: bool = False  # chmod +x


@dataclass(slots=True)
class Template:
    """Один template."""

    name: str
    description: str
    category: str  # "api", "cdc", "file", "saga", ...
    files: list[TemplateFile] = field(default_factory=list)
    variables: list[str] = field(default_factory=list)  # required {{var}} names
    tags: list[str] = field(default_factory=list)


class TemplateCatalog:
    """Registry templates."""

    def __init__(self) -> None:
        self._templates: dict[str, Template] = {}

    def register(self, template: Template) -> None:
        if template.name in self._templates:
            logger.warning(
                "TemplateCatalog: overwriting template name=%s", template.name
            )
        self._templates[template.name] = template

    def get(self, name: str) -> Template | None:
        return self._templates.get(name)

    def list_all(self) -> list[Template]:
        return list(self._templates.values())

    def list_by_category(self, category: str) -> list[Template]:
        return [t for t in self._templates.values() if t.category == category]

    def list_by_tag(self, tag: str) -> list[Template]:
        return [t for t in self._templates.values() if tag in t.tags]

    def size(self) -> int:
        return len(self._templates)

    def clear(self) -> None:
        self._templates.clear()


_catalog: TemplateCatalog | None = None


def get_template_catalog() -> TemplateCatalog:
    global _catalog
    if _catalog is None:
        _catalog = TemplateCatalog()
        _register_default_templates(_catalog)
    return _catalog


def reset_template_catalog() -> None:
    global _catalog
    _catalog = None


def _register_default_templates(catalog: TemplateCatalog) -> None:
    """Register built-in templates."""

    # api_ingest template.
    api_ingest = Template(
        name="api_ingest",
        description="REST API ingestion → normalize → DB → webhook notification",
        category="api",
        variables=["route_id", "owner", "source_url", "webhook_url"],
        tags=["api", "webhook"],
        files=[
            TemplateFile(
                path="route.toml",
                content="""[route]
id = "{{route_id}}"
source = "timer:60s|api={{source_url}}"
description = "API ingestion from {{source_url}}"
owner = "{{owner}}"

[contract]
timeout_seconds = 30
idempotency_key_field = "request_id"
dlq_topic = "events.{{route_id}}.dlq"

[security]
requires_permission = "api.read.{{route_id}}"
""",
            ),
            TemplateFile(
                path="test_{{route_id}}.py",
                content='''"""Contract tests для {{route_id}}."""

import pytest
from src.backend.core.contract_testing import ContractTestCase, ContractTestHarness


@pytest.fixture
def harness() -> ContractTestHarness:
    return ContractTestHarness()


def test_route_contract(harness: ContractTestHarness) -> None:
    """Smoke test для {{route_id}}."""
    # Add contract tests here.
    assert True
''',
            ),
            TemplateFile(
                path="README.md",
                content="# {{route_id}}\n\nREST API integration owned by {{owner}}.\n",
            ),
        ],
    )
    catalog.register(api_ingest)

    # cdc_enrich template.
    cdc_enrich = Template(
        name="cdc_enrich",
        description="CDC source → enrich via HTTP → publish to MQ",
        category="cdc",
        variables=["route_id", "owner", "cdc_source", "enrichment_url"],
        tags=["cdc", "enrichment"],
        files=[
            TemplateFile(
                path="route.toml",
                content="""[route]
id = "{{route_id}}"
source = "{{cdc_source}}"
description = "CDC enrich from {{cdc_source}}"
owner = "{{owner}}"

[contract]
timeout_seconds = 15
idempotency_key_field = "cdc_lsn"
dlq_topic = "events.{{route_id}}.dlq"
""",
            ),
        ],
    )
    catalog.register(cdc_enrich)

    # file_watch template.
    file_watch = Template(
        name="file_watch",
        description="File watcher → validate → action",
        category="file",
        variables=["route_id", "owner", "watch_path", "file_glob"],
        tags=["file", "watcher"],
        files=[
            TemplateFile(
                path="route.toml",
                content="""[route]
id = "{{route_id}}"
source = "filewatcher:{{watch_path}}?glob={{file_glob}}"
description = "File watch {{watch_path}}/{{file_glob}}"
owner = "{{owner}}"

[contract]
timeout_seconds = 60
""",
            ),
        ],
    )
    catalog.register(file_watch)

    # saga_compensation template.
    saga = Template(
        name="saga_compensation",
        description="Saga pattern с retry + compensation",
        category="saga",
        variables=["route_id", "owner", "request_url", "compensate_url"],
        tags=["saga", "compensation"],
        files=[
            TemplateFile(
                path="route.toml",
                content="""[route]
id = "{{route_id}}"
source = "action:{{route_id}}"
description = "Saga {{request_url}} → {{compensate_url}}"
owner = "{{owner}}"

[contract]
timeout_seconds = 30
retry_policy = "exponential"
max_retries = 3
dlq_topic = "events.{{route_id}}.dlq"
""",
            ),
        ],
    )
    catalog.register(saga)
