"""Re-export BaseExternalAPIClient for capability-checked access (S120 W1).

See ``src/backend/core/services/__init__.py`` for the facade rationale.
"""

from __future__ import annotations

from src.backend.services.core.base_external_api import (  # noqa: F401
    BaseExternalAPIClient,
)

__all__ = ("BaseExternalAPIClient",)
