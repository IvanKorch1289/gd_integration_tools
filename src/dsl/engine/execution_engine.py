from typing import Any

from app.core.config.runtime_state import disabled_feature_flags
from app.core.errors import RouteDisabledError
from app.dsl.engine.context import ExecutionContext
from app.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from app.dsl.engine.pipeline import Pipeline

__all__ = ("ExecutionEngine",)


class ExecutionEngine:
    """
    Исполнитель DSL-маршрутов.

    Responsibilities:
    - создает или принимает Exchange;
    - проверяет feature-флаг маршрута;
    - проставляет route metadata;
    - последовательно вызывает процессоры;
    - переводит Exchange в completed/failed;
    - обеспечивает единый runtime-flow для HTTP, stream и gRPC.
    """

    @staticmethod
    def _check_feature_flag(pipeline: Pipeline) -> None:
        """Проверяет, не заблокирован ли маршрут feature-флагом."""
        if (
            pipeline.feature_flag is not None
            and pipeline.feature_flag in disabled_feature_flags
        ):
            raise RouteDisabledError(
                route_id=pipeline.route_id,
                feature_flag=pipeline.feature_flag,
            )

    async def execute(
        self,
        pipeline: Pipeline,
        *,
        exchange: Exchange[Any] | None = None,
        body: Any = None,
        headers: dict[str, Any] | None = None,
        context: ExecutionContext | None = None,
    ) -> Exchange[Any]:
        """
        Выполняет маршрут.

        Args:
            pipeline: Описание маршрута.
            exchange: Уже созданный Exchange.
            body: Тело сообщения, если Exchange еще не создан.
            headers: Заголовки сообщения, если Exchange еще не создан.
            context: Контекст выполнения маршрута.

        Returns:
            Exchange[Any]: Итоговый Exchange после выполнения.

        Raises:
            RouteDisabledError: Если маршрут заблокирован
                feature-флагом.
        """
        self._check_feature_flag(pipeline)

        runtime_context = context or ExecutionContext()
        current_exchange = exchange or Exchange(
            in_message=Message(body=body, headers=headers or {})
        )

        current_exchange.meta.route_id = pipeline.route_id
        current_exchange.meta.source = pipeline.source
        current_exchange.status = ExchangeStatus.processing

        for processor in pipeline.processors:
            if current_exchange.status == ExchangeStatus.failed:
                break
            if current_exchange.stopped:
                break

            try:
                if runtime_context.logger is not None:
                    runtime_context.logger.debug(
                        "Executing DSL processor '%s' for route '%s'",
                        processor.name,
                        pipeline.route_id,
                    )

                await processor.process(current_exchange, runtime_context)

            except Exception as exc:
                if runtime_context.logger is not None:
                    runtime_context.logger.exception(
                        "DSL processor '%s' failed in route '%s'",
                        processor.name,
                        pipeline.route_id,
                    )

                current_exchange.fail(str(exc))
                break

        if current_exchange.status != ExchangeStatus.failed:
            if current_exchange.out_message is None:
                current_exchange.complete(
                    body=current_exchange.in_message.body,
                    headers=dict(current_exchange.in_message.headers),
                )
            else:
                current_exchange.status = ExchangeStatus.completed

        return current_exchange
