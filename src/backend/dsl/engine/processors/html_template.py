"""DSL-процессор ``html_template`` — Jinja2-рендеринг HTML/text шаблонов.

Wave ``[wave:s5/k3-w1-processor-pack-1]``.

Поддерживает sandbox-окружение Jinja2 для безопасного рендеринга
пользовательских шаблонов (без доступа к небезопасным атрибутам/функциям).
Контекст берётся из ``exchange.in_message.body`` (если dict) или передаётся
явно через параметр ``context``. Результат пишется в ``out_message.body``.

Контракт DSL (Camel-style Python)::

    .html_template(template="Hello {{ name }}!", to="body.greeting")

YAML-форма::

    - html_template:
        template: "Hello {{ name }}!"
        to: body.greeting

Feature flag ``feature_flags.proc_html_template`` управляет активацией:
при ``False`` процессор пропускает работу и помечает status=skipped.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import processor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


__all__ = ("HtmlTemplateProcessor",)


@processor(
    "html_template",
    namespace="core",
    spec_schema={
        "type": "object",
        "properties": {
            "template": {"type": "string"},
            "to": {"type": "string"},
            "context_from": {
                "type": "string",
                "enum": ["body", "properties", "merged"],
            },
            "autoescape": {"type": "boolean"},
        },
        "required": ["template"],
    },
    meta={"tier": 1, "category": "transform"},
    tags=("template", "html", "jinja2"),
)
class HtmlTemplateProcessor(BaseProcessor):
    """Sandbox-рендеринг шаблона Jinja2 (HTML/text).

    Args:
        template: Строка шаблона Jinja2.
        to: Путь записи результата (``body.<field>`` или ``properties.<name>``).
            По умолчанию ``body.rendered``.
        context_from: Источник контекста — ``body`` (default), ``properties``,
            ``merged`` (объединение body+properties, properties перекрывает body).
        autoescape: Включить autoescape для HTML (по умолчанию True для безопасности).
    """

    def __init__(
        self,
        template: str,
        *,
        to: str = "body.rendered",
        context_from: str = "body",
        autoescape: bool = True,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "html_template")
        if not template:
            raise ValueError("html_template: template must be non-empty")
        if context_from not in {"body", "properties", "merged"}:
            raise ValueError(
                f"html_template: context_from must be 'body'|'properties'|'merged', "
                f"got {context_from!r}"
            )
        self._template_source = template
        self._target = to
        self._context_from = context_from
        self._autoescape = autoescape

    def _collect_context(self, exchange: "Exchange[Any]") -> dict[str, Any]:
        body = exchange.in_message.body
        body_dict = dict(body) if isinstance(body, dict) else {"body": body}
        props = dict(exchange.properties)
        match self._context_from:
            case "body":
                return body_dict
            case "properties":
                return props
            case "merged":
                merged = dict(body_dict)
                merged.update(props)
                return merged
            case _:
                return body_dict

    def _apply_target(self, exchange: "Exchange[Any]", value: str) -> None:
        if self._target.startswith("body."):
            field = self._target[len("body.") :]
            body = exchange.in_message.body
            if not isinstance(body, dict):
                body = {}
                exchange.in_message.body = body  # type: ignore[assignment]
            body[field] = value
            return
        if self._target.startswith("properties."):
            field = self._target[len("properties.") :]
            exchange.set_property(field, value)
            return
        exchange.set_property(self._target, value)

    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        try:
            from src.backend.core.config.features import feature_flags

            if not feature_flags.proc_html_template:
                exchange.set_property("html_template_status", "skipped")
                return
        except Exception:  # noqa: BLE001
            # feature flags недоступны — продолжаем работу (для unit-тестов)
            pass

        try:
            from jinja2.sandbox import SandboxedEnvironment
        except ImportError as exc:
            exchange.fail(f"html_template: jinja2 not available: {exc}")
            return

        env = SandboxedEnvironment(autoescape=self._autoescape)
        try:
            tmpl = env.from_string(self._template_source)
            rendered = tmpl.render(**self._collect_context(exchange))
        except Exception as exc:  # noqa: BLE001
            exchange.fail(f"html_template render error: {exc}")
            return

        self._apply_target(exchange, rendered)

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {"template": self._template_source}
        if self._target != "body.rendered":
            spec["to"] = self._target
        if self._context_from != "body":
            spec["context_from"] = self._context_from
        if not self._autoescape:
            spec["autoescape"] = self._autoescape
        return {"html_template": spec}
