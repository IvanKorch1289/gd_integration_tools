from src.backend.core.config.settings import settings
from src.backend.infrastructure.logging.factory import get_logger
from src.backend.schemas.base import EmailSchema

__all__ = ("check_all_services", "consolidate_idle_sessions")

scheduler_logger = get_logger("scheduler")


async def check_all_services():
    """
    Проверяет статус всех сервисов.
    Если какой-либо сервис неактивен, отправляет уведомление по электронной почте через Redis Stream.
    """
    from src.backend.infrastructure.monitoring.health_check import (
        get_healthcheck_service,
    )

    try:
        scheduler_logger.info("Запуск проверки состояния всех сервисов...")

        async with get_healthcheck_service() as health_check:
            result = await health_check.check_all_services()

        if not result.get("is_all_services_active"):
            from src.backend.infrastructure.clients.messaging.stream import (
                get_stream_client,
            )

            data = {
                "to_emails": ["cards25@rt.bak"],
                "subject": "Обнаружены неактивные сервисы",
                "message": "Обнаружены неактивные сервисы. Пожалуйста, проверьте сервисы и повторите попытку позже.",
            }

            await get_stream_client().publish_to_redis(
                message=EmailSchema.model_validate(data),
                stream=settings.redis.get_stream_name("email"),
            )
        scheduler_logger.info(f"Проверка состояния завершена. Результат: {result}")
    except Exception as exc:
        scheduler_logger.error(f"Ошибка при проверке состояния: {exc!s}", exc_info=True)


async def consolidate_idle_sessions():
    """
    APScheduler-cron job (Sprint 19 K4 W4b): LangMem consolidation.

    Запускает :meth:`LangMemService.consolidate()` для idle-эпизодов.
    Регистрируется только если ``langmem_settings.consolidation_schedule_cron``
    непустое; иначе — только ручной запуск через admin UI / API.
    """
    try:
        scheduler_logger.info("Запуск LangMem consolidation...")
        from src.backend.services.ai.langmem_service import get_langmem_service

        svc = get_langmem_service()
        report = await svc.consolidate()
        scheduler_logger.info("LangMem consolidation finished: %s", report)
    except Exception as exc:
        scheduler_logger.error(
            "LangMem consolidation failed: %s", str(exc), exc_info=True
        )
