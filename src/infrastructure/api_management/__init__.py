"""API Management (G2, ADR-015): quotas, spike-arrest, versioning,
mocking, try-it-out, SDK generation.

Scaffold-уровень: публичные классы и интерфейсы. Конкретные реализации
частично уже есть (rate limiter в A4), остальное — в `middleware`
FastAPI и `docs/openapi/` артефактах.
"""

from src.infrastructure.api_management.api_key_auth import APIKeyAuth
from src.infrastructure.api_management.quotas import QuotaTracker
from src.infrastructure.api_management.versioning import APIVersion

__all__ = ("APIKeyAuth", "QuotaTracker", "APIVersion")
