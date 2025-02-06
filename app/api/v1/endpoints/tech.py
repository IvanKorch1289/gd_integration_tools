from enum import Enum
from io import BytesIO

import pandas as pd
from fastapi import (
    APIRouter,
    Depends,
    File,
    Header,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import HTMLResponse
from fastapi_utils.cbv import cbv

from app.config.settings import settings
from app.infra.stream_manager import stream_client
from app.schemas.base import EmailSchema
from app.services.route_services.base import BaseService, get_service_for_model
from app.utils.enums.base import get_model_enum
from app.utils.errors import handle_routes_errors
from app.utils.health_check import health_check
from app.utils.utils import utilities


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
    @handle_routes_errors
    async def redirect_to_log_storage(self):
        """
        Возвращает HTML-страницу с ссылкой на хранилище логов.

        Returns:
            HTMLResponse: Страница с кликабельной ссылкой на хранилище логов.
        """
        return utilities.generate_link_page(
            f"{settings.logging.host}:{settings.logging.port}",
            "Хранилище логов",
        )

    @router.get(
        "/file-storage",
        summary="Получить ссылку на файловое хранилище",
        operation_id="getLinkToFileStorage",
        response_class=HTMLResponse,
    )
    @handle_routes_errors
    async def redirect_to_file_storage(self):
        """
        Возвращает HTML-страницу с ссылкой на файловое хранилище.

        Returns:
            HTMLResponse: Страница с кликабельной ссылкой на файловое хранилище.
        """
        return utilities.generate_link_page(
            f"{settings.storage.interface_endpoint}", "Файловое хранилище"
        )

    @router.get(
        "/task-monitor",
        summary="Получить ссылку на интерфейс мониторинга фоновых задач",
        operation_id="getLinkToFlower",
        response_class=HTMLResponse,
    )
    @handle_routes_errors
    async def redirect_to_task_monitor(self):
        """
        Возвращает HTML-страницу с ссылкой на интерфейс мониторинга фоновых задач.

        Returns:
            HTMLResponse: Страница с кликабельной ссылкой на интерфейс мониторинга задач.
        """
        return utilities.generate_link_page(
            settings.celery.flower_url, "Мониторинг задач"
        )

    @router.get(
        "/healthcheck-database",
        summary="Проверить состояние базы данных",
        operation_id="healthcheck_database",
    )
    @handle_routes_errors
    async def healthcheck_database(self):
        """
        Проверяет состояние базы данных.

        Returns:
            dict: Результат проверки состояния базы данных.
        """
        return await health_check.check_database()

    @router.get(
        "/healthcheck-redis",
        summary="Проверить состояние Redis",
        operation_id="healthcheck_redis",
    )
    @handle_routes_errors
    async def healthcheck_redis(self):
        """
        Проверяет состояние Redis.

        Returns:
            dict: Результат проверки состояния Redis.
        """
        return await health_check.check_redis()

    @router.get(
        "/healthcheck-celery",
        summary="Проверить состояние Celery",
        operation_id="healthcheck_celery",
    )
    @handle_routes_errors
    async def healthcheck_celery(self):
        """
        Проверяет состояние Celery.

        Returns:
            dict: Результат проверки состояния Celery.
        """
        return await health_check.check_celery()

    @router.get(
        "/healthcheck-celery-queues",
        summary="Проверить состояние очередей Celery",
        operation_id="check_celery_queues",
    )
    @handle_routes_errors
    async def healthcheck_celery_queues(self):
        """
        Проверяет состояние очередей Celery.

        Returns:
            dict: Состояние очередей Celery.
        """
        return await health_check.check_celery_queues()

    @router.get(
        "/healthcheck-scheduler",
        summary="Проверить состояние планировщика задач",
        operation_id="healthcheck_scheduler",
    )
    @handle_routes_errors
    async def healthcheck_celery_scheduler(self):
        """
        Проверяет состояние планировщика задач.

        Returns:
            dict: Результат проверки состояния планировщика задач.
        """
        return await health_check.check_celery_scheduler()

    @router.get(
        "/healthcheck-s3",
        summary="Проверить состояние S3",
        operation_id="healthcheck_s3",
    )
    @handle_routes_errors
    async def healthcheck_s3(self):
        """
        Проверяет состояние S3.

        Returns:
            dict: Результат проверки состояния S3.
        """
        return await health_check.check_s3()

    @router.get(
        "/healthcheck-s3-bucket",
        summary="Проверить наличие бакета в S3",
        operation_id="healthcheck_s3_bucket",
    )
    @handle_routes_errors
    async def healthcheck_s3_bucket(self):
        """
        Проверяет наличие бакета в S3.

        Returns:
            dict: Результат проверки наличия бакета в S3.
        """
        return await health_check.check_s3_bucket()

    @router.get(
        "/healthcheck-graylog",
        summary="Проверить состояние Graylog",
        operation_id="healthcheck_graylog",
    )
    @handle_routes_errors
    async def healthcheck_graylog(self):
        """
        Проверяет состояние Graylog.

        Returns:
            dict: Результат проверки состояния Graylog.
        """
        return await health_check.check_graylog()

    @router.get(
        "/healthcheck-smtp",
        summary="Проверить состояние SMTP-сервера",
        operation_id="healthcheck_smtp",
    )
    @handle_routes_errors
    async def healthcheck_smtp(self):
        """
        Проверяет состояние SMTP-сервера.

        Returns:
            dict: Результат проверки состояния SMTP-сервера.
        """
        return await health_check.check_smtp()

    @router.get(
        "/healthcheck-kafka",
        summary="Проверить состояние Kafka",
        operation_id="healthcheck_kafka",
    )
    @handle_routes_errors
    async def healthcheck_kafka(self):
        """
        Проверяет состояние Kafka.

        Returns:
            dict: Результат проверки состояния Kafka.
        """
        return await health_check.check_queue()

    @router.get(
        "/healthcheck-all-services",
        summary="Проверить состояние всех сервисов",
        operation_id="healthcheck_all_services",
    )
    @handle_routes_errors
    async def healthcheck_all_services(self):
        """
        Проверяет состояние всех сервисов.

        Returns:
            dict: Результат проверки состояния всех сервисов.
        """
        return await health_check.check_all_services()

    @router.get(
        "/config",
        summary="Получить текущую конфигурацию",
        operation_id="get_config",
    )
    @handle_routes_errors
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
    @handle_routes_errors
    async def send_email(
        self, schema: EmailSchema, x_api_key: str = Header(...)
    ):
        """
        Отправляет тестовое email.

        Args:
            schema (EmailSchema): Схема с данными для отправки email.

        Returns:
            dict: Результат отправки email.
        """
        data = schema.model_dump()

        await stream_client.publish_event(
            event_type="init_mail_send", data=data
        )
        return data

    @router.get(
        "/get-all-custom-tables",
        summary="Получить названия всех таблиц",
        operation_id="get_all_custom_tables",
    )
    @handle_routes_errors
    async def get_all_custom_tables(
        self,
        model_enum: Enum = Depends(get_model_enum),
        x_api_key: str = Header(...),
    ):
        """
        Возвращает названия всех пользовательских таблиц.

        Args:
            model_enum (Enum): Enum, содержащий модели и их таблицы.
            x_api_key (str): API-ключ для аутентификации.

        Returns:
            set: Набор названий таблиц.
        """
        return {model.value.__tablename__ for model in model_enum}

    @router.post(
        "/upload-excel-for-mass-create",
        summary="Загрузить Excel-файл для массового создания объектов",
        operation_id="upload_excel_for_mass_create",
    )
    @handle_routes_errors
    async def upload_excel(
        self,
        file: UploadFile = File(...),
        table_name: str = Query(
            ..., description="Название таблицы для загрузки данных"
        ),
        model_enum: Enum = Depends(get_model_enum),
        x_api_key: str = Header(...),
    ):
        """
        Загружает Excel-файл для массового создания объектов в выбранной таблице.

        Args:
            table_name (str): Название таблицы, в которую будут добавлены данные.
            model_enum (Enum): Enum, содержащий модели и их таблицы.
            x_api_key (str): API-ключ для аутентификации.

        Returns:
            list: Список результатов добавления данных.
        """
        if table_name in model_enum._member_names_:
            # Получаем сервис для модели
            service: BaseService = await get_service_for_model(
                model_enum[table_name].value
            )

            results: list = []

            # Читаем содержимое файла
            contents = await file.read()

            # Читаем Excel-файл
            df = pd.read_excel(BytesIO(contents))

            # Преобразование каждой строки в Pydantic-схему и вызов метода create_item
            for _, row in df.iterrows():
                # Преобразуем строку в словарь и конвертируем numpy-типы в стандартные типы Python
                row_data = {
                    col: utilities.convert_numpy_types(value)
                    for col, value in row.to_dict().items()
                }

                # Валидируем данные с помощью Pydantic-схемы
                validated_data = service.request_schema.model_validate(
                    row_data
                )

                # Добавляем данные через сервис
                try:
                    result = await service.get_or_add(
                        data=validated_data.model_dump()
                    )
                    results.append(result)
                except Exception as exc:
                    results.append({"error": str(exc)})
                    raise

            return results

        return Response(
            content={"error": f"Таблица {table_name} не найдена."},
            status_code=status.HTTP_404_NOT_FOUND,
        )
