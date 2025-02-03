from typing import Dict, List, Optional

from celery import Celery, schedules

from app.celery.cron import CronPresets
from app.config.settings import Settings, settings
from app.utils.decorators.singleton import singleton


__all__ = ("celery_manager", "celery_app")


class CeleryHealthError(Exception):
    """Базовое исключение для ошибок здоровья Celery"""

    def __init__(self, message: str, details: Optional[str] = None):
        self.message = message
        self.details = details
        super().__init__(message)


class CeleryConnectionError(CeleryHealthError):
    """Ошибка соединения с Celery"""


class QueueUnavailableError(CeleryHealthError):
    """Ошибка отсутствия активных очередей"""


class BeatNotRunningError(CeleryHealthError):
    """Ошибка соединения с Celery Beat"""


@singleton
class CeleryManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.app = self._configure_celery()
        self._configure_periodic_tasks()

    def _configure_celery(self) -> Celery:
        """Создает и конфигурирует экземпляр Celery."""
        redis_url = f"{self.settings.redis.redis_url}/{self.settings.redis.redis_db_celery}"
        celery_app = Celery(
            "tasks",
            broker=redis_url,
            backend=redis_url,
            include=["app.celery.tasks"],
        )

        celery_app.conf.update(
            {
                # Сериализация
                "task_serializer": self.settings.celery.cel_task_serializer,
                "result_serializer": self.settings.celery.cel_task_serializer,
                "accept_content": [self.settings.celery.cel_task_serializer],
                # Поведение задач
                "task_default_queue": self.settings.celery.cel_task_default_queue,
                "task_time_limit": self.settings.celery.cel_task_time_limit,
                "task_soft_time_limit": self.settings.celery.cel_task_soft_time_limit,
                "task_default_max_retries": self.settings.celery.cel_task_max_retries,
                "task_retry_backoff": self.settings.celery.cel_task_retry_backoff,
                "task_retry_jitter": self.settings.celery.cel_task_retry_jitter,
                "task_track_started": self.settings.celery.cel_task_track_started,
                # Настройки воркеров
                "worker_concurrency": self.settings.celery.cel_worker_concurrency,
                "worker_prefetch_multiplier": self.settings.celery.cel_worker_prefetch_multiplier,
                "worker_max_tasks_per_child": self.settings.celery.cel_worker_max_tasks_per_child,
                "worker_disable_rate_limits": self.settings.celery.cel_worker_disable_rate_limits,
                "worker_send_events": self.settings.celery.cel_worker_send_events,
                # Управление соединениями
                "broker_pool_limit": self.settings.celery.cel_broker_pool_limit,
                "result_extended": self.settings.celery.cel_result_extended,
                # Безопасность и надежность
                "task_acks_late": True,
                "task_reject_on_worker_lost": True,
                "broker_connection_retry_on_startup": True,
                # Временные настройки
                "enable_utc": True,
                "timezone": "Europe/Moscow",
                # Настройки Beat
                "beat_schedule": self._get_beat_schedule(),
                "beat_max_loop_interval": 300,
            }
        )
        return celery_app

    def _get_beat_schedule(self) -> Dict:
        """Возвращает расписание периодических задач"""
        return {
            "health-check-every-hour": {
                "task": "app.celery.periodic_tasks.check_services_health",
                "schedule": CronPresets.HOURLY.schedule,
                "args": (),
                "options": {
                    "queue": self.settings.celery.cel_task_default_queue,
                    "expires": 300,
                },
            }
        }

    def _configure_periodic_tasks(self):
        """Дополнительная конфигурация периодических задач"""
        if settings.app.app_environment == "testing":
            self.app.conf.beat_schedule = {}
        elif settings.app.app_environment == "development":
            # Для разработки можно уменьшить интервал
            self.app.conf.beat_schedule["health-check-every-hour"][
                "schedule"
            ] = schedules.crontab(minute="*/15")

    async def check_connection(self) -> bool:
        """Проверяет доступность Celery workers.

        Returns:
            bool: True если workers доступны

        Raises:
            CeleryConnectionError: При проблемах с подключением
        """
        try:
            inspect = self.app.control.inspect()
            ping_result = inspect.ping()

            if not ping_result:
                raise CeleryConnectionError("No active workers responding")

            return True

        except Exception as exc:
            raise CeleryConnectionError(
                message="Celery connection failed", details=str(exc)
            )

    async def check_queue_connection(self) -> Dict[str, List[str]]:
        """Возвращает статус очередей.

        Returns:
            Словарь с информацией об очередях

        Raises:
            QueueUnavailableError: Если очереди недоступны
        """
        try:
            inspect = self.app.control.inspect()
            active_queues = inspect.active_queues()

            if not active_queues:
                raise QueueUnavailableError("No active queues found")

            return active_queues

        except Exception as exc:
            raise QueueUnavailableError(
                message="Failed to get queue status", details=str(exc)
            )

    async def check_beat_connection(self) -> dict:
        """Проверяет активность Celery Beat.

        Returns:
            dict: Статус и список запланированных задач

        Raises:
            BeatNotRunningError: Если Beat не запущен
        """
        try:
            inspect = self.app.control.inspect()
            scheduled = inspect.scheduled()  # Планируемые задачи
            active = inspect.active()  # Активные воркеры

            if not scheduled and not active:
                raise BeatNotRunningError("Celery Beat is not running")

            return {"scheduled_tasks": scheduled, "active_workers": active}

        except Exception as exc:
            raise BeatNotRunningError(
                message="Celery Beat check failed", details=str(exc)
            )


# Инициализация менеджера
celery_manager = CeleryManager(settings=settings)

celery_app = celery_manager.app
