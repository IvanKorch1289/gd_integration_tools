"""TemplateEngineMixin (S39 W3c) — synchronous Jinja2 templating для RouteBuilder.

Methods:
- render_template(template_str, context=...) → str
- render_file(template_path, context=...) → str
- render_email(subject_template, body_template, context=...) → (str, str)
- render_document(template_path, output_path, context=...) → int (bytes written)
- register_filter(name, fn) → RouteBuilder (chainable)

Lazy jinja2 import; stdlib ``pathlib``; str/Path supported.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from jinja2 import Environment

    from src.backend.dsl.builders.base import RouteBuilder

__all__ = ("TemplateEngineMixin",)

PathLike = str | Path
Context = dict[str, Any]


class TemplateEngineMixin:
    """Jinja2 templating utilities для ``RouteBuilder`` (S39 W3c).

    Synchronous rendering API для email/document/etc. Custom filters via
    :meth:`register_filter`. Backed by a per-builder ``jinja2.Environment``
    (lazy init, cached в ``_jinja_env``).
    """

    __slots__ = ()

    def _get_env(self: RouteBuilder) -> Environment:  # type: ignore
        """Lazy init + cache ``jinja2.Environment`` per builder."""
        env: Environment | None = getattr(self, "_jinja_env", None)
        if env is None:
            from jinja2 import Environment

            env = Environment(autoescape=True)
            object.__setattr__(self, "_jinja_env", env)
        return env

    def register_filter(  # type: ignore
        self: RouteBuilder, name: str, fn: Callable[..., Any]
    ) -> RouteBuilder:
        """Register custom Jinja2 filter (chainable)."""
        self._get_env().filters[name] = fn  # type: ignore
        return self

    def template_render_str(  # type: ignore
        self: RouteBuilder, template_str: str, context: Context | None = None
    ) -> str:
        """Render Jinja2 template из строки. Returns rendered string.

        Note: renamed from `render_template` to avoid conflict with
        ``ai_rpa.AIRPAMixin.render_template(template)`` which adds a
        RenderTemplateProcessor to the pipeline. Use this method to
        synchronously render a string template; use AIRPAMixin's
        `render_template(template)` to add a pipeline processor.
        """
        if context is None:
            context = {}
        return self._get_env().from_string(template_str).render(**context)  # type: ignore

    def render_file(  # type: ignore
        self: RouteBuilder, template_path: PathLike, context: Context | None = None
    ) -> str:
        """Render Jinja2 template из файла (str | Path)."""
        if context is None:
            context = {}
        path = Path(template_path)
        return (
            self._get_env()  # type: ignore
            .from_string(path.read_text(encoding="utf-8"))
            .render(**context)
        )

    def render_email(  # type: ignore
        self: RouteBuilder,
        subject_template: str,
        body_template: str,
        context: Context | None = None,
    ) -> tuple[str, str]:
        """Render email subject + body. Returns ``(subject, body)`` tuple."""
        if context is None:
            context = {}
        env = self._get_env()  # type: ignore
        return (
            env.from_string(subject_template).render(**context),
            env.from_string(body_template).render(**context),
        )

    def render_document(  # type: ignore
        self: RouteBuilder,
        template_path: PathLike,
        output_path: PathLike,
        context: Context | None = None,
    ) -> int:
        """Render template file → output file. Returns bytes written."""
        rendered = self.render_file(template_path, context)  # type: ignore
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        return out.write_text(rendered, encoding="utf-8")

    def html_template(  # type: ignore
        self: RouteBuilder,
        template: str,
        *,
        to: str = "body.html",
        context_from: str = "body",
        autoescape: bool = True,
    ) -> RouteBuilder:
        """Render Jinja2 HTML template (async DSL processor).

        Args:
            template: Jinja2 template string.
            to: Destination dotted-path.
            context_from: Source: ``"body"``, ``"properties"``, or ``"merged"``.
            autoescape: Enable HTML autoescaping.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.html_template",
            "HtmlTemplateProcessor",
            template=template,
            to=to,
            context_from=context_from,
            autoescape=autoescape,
        )

    def pdf_template(  # type: ignore
        self: RouteBuilder,
        template: str,
        *,
        to: str = "body.pdf_bytes",
        page_size: str = "A4",
        font_size: int = 12,
    ) -> RouteBuilder:
        """Generate PDF from Jinja2 template via ReportLab.

        Args:
            template: Jinja2 template string.
            to: Destination dotted-path for PDF bytes.
            page_size: ``"A4"``, ``"LETTER"``, ``"A3"``, ``"A5"``.
            font_size: Base font size.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.pdf_template",
            "PdfTemplateProcessor",
            template=template,
            to=to,
            page_size=page_size,
            font_size=font_size,
        )
