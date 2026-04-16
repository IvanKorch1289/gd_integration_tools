from app.core.config.settings import settings
from app.infrastructure.external_apis.logging_service import scheduler_logger
from app.schemas.base import EmailSchema

__all__ = ("check_all_services",)


async def check_all_services():
    """
    Проверяет статус всех сервисов.
    Если какой-либо сервис неактивен, отправляет уведомление по электронной почте через Redis Stream.
    """
    from app.core.utils.health_check import get_healthcheck_service

    try:
        scheduler_logger.info("Запуск проверки состояния всех сервисов...")

        async with get_healthcheck_service() as health_check:
            result = await health_check.check_all_services()

        if not result.get("is_all_services_active"):
            from app.infrastructure.clients.stream import stream_client

            data = {
                "to_emails": ["cards25@rt.bak"],
                "subject": "Обнаружены неактивные сервисы",
                "message": "Обнаружены неактивные сервисы. Пожалуйста, проверьте сервисы и повторите попытку позже.",
            }

            await stream_client.publish_to_redis(
                message=EmailSchema.model_validate(data),
                stream=settings.redis.get_stream_name("email"),
            )
        scheduler_logger.info(f"Проверка состояния завершена. Результат: {result}")
    except Exception as exc:
        scheduler_logger.error(
            f"Ошибка при проверке состояния: {str(exc)}", exc_info=True
        )
