"""DSL-процессор ``pdf_template`` — генерация PDF из шаблона через reportlab.

Wave ``[wave:s5/k3-w2-processor-pack-2]``.

Минимальный сценарий: рендер текстового шаблона (с jinja2 substitutions)
в PDF-документ (one-page A4) через ReportLab Canvas. Расширения (таблицы,
картинки) добавляются в payload.

Контракт DSL::

    .pdf_template(
        template="Order #{{ order_id }} for {{ customer }}",
        to="body.pdf_bytes",
    )

YAML::

    - pdf_template:
        template: |
          Account: {{ account }}
          Balance: {{ balance }}
        to: body.pdf_bytes

Feature flag: ``feature_flags.proc_pdf_template`` (default-OFF).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import processor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


__all__ = ("PdfTemplateProcessor",)


_ALLOWED_PAGE_SIZES = frozenset({"A4", "LETTER", "A3", "A5"})


@processor(
    "pdf_template",
    namespace="core",
    spec_schema={
        "type": "object",
        "properties": {
            "template": {"type": "string"},
            "to": {"type": "string"},
            "page_size": {"type": "string", "enum": sorted(_ALLOWED_PAGE_SIZES)},
            "font_size": {"type": "integer"},
            "context_from": {
                "type": "string",
                "enum": ["body", "properties", "merged"],
            },
        },
        "required": ["template"],
    },
    meta={"tier": 1, "category": "documents"},
    tags=("pdf", "template", "documents", "reportlab"),
)
class PdfTemplateProcessor(BaseProcessor):
    """Render Jinja2-template в PDF (one page, multiline-text) через ReportLab.

    Args:
        template: Текстовый шаблон (Jinja2 substitutions ``{{ var }}``).
        to: Куда положить ``bytes`` PDF (``body.<field>`` / ``properties.<name>``).
        page_size: ``A4`` (default) / ``LETTER`` / ``A3`` / ``A5``.
        font_size: Размер шрифта (default 12).
        context_from: ``body`` / ``properties`` / ``merged``.
    """

    def __init__(
        self,
        template: str,
        *,
        to: str = "body.pdf_bytes",
        page_size: str = "A4",
        font_size: int = 12,
        context_from: str = "body",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "pdf_template")
        if not template:
            raise ValueError("pdf_template: template must be non-empty")
        if page_size not in _ALLOWED_PAGE_SIZES:
            raise ValueError(
                f"pdf_template: page_size must be one of {sorted(_ALLOWED_PAGE_SIZES)}, "
                f"got {page_size!r}"
            )
        if context_from not in {"body", "properties", "merged"}:
            raise ValueError(f"pdf_template: context_from invalid: {context_from!r}")
        self._template_source = template
        self._target = to
        self._page_size = page_size
        self._font_size = font_size
        self._context_from = context_from

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

    def _apply_target(self, exchange: "Exchange[Any]", value: bytes) -> None:
        if self._target.startswith("body."):
            field = self._target[len("body.") :]
            body = exchange.in_message.body
            if not isinstance(body, dict):
                body = {}
                exchange.in_message.body = body  
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

            if not feature_flags.proc_pdf_template:
                exchange.set_property("pdf_template_status", "skipped")
                return
        except Exception as _:  # noqa: BLE001
            pass

        # Lazy-import reportlab + jinja2
        try:
            from reportlab.lib.pagesizes import (  
                A3,
                A4,
                A5,
                LETTER,
            )
            from reportlab.pdfgen import canvas  
        except ImportError as exc:
            exchange.fail(f"pdf_template: reportlab not available: {exc}")
            return

        try:
            from jinja2.sandbox import SandboxedEnvironment
        except ImportError as exc:
            exchange.fail(f"pdf_template: jinja2 not available: {exc}")
            return

        env = SandboxedEnvironment(autoescape=False)
        try:
            text = env.from_string(self._template_source).render(
                **self._collect_context(exchange)
            )
        except Exception as exc:  # noqa: BLE001
            exchange.fail(f"pdf_template render error: {exc}")
            return

        page_map = {"A4": A4, "LETTER": LETTER, "A3": A3, "A5": A5}
        page = page_map[self._page_size]

        import io as _io

        buf = _io.BytesIO()
        try:
            c = canvas.Canvas(buf, pagesize=page)
            c.setFont("Helvetica", self._font_size)
            line_h = self._font_size * 1.4
            x = 50
            y = page[1] - 50
            for line in text.splitlines() or [text]:
                if y < 50:
                    c.showPage()
                    c.setFont("Helvetica", self._font_size)
                    y = page[1] - 50
                c.drawString(x, y, line)
                y -= line_h
            c.showPage()
            c.save()
        except Exception as exc:  # noqa: BLE001
            exchange.fail(f"pdf_template canvas error: {exc}")
            return

        self._apply_target(exchange, buf.getvalue())

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {"template": self._template_source}
        if self._target != "body.pdf_bytes":
            spec["to"] = self._target
        if self._page_size != "A4":
            spec["page_size"] = self._page_size
        if self._font_size != 12:
            spec["font_size"] = self._font_size
        if self._context_from != "body":
            spec["context_from"] = self._context_from
        return {"pdf_template": spec}
