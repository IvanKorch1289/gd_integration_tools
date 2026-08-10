"""Domain layer AI Feedback (S38.4 DDD)."""

from src.backend.core.domain.feedback.service import (
    FeedbackDomainService,  # noqa: F401 — re-export
)

__all__ = ("FeedbackDomainService",)
