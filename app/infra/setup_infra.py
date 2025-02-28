from asyncio import to_thread

from types import CoroutineType

from app.infra.application.scheduler import scheduler_manager
from app.infra.clients.logger import graylog_handler
from app.infra.clients.redis import redis_client
from app.infra.clients.smtp import smtp_client
from app.infra.clients.storage import s3_client
from app.infra.db.database import db_initializer
from app.utils.decorators.limiting import init_limiter
from app.utils.logging_service import app_logger


__all__ = (
    "starting",
    "ending",
)


# Операции, выполняемые при запуске приложения
starting_operations = [
    redis_client.ensure_connected,  # Подключение к Redis
    (
        "graylog_client",
        lambda: to_thread(graylog_handler.connect),
    ),  # Подключение к Graylog
    db_initializer.initialize_async_pool,  # Инициализация пула асинхронных соединений с БД
    s3_client.connect,  # Подключение к S3-хранилищу
    smtp_client.initialize_pool,  # Инициализация пула SMTP-соединений
    init_limiter,  # Инициализация лимитера запросов
    redis_client.create_initial_streams,  # Создание начальных потоков в Redis
    scheduler_manager.start,  # Запуск планировщика задач
]

# Операции, выполняемые при завершении работы приложения
ending_operations = [
    scheduler_manager.stop,  # Остановка планировщика задач
    smtp_client.close_pool,  # Закрытие пула SMTP-соединений
    s3_client.close,  # Закрытие соединения с S3-хранилищем
    db_initializer.close,  # Закрытие соединений с БД
    (
        "graylog_client",
        lambda: to_thread(graylog_handler.close),
    ),  # Закрытие соединения с Graylog
    redis_client.close,  # Закрытие соединения с Redis
]


async def perform_infrastructure_operation(components: list) -> None:
    """Выполняет операции инициализации или завершения работы инфраструктуры.

    Args:
        components (list): Список операций для выполнения.
            Каждая операция может быть функцией или кортежем (имя, функция).

    Raises:
        Exception: Если операция завершилась с ошибкой.
    """
    for component in components:
        try:
            coro = None

            # Обработка кортежа (имя, функция)
            if isinstance(component, tuple):
                _, func = component
                coro = func()
            else:
                coro = component()

            # Если операция является корутиной, ожидаем её завершения
            if isinstance(coro, CoroutineType):
                await coro

            app_logger.info(f"Операция {coro.__name__} выполнена успешно")
        except Exception as exc:
            app_logger.critical(
                f"Ошибка при выполнении операции {coro.__name__}: {str(exc)}",
                exc_info=True,
            )
            raise


async def starting() -> None:
    """Запускает все операции инициализации инфраструктуры при старте приложения."""
    await perform_infrastructure_operation(components=starting_operations)


async def ending() -> None:
    """Запускает все операции завершения работы инфраструктуры при остановке приложения."""
    await perform_infrastructure_operation(components=ending_operations)
