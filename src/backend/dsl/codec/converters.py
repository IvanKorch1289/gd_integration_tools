"""Back-compat shim — re-exports из :mod:`core.utils.converters` (Sprint 224).

Pure value converters (numpy scalars, glob patterns, pydantic models)
перенесены в ``core/utils/converters.py`` для устранения 3 layer-violation
(services/tech.py, entrypoints/middlewares/admin_ip.py,
entrypoints/middlewares/api_key.py импортировали эти утилиты из dsl/).
Dsl re-export shim сохранён для backward compatibility.

Новые потребители должны импортировать из:
    ``from src.backend.core.utils.converters import convert_numpy_types, convert_pattern, transfer_model_to_schema``
"""

from src.backend.core.utils.converters import (  # noqa: F401 — back-compat re-export
    convert_numpy_types,
    convert_pattern,
    transfer_model_to_schema,
)

__all__ = ("convert_numpy_types", "convert_pattern", "transfer_model_to_schema")
