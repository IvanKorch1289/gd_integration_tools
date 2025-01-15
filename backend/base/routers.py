from fastapi import APIRouter, Header
from fastapi.responses import HTMLResponse
from fastapi_utils.cbv import cbv

from backend.base.schemas import EmailSchema
from backend.base.service import BaseService
from backend.core.settings import settings
from backend.core.utils import utilities


__all__ = ("router",)

router = APIRouter()


@cbv(router)
class TechBV:
    """
    CBV-класс для переадресаций на интерфейсы технических приложений и выполнения healthcheck-ов.

    Предоставляет эндпоинты для получения ссылок на технические интерфейсы, проверки состояния
    сервисов и отправки тестовых email.
    """

    service = BaseService()

    @router.get(
        "/log-storage",
        summary="Получить ссылку на хранилище логов",
        operation_id="getLinkToLogStorage",
        response_class=HTMLResponse,
    )
    async def redirect_to_log_storage(self):
        """
        Возвращает HTML-страницу с ссылкой на хранилище логов.

        Returns:
            HTMLResponse: Страница с кликабельной ссылкой на хранилище логов.
        """
        log_url = (
            f"{settings.logging_settings.log_host}:{settings.logging_settings.log_port}"
        )
        return utilities.generate_link_page(log_url, "Хранилище логов")

    @router.get(
        "/file-storage",
        summary="Получить ссылку на файловое хранилище",
        operation_id="getLinkToFileStorage",
        response_class=HTMLResponse,
    )
    async def redirect_to_file_storage(self):
        """
        Возвращает HTML-страницу с ссылкой на файловое хранилище.

        Returns:
            HTMLResponse: Страница с кликабельной ссылкой на файловое хранилище.
        """
        fs_url = f"{settings.storage_settings.fs_interfase_url}"
        return utilities.generate_link_page(fs_url, "Файловое хранилище")

    @router.get(
        "/task-monitor",
        summary="Получить ссылку на интерфейс мониторинга фоновых задач",
        operation_id="getLinkToFlower",
        response_class=HTMLResponse,
    )
    async def redirect_to_task_monitor(self):
        """
        Возвращает HTML-страницу с ссылкой на интерфейс мониторинга фоновых задач.

        Returns:
            HTMLResponse: Страница с кликабельной ссылкой на интерфейс мониторинга задач.
        """
        bts_url = settings.bts_settings.bts_interface_url
        return utilities.generate_link_page(bts_url, "Мониторинг задач")

    @router.get(
        "/healthcheck-database",
        summary="Проверить состояние базы данных",
        operation_id="healthcheck_database",
    )
    async def healthcheck_database(self):
        """
        Проверяет состояние базы данных.

        Returns:
            dict: Результат проверки состояния базы данных.
        """
        return await utilities.health_check_database()

    @router.get(
        "/healthcheck-redis",
        summary="Проверить состояние Redis",
        operation_id="healthcheck_redis",
    )
    async def healthcheck_redis(self):
        """
        Проверяет состояние Redis.

        Returns:
            dict: Результат проверки состояния Redis.
        """
        return await utilities.health_check_redis()

    @router.get(
        "/healthcheck-celery",
        summary="Проверить состояние Celery",
        operation_id="healthcheck_celery",
    )
    async def healthcheck_celery(self):
        """
        Проверяет состояние Celery.

        Returns:
            dict: Результат проверки состояния Celery.
        """
        return await utilities.health_check_celery()

    @router.get(
        "/healthcheck-celery-queues",
        summary="Проверить состояние очередей Celery",
        operation_id="check_celery_queues",
    )
    async def healthcheck_celery_queues(self):
        """
        Проверяет состояние очередей Celery.

        Returns:
            dict: Состояние очередей Celery.
        """
        return await utilities.check_celery_queues()

    @router.get(
        "/healthcheck-s3",
        summary="Проверить состояние S3",
        operation_id="healthcheck_s3",
    )
    async def healthcheck_s3(self):
        """
        Проверяет состояние S3.

        Returns:
            dict: Результат проверки состояния S3.
        """
        return await utilities.health_check_s3()

    @router.get(
        "/healthcheck-scheduler",
        summary="Проверить состояние планировщика задач",
        operation_id="healthcheck_scheduler",
    )
    async def healthcheck_scheduler(self):
        """
        Проверяет состояние планировщика задач.

        Returns:
            dict: Результат проверки состояния планировщика задач.
        """
        return await utilities.health_check_scheduler()

    @router.get(
        "/healthcheck-graylog",
        summary="Проверить состояние Graylog",
        operation_id="healthcheck_graylog",
    )
    async def healthcheck_graylog(self):
        """
        Проверяет состояние Graylog.

        Returns:
            dict: Результат проверки состояния Graylog.
        """
        return await utilities.health_check_graylog()

    @router.get(
        "/healthcheck-smtp",
        summary="Проверить состояние SMTP-сервера",
        operation_id="healthcheck_smtp",
    )
    async def healthcheck_smtp(self):
        """
        Проверяет состояние SMTP-сервера.

        Returns:
            dict: Результат проверки состояния SMTP-сервера.
        """
        return await utilities.health_check_smtp()

    @router.get(
        "/healthcheck-all-services",
        summary="Проверить состояние всех сервисов",
        operation_id="healthcheck_all_services",
    )
    async def healthcheck_all_services(self):
        """
        Проверяет состояние всех сервисов.

        Returns:
            dict: Результат проверки состояния всех сервисов.
        """
        return await utilities.health_check_all_services()

    @router.get(
        "/version", summary="Получить версию приложения", operation_id="get_version"
    )
    async def get_version(self):
        """
        Возвращает текущую версию приложения.

        Returns:
            dict: Версия приложения.
        """
        return {"version": settings.app_version}

    @router.get(
        "/config", summary="Получить текущую конфигурацию", operation_id="get_config"
    )
    async def get_config(self, x_api_key: str = Header(...)):
        """
        Возвращает текущую конфигурацию приложения.

        Returns:
            dict: Конфигурация приложения.
        """
        return settings.model_dump()

    @router.post(
        "/send-email",
        summary="Отправить тестовое email",
        operation_id="send_email",
    )
    async def send_email(self, schema: EmailSchema):
        """
        Отправляет тестовое email.

        Args:
            schema (EmailSchema): Схема с данными для отправки email.

        Returns:
            dict: Результат отправки email.
        """
        return await utilities.send_email(
            to_email=schema.to_email, subject=schema.subject, message=schema.message
        )
