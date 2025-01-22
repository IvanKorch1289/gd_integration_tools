from typing import Any, Callable, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from backend.core.logging_config import scheduler_logger
from backend.core.utils import singleton


@singleton
class SchedulerManager:
    """
    Менеджер для управления задачами планировщика.

    Использует библиотеку APScheduler для выполнения задач по расписанию.
    """

    def __init__(self):
        """Инициализация планировщика."""
        self.scheduler = AsyncIOScheduler()

    async def add_task(
        self, task_function: Callable, interval_minutes: int = 60, **kwargs: Any
    ) -> None:
        """
        Добавляет задачу в планировщик.

        Args:
            task_function (Callable): Функция, которая будет выполняться по расписанию.
            interval_minutes (int): Интервал выполнения задачи в минутах. По умолчанию 60.
            **kwargs: Дополнительные аргументы для задачи.
        """
        trigger = IntervalTrigger(minutes=interval_minutes)
        self.scheduler.add_job(task_function, trigger, replace_existing=True, **kwargs)
        scheduler_logger.info(
            f"Задача '{task_function.__name__}' добавлена с интервалом {interval_minutes} минут."
        )

    async def start_scheduler(self) -> None:
        """Запускает планировщик."""
        if not self.scheduler.running:
            self.scheduler.start()
            scheduler_logger.info("Планировщик запущен.")

    async def stop_scheduler(self) -> None:
        """Останавливает планировщик."""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            scheduler_logger.info("Планировщик остановлен.")

    async def check_status(self) -> bool:
        """
        Проверяет, запущен ли планировщик.

        Returns:
            bool: True, если планировщик запущен, иначе False.
        """
        return self.scheduler.running


# Глобальный экземпляр менеджера планировщика
scheduler_manager = SchedulerManager()


async def send_request_for_checking_services() -> Optional[bool]:
    """
    Задача для проверки состояния сервисов.

    Если какой-либо сервис недоступен, отправляет уведомление по email.

    Returns:
        Optional[bool]: Возвращает None, если задача выполнена успешно, иначе False.
    """
    from backend.core.utils import utilities

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
