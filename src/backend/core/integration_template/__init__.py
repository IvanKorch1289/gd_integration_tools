"""Integration Template Catalog + Generator (Wave 2 DX #58-#59).

Проблема (EP-R1):
    Каждая новая интеграция начинается с нуля:
    - Копипаст route.toml, schema, тестов, документации.
    - Разные структуры → inconsistent code.
    - Долгий time-to-first-route (TTR).

Решение:
    ``TemplateCatalog`` + ``TemplateGenerator``:

    1. ``TemplateCatalog`` — registry готовых templates:
       - ``api_ingest`` — REST API → DB → webhook.
       - ``cdc_enrich`` — CDC → enrich → publish.
       - ``file_watch`` — file watcher → validate → action.
       - ``saga_compensation`` — Saga retry + compensation.
       - Custom templates (per-team).

    2. ``TemplateGenerator`` — render template в target dir:
       - Variable substitution ({{route_id}}, {{owner}}, ...).
       - Directory layout per template.
       - Files written atomically.

    3. ``generate(template_name, variables, target_dir)`` →
       ``GenerationResult`` с созданными файлами.

Использование::

    from src.backend.core.integration_template import (
        get_template_catalog, TemplateGenerator,
    )

    catalog = get_template_catalog()
    template = catalog.get("api_ingest")

    generator = TemplateGenerator()
    result = generator.generate(
        template=template,
        variables={"route_id": "order-create", "owner": "team-payments"},
        target_dir="./extensions/order-create",
    )
"""

from __future__ import annotations

from src.backend.core.integration_template.catalog import (
    Template,
    TemplateCatalog,
    TemplateFile,
    get_template_catalog,
)
from src.backend.core.integration_template.generator import (
    GenerationResult,
    TemplateGenerator,
    get_template_generator,
)

__all__ = (
    "GenerationResult",
    "Template",
    "TemplateCatalog",
    "TemplateFile",
    "TemplateGenerator",
    "get_template_catalog",
    "get_template_generator",
)
