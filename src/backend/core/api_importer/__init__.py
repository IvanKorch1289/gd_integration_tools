"""API Importer — OpenAPI/WSDL → connector/route draft generator (Wave 2 DX).

Проблема:
    Каждый connector пишется вручную на основе external API spec:
    - Нужно прочитать OpenAPI/Swagger doc.
    - Вручную извлечь paths, methods, parameters, schemas.
    - Сгенерировать connector metadata + route draft.

Решение:
    ``APIImporter`` — pure-Python parser + draft generator:

    1. ``import_openapi(spec)`` — parse OpenAPI 3.x JSON.
    2. ``import_swagger(spec)`` — parse Swagger 2.0 JSON.
    3. ``generate_connector_draft(imported)`` → BaseConnector metadata.
    4. ``generate_route_draft(imported)`` → Route draft (route.toml).
    5. ``export_route_draft(draft, target_dir)`` — write files.

Использование::

    from src.backend.core.api_importer import (
        APIImporter, import_openapi, generate_route_draft,
    )

    spec = json.load(open("partner_api.json"))
    imported = import_openapi(spec)
    draft = generate_route_draft(imported, route_id="partner-orders")
    Path("extensions/partner_orders/").mkdir(exist_ok=True)
    export_route_draft(draft, "extensions/partner_orders")
"""

from __future__ import annotations

from src.backend.core.api_importer.importer import (
    APIImporter,
    ConnectorDraft,
    ImportedAPI,
    OperationInfo,
    PathInfo,
    export_route_draft,
    generate_connector_draft,
    generate_route_draft,
    import_openapi,
    import_swagger,
)

__all__ = (
    "APIImporter",
    "ConnectorDraft",
    "ImportedAPI",
    "OperationInfo",
    "PathInfo",
    "export_route_draft",
    "generate_connector_draft",
    "generate_route_draft",
    "import_openapi",
    "import_swagger",
)
