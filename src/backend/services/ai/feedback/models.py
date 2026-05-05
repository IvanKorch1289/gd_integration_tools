"""Модели AI Feedback Loop — re-export из core/models/.

DTO перенесены в ``src.core.models.feedback`` (W6.6), здесь
сохраняется re-export для обратной совместимости импортёров.
"""

from src.core.models.feedback import AIFeedbackDoc, FeedbackLabel

__all__ = ("AIFeedbackDoc", "FeedbackLabel")
