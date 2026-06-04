"""TemplateEngineChainMixin — chainable .jinja_template / .jinja_template_file.

Использует Jinja2 (lazy import).
Stateless — см. контракт в ``base.py``.

Note: для синхронного рендера (render_template / render_email / …) см.
:class:`src.backend.dsl.builders.template_engine_mixin.TemplateEngineMixin`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backend.dsl.builder import RouteBuilder


class TemplateEngineChainMixin:
    """Chainable Jinja2-step mixin для ``RouteBuilder``."""

    __slots__ = ()

    def jinja_template(
        self,
        template_string: str,
        *,
        context_from: str = "body",
        result_property: str = "rendered",
    ) -> RouteBuilder:
        """Рендерит Jinja2-шаблон из строки.

        Args:
            template_string: Текст шаблона Jinja2.
            context_from: Источник контекста — ``"body"`` (dict) |
                ``"body.field"`` | ``"properties.name"``.
            result_property: Имя property для записи результата.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.template_engine",
            "RenderTemplateProcessor",
            template_string=template_string,
            context_from=context_from,
            result_property=result_property,
        )

    def jinja_template_file(
        self,
        path: str,
        *,
        context_from: str = "body",
        result_property: str = "rendered",
    ) -> RouteBuilder:
        """Рендерит Jinja2-шаблон из файла.

        Args:
            path: Путь к файлу шаблона.
            context_from: Источник контекста — ``"body"`` | ``"body.field"`` |
                ``"properties.name"``.
            result_property: Имя property для записи результата.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.template_engine",
            "RenderTemplateFileProcessor",
            path=path,
            context_from=context_from,
            result_property=result_property,
        )
