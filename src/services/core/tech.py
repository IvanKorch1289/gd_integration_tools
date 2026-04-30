from enum import Enum
from io import BytesIO
from typing import Any

import polars as pl
from fastapi.responses import HTMLResponse

from src.core.config.settings import settings
from src.core.di.providers import get_healthcheck_session_provider
from src.services.core.base import BaseService, get_service_for_model
from src.utilities.converters import convert_numpy_types
from src.utilities.web import generate_link_page

__all__ = ("TechService", "get_tech_service")


class TechService:
    """
    Сервис для технических и служебных операций (Healthcheck, ссылки, отправка писем, массовая загрузка).
    """

    async def get_log_storage_link(self) -> HTMLResponse:
        return generate_link_page(
            f"{settings.logging.host}:{settings.logging.port}", "Хранилище логов"
        )

    async def get_file_storage_link(self) -> HTMLResponse:
        return generate_link_page(
            f"{settings.storage.interface_endpoint}", "Файловое хранилище"
        )

    async def get_queue_monitor_link(self) -> HTMLResponse:
        return generate_link_page(settings.queue.queue_ui_url, "Мониторинг очередей")

    async def get_langfuse_link(self) -> HTMLResponse:
        return generate_link_page(
            settings.app.langfuse_url, "LangFuse — LLM Observability"
        )

    async def get_langgraph_link(self) -> HTMLResponse:
        return generate_link_page(
            settings.app.langgraph_url, "LangGraph Studio — AI Agents"
        )

    async def check_database(self) -> bool:
        async with get_healthcheck_session_provider()() as health_check:
            return await health_check.check_database()

    async def check_redis(self) -> bool:
        async with get_healthcheck_session_provider()() as health_check:
            return await health_check.check_redis()

    async def check_s3(self) -> bool:
        async with get_healthcheck_session_provider()() as health_check:
            return await health_check.check_s3()

    async def check_s3_bucket(self) -> bool:
        async with get_healthcheck_session_provider()() as health_check:
            return await health_check.check_s3_bucket()

    async def check_graylog(self) -> bool:
        async with get_healthcheck_session_provider()() as health_check:
            return await health_check.check_graylog()

    async def check_smtp(self) -> bool:
        async with get_healthcheck_session_provider()() as health_check:
            return await health_check.check_smtp()

    async def check_rabbitmq(self) -> bool:
        async with get_healthcheck_session_provider()() as health_check:
            return await health_check.check_rabbitmq()

    async def check_all_services(self) -> dict[str, Any]:
        async with get_healthcheck_session_provider()() as health_check:
            return await health_check.check_all_services()

    async def get_all_custom_tables(self, model_enum: Enum) -> set[str]:
        return {model.value.__tablename__ for model in model_enum}  # type: ignore

    async def upload_excel_for_mass_create(
        self, file_bytes: bytes, table_name: str, model_enum: Enum
    ) -> list[dict[str, Any]]:
        """
        Парсит Excel-файл и добавляет записи в БД через BaseService нужной модели.
        """
        if table_name not in model_enum._member_names_:  # type: ignore
            raise ValueError(f"Таблица {table_name} не найдена.")

        service: BaseService = await get_service_for_model(
            model_enum[table_name].value  # type: ignore
        )

        results: list = []
        df = pl.read_excel(BytesIO(file_bytes))

        for row in df.iter_rows(named=True):
            row_data = {col: convert_numpy_types(value) for col, value in row.items()}

            validated_data = service.request_schema.model_validate(row_data)

            try:
                result = await service.get_or_add(data=validated_data.model_dump())
                results.append(result)
            except Exception as exc:
                results.append({"error": str(exc)})

        return results


_tech_service_instance = TechService()


def get_tech_service() -> TechService:
    return _tech_service_instance
