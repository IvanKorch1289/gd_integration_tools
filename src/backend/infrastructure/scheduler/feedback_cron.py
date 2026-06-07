"""APScheduler cron-job для DSPy feedback nightly (Sprint 11 K4 W5).

Регистрируется в lifespan'е plugins/composition при включённом
``feature_flags.dspy_feedback_loop``. Запускается ежедневно в 03:00.
"""

from __future__ import annotations
from src.backend.infrastructure.logging.factory import get_logger


from typing import Any

__all__ = ("register_feedback_cron",)

logger = get_logger("infra.scheduler.feedback_cron")


def register_feedback_cron(
    scheduler: Any, *, trainer_factory: Any, cron: str = "0 3 * * *"
) -> str:
    """Зарегистрировать nightly feedback-train job в APScheduler.

    Args:
        scheduler: ``AsyncIOScheduler`` или совместимый объект с методом
            ``add_job(func, trigger, id=...)``.
        trainer_factory: Async callable, возвращающее :class:`FeedbackTrainer`
            (lazy, чтобы избежать импорта heavy deps при регистрации).
        cron: Crontab выражение (default ``0 3 * * *`` — 03:00 UTC).

    Returns:
        ID зарегистрированного job'а (``ai_feedback_dspy_nightly``).
    """
    from apscheduler.triggers.cron import CronTrigger

    async def _job() -> None:
        try:
            trainer = await trainer_factory()
            result = await trainer.train(prompt_name="rag_default", limit=1000)
            logger.info(
                "ai_feedback_dspy_nightly: examples=%s version=%s elapsed=%.1fs",
                result.examples_used,
                result.prompt_version,
                result.elapsed_seconds,
            )
        except Exception as exc:
            logger.exception("ai_feedback_dspy_nightly job failed: %s", exc)

    job_id = "ai_feedback_dspy_nightly"
    scheduler.add_job(
        _job, trigger=CronTrigger.from_crontab(cron), id=job_id, replace_existing=True
    )
    logger.info("registered feedback cron %s (cron=%s)", job_id, cron)
    return job_id
