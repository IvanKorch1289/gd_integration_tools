"""Web Automation DSL процессоры — navigate, click, fill, extract, screenshot."""

from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

__all__ = (
    "NavigateProcessor",
    "ClickProcessor",
    "FillFormProcessor",
    "ExtractProcessor",
    "ScreenshotProcessor",
    "RunScenarioProcessor",
)


class NavigateProcessor(BaseProcessor):
    """Открывает URL в браузере, результат в properties."""

    def __init__(
        self,
        url: str | None = None,
        url_property: str | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        self._url = url
        self._url_property = url_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from src.backend.services.io.web_automation import get_web_automation_service

        svc = get_web_automation_service()
        url = self._url
        if self._url_property:
            url = exchange.properties.get(self._url_property, url)
        if not url:
            body = exchange.in_message.body
            url = body.get("url") if isinstance(body, dict) else str(body)
        result = await svc.navigate(url)
        exchange.set_property("page_info", result)


class ClickProcessor(BaseProcessor):
    """Кликает по CSS-селектору на текущей странице."""

    def __init__(self, url: str, selector: str, name: str | None = None) -> None:
        super().__init__(name)
        self._url = url
        self._selector = selector

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from src.backend.services.io.web_automation import get_web_automation_service

        svc = get_web_automation_service()
        result = await svc.click(self._url, self._selector)
        exchange.set_property("click_result", result)


class FillFormProcessor(BaseProcessor):
    """Заполняет форму на странице."""

    def __init__(
        self,
        url: str,
        fields: dict[str, str] | None = None,
        submit: str | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        self._url = url
        self._fields = fields or {}
        self._submit = submit

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from src.backend.services.io.web_automation import get_web_automation_service

        svc = get_web_automation_service()
        fields = self._fields
        if not fields:
            body = exchange.in_message.body
            fields = body if isinstance(body, dict) else {}
        result = await svc.fill_form(self._url, fields, self._submit)
        exchange.set_property("form_result", result)


class ExtractProcessor(BaseProcessor):
    """Извлекает текст по CSS-селектору."""

    def __init__(
        self,
        url: str | None = None,
        selector: str = "body",
        output_property: str = "extracted",
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        self._url = url
        self._selector = selector
        self._output = output_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from src.backend.services.io.web_automation import get_web_automation_service

        svc = get_web_automation_service()
        url = self._url
        if not url:
            body = exchange.in_message.body
            url = body.get("url") if isinstance(body, dict) else str(body)
        texts = await svc.extract_text(url, self._selector)
        exchange.set_property(self._output, texts)


class ScreenshotProcessor(BaseProcessor):
    """Делает скриншот страницы."""

    def __init__(
        self,
        url: str | None = None,
        output_property: str = "screenshot",
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        self._url = url
        self._output = output_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from src.backend.services.io.web_automation import get_web_automation_service

        svc = get_web_automation_service()
        url = self._url
        if not url:
            body = exchange.in_message.body
            url = body.get("url") if isinstance(body, dict) else str(body)
        data = await svc.screenshot(url)
        exchange.set_property(self._output, data)
        exchange.set_property(f"{self._output}_size", len(data))


class RunScenarioProcessor(BaseProcessor):
    """Выполняет multi-step сценарий из body или параметра."""

    def __init__(
        self, steps: list[dict[str, Any]] | None = None, name: str | None = None
    ) -> None:
        super().__init__(name)
        self._steps = steps

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from src.backend.services.io.web_automation import get_web_automation_service

        svc = get_web_automation_service()
        steps = self._steps
        if not steps:
            body = exchange.in_message.body
            steps = body.get("steps") if isinstance(body, dict) else []
        results = await svc.run_scenario(steps or [])
        exchange.set_property("scenario_results", results)
        exchange.in_message.set_body(results)
