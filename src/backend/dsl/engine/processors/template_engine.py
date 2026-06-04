"""TemplateEngine processors — Jinja2 рендеринг из строки/файла."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


__all__ = ("RenderTemplateFileProcessor", "RenderTemplateProcessor")


def _resolve_context(exchange: Exchange[Any], context_from: str) -> dict[str, Any]:
    if context_from == "body":
        body = exchange.in_message.body
        return body if isinstance(body, dict) else {}
    if context_from.startswith("body."):
        body = exchange.in_message.body
        if isinstance(body, dict):
            return body.get(context_from[5:], {}) or {}
        return {}
    if context_from.startswith("properties."):
        return exchange.properties.get(context_from[11:], {}) or {}
    return {}


def _safe_template_path(path: str) -> str:
    """Защита от path-traversal в шаблонах."""
    safe = os.path.normpath(path)
    if safe.startswith("..") or safe.startswith("/"):
        raise ValueError(f"Invalid template path: {path!r}")
    return safe


class RenderTemplateProcessor(BaseProcessor):
    """Рендерит Jinja2-шаблон из строки."""

    def __init__(
        self,
        *,
        template_string: str,
        context_from: str = "body",
        result_property: str = "rendered",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "render_template")
        self._template_string = template_string
        self._context_from = context_from
        self._result_property = result_property

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from jinja2 import Template

        tmpl = Template(self._template_string, autoescape=True)
        ctx = _resolve_context(exchange, self._context_from)
        result = tmpl.render(ctx)
        exchange.set_property(self._result_property, result)
        exchange.set_out(
            body=exchange.in_message.body, headers=dict(exchange.in_message.headers)
        )

    def to_spec(self) -> dict[str, Any] | None:
        return {
            "render_template": {
                "template_string": self._template_string,
                "context_from": self._context_from,
                "result_property": self._result_property,
            }
        }


class RenderTemplateFileProcessor(BaseProcessor):
    """Рендерит Jinja2-шаблон из файла."""

    def __init__(
        self,
        *,
        path: str,
        context_from: str = "body",
        result_property: str = "rendered",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"render_template_file({path})")
        self._path = path
        self._context_from = context_from
        self._result_property = result_property

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from jinja2 import Environment, FileSystemLoader

        safe_path = _safe_template_path(self._path)
        base_dir = os.path.dirname(safe_path) or "."
        template_name = os.path.basename(safe_path)
        env = Environment(loader=FileSystemLoader(base_dir), autoescape=True)
        tmpl = env.get_template(template_name)
        ctx = _resolve_context(exchange, self._context_from)
        result = tmpl.render(ctx)
        exchange.set_property(self._result_property, result)
        exchange.set_out(
            body=exchange.in_message.body, headers=dict(exchange.in_message.headers)
        )

    def to_spec(self) -> dict[str, Any] | None:
        return {
            "render_template_file": {
                "path": self._path,
                "context_from": self._context_from,
                "result_property": self._result_property,
            }
        }
