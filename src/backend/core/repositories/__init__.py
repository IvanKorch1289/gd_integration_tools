"""Repository-абстракции (S38.4 DDD).

Чистые интерфейсы хранилищ, независимые от конкретной
infrastructure-реализации (in-memory, MongoDB, Postgres).
"""

from __future__ import annotations

from src.backend.core.repositories.feedback import FeedbackRepository

__all__ = ("FeedbackRepository",)
