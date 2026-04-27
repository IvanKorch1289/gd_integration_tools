"""Schema Importer — OpenAPI / Postman → Pydantic v2 + DSL Routes.

Публичный фасад:

    from src.tools.schema_importer import SchemaImporter

    importer = SchemaImporter()
    importer.from_openapi("petstore.yaml", out_dir="src/schemas/auto")
    importer.from_postman("collection.json", out_dir="src/schemas/auto")

Сгенерированные модели складываются в :data:`SchemaImporter.default_out_dir`
(``src/schemas/auto``). Переопределения кастомных схем кладутся в
``src/schemas/custom`` и подключаются через re-export.

Роуты DSL (YAML) генерируются в ``config/routes/imported/``.
"""

from __future__ import annotations

from src.tools.schema_importer.importer import SchemaImporter

__all__ = ("SchemaImporter",)
