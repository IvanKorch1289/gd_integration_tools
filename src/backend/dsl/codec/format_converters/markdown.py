"""S58 W3 — markdown.py part of format_converters decomp.

Classes: MarkdownToHtmlProcessor, HtmlToMarkdownProcessor.

Markdown ↔ HTML conversion + _simple_html_to_markdown helper.
"""
from __future__ import annotations

import datetime as _dt
import importlib
import io
import json
from typing import Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

_logger = get_logger("dsl.format_converters")

class MarkdownToHtmlProcessor(BaseProcessor):
    """Markdown → HTML через ``markdown-it-py`` (transitive dep, есть в стеке)."""

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(self, *, preset: str = "commonmark", name: str | None = None) -> None:
        super().__init__(name=name or "markdown_to_html")
        self._preset = preset

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Обработать exchange согласно логике процессора. Читает body / properties, мутирует exchange, raises exceptions для error handling pipeline."""
        from markdown_it import MarkdownIt

        body = exchange.in_message.body
        if not isinstance(body, str):
            exchange.fail("markdown_to_html: body must be str")
            return
        md = MarkdownIt(self._preset)
        html = md.render(body)
        exchange.set_out(body=html, headers=dict(exchange.in_message.headers))

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализовать конфигурацию процессора в dict (для YAML/JSON spec). Returns None для non-serializable state."""
        spec: dict[str, Any] = {}
        if self._preset != "commonmark":
            spec["preset"] = self._preset
        return {"markdown_to_html": spec}

class HtmlToMarkdownProcessor(BaseProcessor):
    """HTML → Markdown.

    Если установлен пакет ``markdownify`` — используется он.
    Иначе используется простая эвристика на базе ``html.parser`` для
    основных тегов (h1-h6 / p / a / strong / em / ul / ol / code / pre).
    Для banking-кейсов markdown-вывод обычно достаточен; продакшн
    рекомендуется ставить ``markdownify`` через extras.
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(self, *, name: str | None = None) -> None:
        super().__init__(name=name or "html_to_markdown")

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Обработать exchange согласно логике процессора. Читает body / properties, мутирует exchange, raises exceptions для error handling pipeline."""
        body = exchange.in_message.body
        if not isinstance(body, str):
            exchange.fail("html_to_markdown: body must be str")
            return
        md = self._convert(body)
        exchange.set_out(body=md, headers=dict(exchange.in_message.headers))

    @staticmethod
    def _convert(html: str) -> str:
        """Опциональный путь через ``markdownify`` или fallback на эвристику."""
        try:
            import markdownify as _mdfy
        except ImportError:
            return _simple_html_to_markdown(html)
        return str(_mdfy.markdownify(html, heading_style="ATX"))

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализовать конфигурацию процессора в dict (для YAML/JSON spec). Returns None для non-serializable state."""
        return {"html_to_markdown": {}}

def _simple_html_to_markdown(html: str) -> str:
    """Минимальная эвристика HTML → Markdown без сторонних зависимостей."""
    from html.parser import HTMLParser

    class _MdParser(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.parts: list[str] = []
            self._stack: list[str] = []
            self._href: str | None = None

        def handle_starttag(
            self, tag: str, attrs: list[tuple[str, str | None]]
        ) -> None:
            self._stack.append(tag)
            mapping = {
                "h1": "\n# ",
                "h2": "\n## ",
                "h3": "\n### ",
                "h4": "\n#### ",
                "h5": "\n##### ",
                "h6": "\n###### ",
                "p": "\n",
                "br": "\n",
                "strong": "**",
                "b": "**",
                "em": "*",
                "i": "*",
                "code": "`",
                "li": "\n- ",
                "pre": "\n```\n",
            }
            if tag in mapping:
                self.parts.append(mapping[tag])
            elif tag == "a":
                for k, v in attrs:
                    if k == "href":
                        self._href = v
                self.parts.append("[")

        def handle_endtag(self, tag: str) -> None:
            if self._stack and self._stack[-1] == tag:
                self._stack.pop()
            mapping_close = {
                "strong": "**",
                "b": "**",
                "em": "*",
                "i": "*",
                "code": "`",
                "pre": "\n```\n",
                "p": "\n",
            }
            if tag in mapping_close:
                self.parts.append(mapping_close[tag])
            elif tag == "a":
                href = self._href or ""
                self.parts.append(f"]({href})")
                self._href = None

        def handle_data(self, data: str) -> None:
            self.parts.append(data)

    parser = _MdParser()
    parser.feed(html)
    return "".join(parser.parts).strip()

