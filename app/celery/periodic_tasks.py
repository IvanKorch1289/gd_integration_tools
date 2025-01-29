from app.celery.celery_config import celery_manager
from app.utils import mail_service, scheduler_logger, utilities


@celery_manager.app.task(
    name="check_services_health",
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    retry_backoff=True,
    autoretry_for=(Exception,),
    ignore_result=False,
)
def check_services_health(self):
    """Периодическая задача для проверки состояния сервисов"""

    async def inner_check():
        try:
            response = await utilities.health_check_all_services()
            response_body = await utilities.get_response_type_body(response)

            if not response_body.get("is_all_services_active"):
                await mail_service.send_email(
                    to_email="crazyivan1289@yandex.ru",
                    subject="Недоступен компонент GD_ADVANCED_TOOLS",
                    message=str(response_body),
                )
                scheduler_logger.warning("Обнаружены недоступные сервисы.")
                return {"status": "warning", "details": response_body}

            scheduler_logger.info("Все сервисы активны.")
            return {"status": "ok"}

        except Exception as exc:
            scheduler_logger.error(f"Критическая ошибка: {exc}")
            await mail_service.send_email(
                to_email="crazyivan1289@yandex.ru",
                subject="Сбой проверки сервисов",
                message=str(exc),
            )
            raise exc

    try:
        return utilities.run_async_task(inner_check())
    except Exception as exc:
        self.retry(exc=exc, countdown=self.default_retry_delay)
