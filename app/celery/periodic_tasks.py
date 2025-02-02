from app.celery.celery_config import celery_app
from app.infra import event_bus
from app.services.infra_services.mail import mail_sender
from app.utils.logging import scheduler_logger
from app.utils.utils import utilities


@celery_app.task(
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
        from app.utils.health_check import health_check

        try:
            response = await health_check.check_all_services()
            response_body = await utilities.get_response_body(response)

            if not response_body.get("is_all_services_active"):
                await event_bus.event_client.publish_event(
                    event_type="init_mail_send",
                    data={
                        "to_emails": ["crazyivan1289@yandex.ru"],
                        "subject": "Недоступен компонент GD_ADVANCED_TOOLS",
                        "message": str(response_body),
                    },
                )
                scheduler_logger.warning("Обнаружены недоступные сервисы.")
                return {"status": "warning", "details": response_body}

            scheduler_logger.info("Все сервисы активны.")
            return {"status": "ok"}

        except Exception as exc:
            scheduler_logger.error(f"Критическая ошибка: {exc}")
            await event_bus.event_client.publish_event(
                event_type="init_mail_send",
                data={
                    "to_emails": ["crazyivan1289@yandex.ru"],
                    "subject": "Ошибка при проверке",
                    "message": str(response_body),
                },
            )
            raise exc

    try:
        return utilities.execute_async_task(inner_check())
    except Exception as exc:
        self.retry(exc=exc, countdown=self.default_retry_delay)
