from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger


class SchedulerManager:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not isinstance(cls._instance, cls):
            cls._instance = object.__new__(cls)
        return cls._instance

    def __init__(self):
        self.scheduler = AsyncIOScheduler()

    async def add_task(self, task_function, interval_minutes: int = 5, **kwargs):
        """Добавление новой задачи в планировщик."""
        trigger = IntervalTrigger(minutes=interval_minutes)
        self.scheduler.add_job(task_function, trigger, replace_existing=True)

    async def start_scheduler(self):
        self.scheduler.start()

    async def stop_scheduler(self):
        self.scheduler.shutdown()

    async def check_status(self):
        return self.scheduler.running


scheduler_manager = SchedulerManager()


####################################################################
#                        Задачи для планировщика                   #
####################################################################
async def send_request_for_checking_services():
    from backend.core.utils import utilities

    try:
        response = await utilities.health_check_all_services()
        response_body = await utilities.get_response_type_body(response)
        if not response_body.get("is_all_services_active", None):
            return await utilities.send_email(
                to_email="crazyivan1289@yandex.ru",
                subject="Недоступен компонент GD_ADVANCED_TOOLS",
                message=str(response_body),
            )
    except Exception as exc:
        return await utilities.send_email(
            to_email="crazyivan1289@yandex.ru",
            subject="Недоступен компонент GD_ADVANCED_TOOLS",
            message=str(exc),
        )
