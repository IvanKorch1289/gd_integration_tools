"""DSL services — фасад над core/dsl для entrypoints (Streamlit, REST).

Модуль агрегирует операции с DSL-маршрутами:
- инспекция (list / get / preview YAML);
- write-back (сохранение Pipeline в YAMLStore с dev-only guard'ом);
- diff между текущим и целевым YAML.

Цель — изолировать UI/API от прямых импортов из ``core/dsl`` и
``infrastructure/`` (см. CLAUDE.md, layer policy).
"""

from src.backend.services.dsl.builder_service import (
    DSLBuilderService,
    SaveResult,
    get_dsl_builder_service,
)

__all__ = ("DSLBuilderService", "SaveResult", "get_dsl_builder_service")
