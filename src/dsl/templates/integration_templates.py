"""Готовые шаблоны интеграционных pipeline.

Типовые сценарии, которые можно использовать out-of-the-box
или адаптировать под конкретные задачи.

Использование:
    from app.dsl.templates.integration_templates import IntegrationTemplates

    # ETL pipeline: получить → трансформировать → загрузить
    pipeline = IntegrationTemplates.etl(
        source_action="external_crm.get_users",
        transform_expression="data.items",
        target_action="users.add",
    )

    # Webhook relay: получить → валидировать → разослать
    pipeline = IntegrationTemplates.webhook_relay(
        source_route="webhook.incoming",
        targets=["orders.process", "notifications.send"],
    )
"""

from typing import Any, Callable

from app.dsl.builder import RouteBuilder
from app.dsl.engine.exchange import Exchange
from app.dsl.engine.pipeline import Pipeline
from app.dsl.engine.processors import (
    DispatchActionProcessor,
    LogProcessor,
    SetHeaderProcessor,
    ValidateProcessor,
)

__all__ = ("IntegrationTemplates",)


class IntegrationTemplates:
    """Библиотека готовых интеграционных шаблонов."""

    @staticmethod
    def etl(
        source_action: str,
        target_action: str,
        *,
        transform_expression: str | None = None,
        route_id: str | None = None,
        validation_schema: type | None = None,
    ) -> Pipeline:
        """ETL pipeline: Extract → Transform → Load.

        Args:
            source_action: Action для извлечения данных.
            target_action: Action для загрузки данных.
            transform_expression: jmespath для трансформации.
            route_id: ID маршрута (авто если None).
            validation_schema: Pydantic-модель для валидации.
        """
        rid = route_id or f"etl.{source_action}_to_{target_action}"
        builder = (
            RouteBuilder.from_(rid, source=f"template:etl")
            .set_header("x-template", "etl")
            .dispatch_action(source_action, result_property="extracted")
        )

        if transform_expression:
            builder = builder.transform(transform_expression)

        if validation_schema:
            builder = builder.validate(validation_schema)

        return builder.dispatch_action(target_action).log().build()

    @staticmethod
    def webhook_relay(
        source_route: str,
        targets: list[str],
        *,
        route_id: str | None = None,
        parallel: bool = True,
    ) -> Pipeline:
        """Webhook Relay: получить → разослать на N targets.

        Args:
            source_route: Исходный route_id.
            targets: Список route_id для рассылки.
            parallel: Параллельная отправка.
        """
        rid = route_id or f"relay.{source_route}"
        return (
            RouteBuilder.from_(rid, source="template:webhook_relay")
            .set_header("x-template", "webhook_relay")
            .log()
            .recipient_list(
                recipients_expression=lambda _: targets,
                parallel=parallel,
            )
            .build()
        )

    @staticmethod
    def sync_with_retry(
        source_action: str,
        target_action: str,
        *,
        max_attempts: int = 3,
        route_id: str | None = None,
    ) -> Pipeline:
        """Sync with Retry: синхронизация с повтором при ошибке.

        Args:
            source_action: Откуда берём данные.
            target_action: Куда загружаем.
            max_attempts: Число попыток.
        """
        rid = route_id or f"sync.{source_action}_to_{target_action}"
        return (
            RouteBuilder.from_(rid, source="template:sync_retry")
            .set_header("x-template", "sync_retry")
            .dispatch_action(source_action)
            .retry(
                [DispatchActionProcessor(action=target_action)],
                max_attempts=max_attempts,
                backoff="exponential",
            )
            .log()
            .build()
        )

    @staticmethod
    def enrichment_pipeline(
        main_action: str,
        enrichment_actions: list[str],
        *,
        route_id: str | None = None,
    ) -> Pipeline:
        """Enrichment: основной запрос + обогащение из N источников.

        Args:
            main_action: Основной action.
            enrichment_actions: Список actions для обогащения.
        """
        rid = route_id or f"enrich.{main_action}"
        builder = (
            RouteBuilder.from_(rid, source="template:enrichment")
            .set_header("x-template", "enrichment")
            .dispatch_action(main_action)
        )

        for i, enrich_action in enumerate(enrichment_actions):
            builder = builder.enrich(enrich_action, result_property=f"enrichment_{i}")

        return builder.log().build()

    @staticmethod
    def saga_workflow(
        steps: list[tuple[str, str | None]],
        *,
        route_id: str = "saga.workflow",
    ) -> Pipeline:
        """Saga Workflow: шаги с компенсациями.

        Args:
            steps: [(forward_action, compensate_action | None), ...]
        """
        from app.dsl.engine.processors import SagaStep

        saga_steps = [
            SagaStep(
                forward=DispatchActionProcessor(action=fwd),
                compensate=DispatchActionProcessor(action=comp) if comp else None,
            )
            for fwd, comp in steps
        ]

        return (
            RouteBuilder.from_(route_id, source="template:saga")
            .set_header("x-template", "saga")
            .saga(saga_steps)
            .log()
            .build()
        )

    @staticmethod
    def scheduled_poll(
        poll_action: str,
        process_action: str,
        *,
        route_id: str | None = None,
        split_expression: str | None = None,
    ) -> Pipeline:
        """Scheduled Poll: периодический опрос → обработка.

        Args:
            poll_action: Action для получения данных.
            process_action: Action для обработки каждого элемента.
            split_expression: jmespath для разбиения результата на элементы.
        """
        rid = route_id or f"poll.{poll_action}"
        builder = (
            RouteBuilder.from_(rid, source="template:scheduled_poll")
            .set_header("x-template", "scheduled_poll")
            .dispatch_action(poll_action)
        )

        if split_expression:
            builder = builder.split(
                split_expression,
                [DispatchActionProcessor(action=process_action)],
            )
        else:
            builder = builder.dispatch_action(process_action)

        return builder.log().build()

    @staticmethod
    def format_bridge(
        source_action: str,
        target_action: str,
        *,
        from_format: str = "json",
        to_format: str = "xml",
        route_id: str | None = None,
    ) -> Pipeline:
        """Format Bridge: конвертация формата между системами.

        Args:
            source_action: Источник данных.
            target_action: Получатель данных.
            from_format: Входной формат (json, xml, csv).
            to_format: Выходной формат.
        """
        rid = route_id or f"bridge.{from_format}_to_{to_format}"
        return (
            RouteBuilder.from_(rid, source="template:format_bridge")
            .set_header("x-template", "format_bridge")
            .dispatch_action(source_action)
            .translate(from_format, to_format)
            .dispatch_action(target_action)
            .log()
            .build()
        )
