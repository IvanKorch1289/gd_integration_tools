from typing import Optional

from app.core.logging import scheduler_logger
from app.utils import utilities


__all__ = ("send_request_for_checking_services",)


async def send_request_for_checking_services() -> Optional[bool]:
    """
    Задача для проверки состояния сервисов.

    Если какой-либо сервис недоступен, отправляет уведомление по email.

    Returns:
        Optional[bool]: Возвращает None, если задача выполнена успешно, иначе False.
    """
    try:
        # Проверка состояния сервисов
        response = await utilities.health_check_all_services()
        response_body = await utilities.get_response_type_body(response)

        # Если не все сервисы активны, отправляем уведомление
        if not response_body.get("is_all_services_active", None):
            await utilities.send_email(
                to_email="crazyivan1289@yandex.ru",
                subject="Недоступен компонент GD_ADVANCED_TOOLS",
                message=str(response_body),
            )
            scheduler_logger.warning("Обнаружены недоступные сервисы.")
            return False

        scheduler_logger.info("Все сервисы активны.")
        return None

    except Exception as exc:
        # Логирование ошибки и отправка уведомления
        scheduler_logger.error(f"Ошибка при проверке сервисов: {exc}")
        await utilities.send_email(
            to_email="crazyivan1289@yandex.ru",
            subject="Недоступен компонент GD_ADVANCED_TOOLS",
            message=str(exc),
        )
        return False
