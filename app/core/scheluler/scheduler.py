from typing import Any, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core.logging import scheduler_logger
from app.utils import singleton


__all__ = ("scheduler_manager",)


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
