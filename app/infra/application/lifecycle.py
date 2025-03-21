from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.utils.logging_service import app_logger


__all__ = ("lifespan",)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Асинхронный контекстный менеджер для управления жизненным циклом приложения FastAPI.

    Обеспечивает:
    - Инициализацию служб при запуске (планировщик задач, лимиты запросов)
    - Корректное освобождение ресурсов при завершении
    - Обработку критических ошибок инициализации

    Args:
        app (FastAPI): Экземпляр приложения FastAPI для управления жизненным циклом.

    Yields:
        None: Контроль возвращается приложению после успешной инициализации.

    Raises:
        RuntimeError: Возникает при неудачной инициализации служб (например, проблемы с БД, планировщиком)
        Exception: Любые необработанные исключения во время работы приложения (логируются как критические)

    Пример использования:
        Передается в FastAPI при создании экземпляра: `FastAPI(lifespan=lifespan)`
    """
    from app.infra.setup_infra import ending, starting

    app_logger.info("Запуск приложения...")

    try:
        # Инициализация инфраструктуры
        await starting()
        app_logger.info("Приложение успешно запущено")

        # Возврат управления приложению
        yield
    except Exception as exc:
        # Логирование критических ошибок инициализации
        app_logger.critical(
            f"Критическая ошибка при запуске: {str(exc)}", exc_info=True
        )
        raise RuntimeError(
            "Остановка приложения из-за ошибки инициализации"
        ) from exc
    finally:
        # Корректное завершение работы
        app_logger.info("Завершение работы...")
        try:
            await ending()
        except Exception as shutdown_exc:
            app_logger.error(
                f"Ошибка при завершении работы: {str(shutdown_exc)}",
                exc_info=True,
            )
        app_logger.info("Приложение остановлено")
