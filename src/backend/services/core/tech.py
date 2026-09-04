from enum import Enum
from io import BytesIO
from typing import Any

# polars — optional dep (Ponytail YAGNI). Module импортируется даже
# без polars; реальное обращение к pl.read_excel в import_excel_data()
# даёт понятную ошибку с инструкцией install.
try:
    import polars as pl  # type: ignore[import-not-found]
except ImportError:
    pl = None  # type: ignore[assignment]

from fastapi.responses import HTMLResponse

from src.backend.core.config.settings import settings
from src.backend.core.di.app_state import app_state_singleton
from src.backend.core.di.providers import get_health_aggregator_provider
from src.backend.core.net.http_utils import generate_link_page
from src.backend.core.utils.converters import convert_numpy_types
from src.backend.services.core.base import BaseService, get_service_for_model

__all__ = ("TechService", "get_tech_service")


# T7 (Фаза A, 2026-09-05): tech-проверки идут через живой HealthAggregator
# (ConnectorRegistry/pools: db_main, redis_cache, s3_main, smtp_main, ...).
# Прежний путь (monitoring.health_check) не существовал — S102 сломал роут,
# S107 поставил заглушку с hard-coded False (ложный «нездоров» сигнал).
_COMPONENT_MAP: dict[str, str] = {
    "database": "db_main",
    "redis": "redis_cache",
    "s3": "s3_main",
    "s3_bucket": "s3_main",
    "smtp": "smtp_main",
    "rabbitmq": "eventbus_main",
    "graylog": "logging_service",
    # "logging_service" (Graylog-транспорт) не зарегистрирован как
    # connector/pool — check_single вернёт "Component not registered" →
    # False (честный «неизвестно/недоступен»).
}


class TechService:
    """Сервис для технических и служебных операций (Healthcheck, ссылки, отправка писем, массовая загрузка)."""

    async def _check_component(self, component: str) -> bool:
        """Health одной компоненты через HealthAggregator (T7 вариант (a))."""
        aggregator = get_health_aggregator_provider()
        name = _COMPONENT_MAP.get(component, component)
        report = await aggregator.check_single(name, mode="fast")
        return report.get("status") == "ok"

    async def get_log_storage_link(self) -> HTMLResponse:
        """Get link to log storage.

        Returns:
            HTML response with link.

        """
        return generate_link_page(
            f"{settings.logging.host}:{settings.logging.port}", "Хранилище логов"
        )

    async def get_file_storage_link(self) -> HTMLResponse:
        """Get link to file storage.

        Returns:
            HTML response with link.

        """
        return generate_link_page(
            f"{settings.storage.interface_endpoint}", "Файловое хранилище"
        )

    async def get_queue_monitor_link(self) -> HTMLResponse:
        """Get link to queue monitor.

        Returns:
            HTML response with link.

        """
        return generate_link_page(settings.queue.queue_ui_url, "Мониторинг очередей")

    async def get_langfuse_link(self) -> HTMLResponse:
        """Get link to LangFuse.

        Returns:
            HTML response with link.

        """
        return generate_link_page(
            settings.app.langfuse_url, "LangFuse — LLM Observability"
        )

    async def get_langgraph_link(self) -> HTMLResponse:
        """Get link to LangGraph Studio.

        Returns:
            HTML response with link.

        """
        return generate_link_page(
            settings.app.langgraph_url, "LangGraph Studio — AI Agents"
        )

    async def check_database(self) -> bool:
        """Check database health (HealthAggregator, компонент ``db_main``).

        Returns:
            True if healthy.

        """
        return await self._check_component("database")

    async def check_redis(self) -> bool:
        """Check Redis health (HealthAggregator, компонент ``redis_cache``).

        Returns:
            True if healthy.

        """
        return await self._check_component("redis")

    async def check_s3(self) -> bool:
        """Check S3 health (HealthAggregator, компонент ``s3_main``).

        Returns:
            True if healthy.

        """
        return await self._check_component("s3")

    async def check_s3_bucket(self) -> bool:
        """Check S3 bucket health (HealthAggregator, компонент ``s3_main``).

        Returns:
            True if healthy.

        """
        return await self._check_component("s3_bucket")

    async def check_graylog(self) -> bool:
        """Check Graylog health (HealthAggregator, компонент ``logging_service``).

        Returns:
            True if healthy.

        """
        return await self._check_component("graylog")

    async def check_smtp(self) -> bool:
        """Check SMTP health (HealthAggregator, компонент ``smtp_main``).

        Returns:
            True if healthy.

        """
        return await self._check_component("smtp")

    async def check_rabbitmq(self) -> bool:
        """Check RabbitMQ health (HealthAggregator, компонент ``eventbus_main``).

        Returns:
            True if healthy.

        """
        return await self._check_component("rabbitmq")

    async def check_all_services(self) -> dict[str, bool]:
        """Health всех зарегистрированных компонент (HealthAggregator.check_all).

        Returns:
            ``{компонента: healthy}`` — статус "ok" → True.
        """
        aggregator = get_health_aggregator_provider()
        report = await aggregator.check_all(mode="fast")
        components = report.get("components", report)
        return {
            name: isinstance(comp, dict) and comp.get("status") == "ok"
            for name, comp in components.items()
            if isinstance(comp, dict)
        }

    async def get_degradation_snapshot(self) -> dict[str, Any]:
        """Снимок зарегистрированных features из GracefulDegradationRegistry.

        S13 K2 W4 wire-up. Возвращает dict ``{feature_name: {state,
        samples, error_rate}}`` — используется для admin-обзора и
        Prometheus exporter'ом (TBD R3).
        """
        from src.backend.core.resilience.graceful_degradation import (
            get_graceful_degradation_registry,
        )

        return get_graceful_degradation_registry().snapshot()

    async def get_all_custom_tables(self, model_enum: Enum) -> set[str]:
        """Метод get_all_custom_tables (см. signature)."""
        return {model.value.__tablename__ for model in model_enum}  # type: ignore

    async def upload_excel_for_mass_create(
        self, file_bytes: bytes, table_name: str, model_enum: Enum
    ) -> list[dict[str, Any]]:
        """Парсит Excel-файл и добавляет записи в БД через BaseService нужной модели."""
        if table_name not in model_enum._member_names_:  # type: ignore
            raise ValueError(f"Таблица {table_name} не найдена.")

        service: BaseService = await get_service_for_model(
            model_enum[table_name].value  # type: ignore
        )

        results: list = []
        if pl is None:
            raise RuntimeError(
                "polars required for Excel-импорт. Install: uv pip install polars"
            )
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


@app_state_singleton("tech_service", factory=TechService)
def get_tech_service() -> TechService:
    """Фабрика: TechService."""
    raise NotImplementedError  # заменяется декоратором
