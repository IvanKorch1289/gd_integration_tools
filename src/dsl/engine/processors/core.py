import logging
from typing import Any, Callable

from app.dsl.engine.context import ExecutionContext
from app.dsl.engine.exchange import Exchange
from app.dsl.engine.processors.base import BaseProcessor
from app.schemas.invocation import ActionCommandSchema

__all__ = (
    "SetHeaderProcessor", "SetPropertyProcessor", "DispatchActionProcessor",
    "TransformProcessor", "FilterProcessor", "EnrichProcessor",
    "LogProcessor", "ValidateProcessor",
)


class SetHeaderProcessor(BaseProcessor):
    def __init__(self, key: str, value: Any) -> None:
        super().__init__(name=f"set_header:{key}")
        self.key = key
        self.value = value

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        exchange.in_message.set_header(self.key, self.value)


class SetPropertyProcessor(BaseProcessor):
    def __init__(self, key: str, value: Any) -> None:
        super().__init__(name=f"set_property:{key}")
        self.key = key
        self.value = value

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        exchange.set_property(self.key, self.value)


class DispatchActionProcessor(BaseProcessor):
    def __init__(
        self, action: str, *,
        payload_factory: Callable[[Exchange[Any]], dict[str, Any]] | None = None,
        result_property: str = "action_result",
    ) -> None:
        super().__init__(name=f"dispatch_action:{action}")
        self.action = action
        self.payload_factory = payload_factory
        self.result_property = result_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        if self.payload_factory is not None:
            payload = self.payload_factory(exchange)
        else:
            body = exchange.in_message.body
            payload = body if isinstance(body, dict) else {}
        command = ActionCommandSchema(action=self.action, payload=payload)
        result = await context.action_registry.dispatch(command)
        exchange.set_property(self.result_property, result)
        exchange.set_out(body=result, headers=dict(exchange.in_message.headers))


class TransformProcessor(BaseProcessor):
    def __init__(self, expression: str, *, name: str | None = None) -> None:
        super().__init__(name=name or f"transform:{expression[:30]}")
        self.expression = expression

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        import jmespath
        body = exchange.in_message.body
        result = jmespath.search(self.expression, body)
        exchange.set_out(body=result, headers=dict(exchange.in_message.headers))


class FilterProcessor(BaseProcessor):
    def __init__(self, predicate: Callable[[Exchange[Any]], bool], *, name: str | None = None) -> None:
        super().__init__(name=name or "filter")
        self._predicate = predicate

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        if not self._predicate(exchange):
            exchange.set_property("filtered", True)
            exchange.stop()


class EnrichProcessor(BaseProcessor):
    def __init__(
        self, action: str, *,
        payload_factory: Callable[[Exchange[Any]], dict[str, Any]] | None = None,
        result_property: str = "enrichment", name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"enrich:{action}")
        self.action = action
        self.payload_factory = payload_factory
        self.result_property = result_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        payload = self.payload_factory(exchange) if self.payload_factory else {}
        command = ActionCommandSchema(action=self.action, payload=payload)
        result = await context.action_registry.dispatch(command)
        exchange.set_property(self.result_property, result)


class LogProcessor(BaseProcessor):
    def __init__(self, *, level: str = "info", name: str | None = None) -> None:
        super().__init__(name=name or "log")
        self._level = level

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        logger = logging.getLogger("dsl.pipeline")
        log_fn = getattr(logger, self._level, logger.info)
        log_fn(
            "Exchange[route=%s]: body=%s, properties=%s",
            context.route_id, type(exchange.in_message.body).__name__,
            list(exchange.properties.keys()),
        )


class ValidateProcessor(BaseProcessor):
    def __init__(self, model: type, *, name: str | None = None) -> None:
        super().__init__(name=name or f"validate:{model.__name__}")
        self._model = model

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from pydantic import ValidationError
        body = exchange.in_message.body
        if not isinstance(body, dict):
            exchange.set_error(f"Ожидался dict, получен {type(body).__name__}")
            exchange.stop()
            return
        try:
            validated = self._model.model_validate(body)
            exchange.set_property("validated_payload", validated)
        except ValidationError as exc:
            exchange.set_error(str(exc))
            exchange.stop()
