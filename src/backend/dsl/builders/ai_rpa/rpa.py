"""AI / RPA / Banking-AI миксин для RouteBuilder.

Группа: call_llm / call_llm_with_fallback / cache / cache_write /
guardrails / semantic_route / mcp_tool / agent_graph / rag_search /
compose_prompt / parse_llm_output / token_budget / sanitize_pii /
restore_pii / get_feedback_examples / publish_event / load_memory /
save_memory; banking AI (kyc_aml_verify / antifraud_score /
credit_scoring_rag / customer_chatbot / appeal_ai / tx_categorize /
findoc_ocr_llm); RPA (navigate / click / fill_form / extract /
screenshot / run_scenario / citrix / terminal_3270 / appium_mobile /
email_driven / keystroke_replay / scrape / paginate / api_proxy).

Stateless — см. контракт в ``base.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from src.backend.dsl.engine.exchange import Exchange

if TYPE_CHECKING:
    from src.backend.dsl.builder import RouteBuilder


class RPAMixin:
    """Поведенческий миксин RPA / automation / documents для ``RouteBuilder``.

    Stateless: использует ``self._add`` / ``self._add_lazy`` через MRO.
    """

    __slots__ = ()

    # --- RPA / automation / documents methods (S51 W2 extraction) ---

    def navigate(self, url: str) -> RouteBuilder:
        """Открыть URL в браузере (Playwright)."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.web", "NavigateProcessor", url=url
        )

    def click(self, url: str, selector: str) -> RouteBuilder:
        """Клик по CSS-селектору."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.web",
            "ClickProcessor",
            url=url,
            selector=selector,
        )

    def fill_form(
        self, url: str, fields: dict | None = None, submit: str | None = None
    ) -> RouteBuilder:
        """Заполнение формы по полям + опциональный submit."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.web",
            "FillFormProcessor",
            url=url,
            fields=fields,
            submit=submit,
        )

    def extract(
        self, selector: str, url: str | None = None, output_property: str = "extracted"
    ) -> RouteBuilder:
        """Извлечение текста по CSS-селектору."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.web",
            "ExtractProcessor",
            url=url,
            selector=selector,
            output_property=output_property,
        )

    def screenshot(self, url: str | None = None) -> RouteBuilder:
        """Скриншот страницы как bytes."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.web", "ScreenshotProcessor", url=url
        )

    def run_scenario(self, steps: list[dict] | None = None) -> RouteBuilder:
        """Multi-step web сценарий (navigate/click/fill/extract)."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.web", "RunScenarioProcessor", steps=steps
        )

    def call_llm_with_fallback(
        self, providers: list[str], *, model: str = "default"
    ) -> RouteBuilder:
        """LLM с fallback-цепочкой провайдеров."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.ai",
            "LLMFallbackProcessor",
            providers=providers,
            model=model,
        )

    def cache(
        self, key_fn: Callable[[Exchange[Any]], str], *, ttl: int = 3600
    ) -> RouteBuilder:
        """Redis-кеш: проверяет наличие по ключу, пропускает если есть."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.ai",
            "CacheProcessor",
            key_fn=key_fn,
            ttl_seconds=ttl,
        )

    def cache_write(
        self, key_fn: Callable[[Exchange[Any]], str], *, ttl: int = 3600
    ) -> RouteBuilder:
        """Redis-кеш: записывает результат после обработки."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.ai",
            "CacheWriteProcessor",
            key_fn=key_fn,
            ttl_seconds=ttl,
        )

    def guardrails(
        self,
        *,
        max_length: int = 10000,
        blocked_patterns: list[str] | None = None,
        required_fields: list[str] | None = None,
    ) -> RouteBuilder:
        """Проверка LLM output на безопасность (длина, blocklist, required fields)."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.ai",
            "GuardrailsProcessor",
            max_length=max_length,
            blocked_patterns=blocked_patterns,
            required_fields=required_fields,
        )

    def semantic_route(
        self,
        intents: dict[str, str],
        *,
        default_route: str | None = None,
        query_field: str = "question",
        threshold: float = 0.5,
        namespace: str = "intents",
    ) -> RouteBuilder:
        """Semantic routing — RAG-based intent detection → выбор маршрута."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.ai",
            "SemanticRouterProcessor",
            intents=intents,
            default_route=default_route,
            query_field=query_field,
            threshold=threshold,
            namespace=namespace,
        )

    def pdf_read(self, *, extract_tables: bool = False) -> RouteBuilder:
        """Извлечь текст и таблицы из PDF.

        Body: bytes (содержимое PDF) или str (путь к файлу).
        Результат: {"text": "...", "pages": [...], "tables": [...]}
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.rpa",
            "PdfReadProcessor",
            extract_tables=extract_tables,
        )

    def pdf_merge(self) -> RouteBuilder:
        """Объединить несколько PDF в один.

        Body: list[bytes] — список PDF-файлов.
        Результат: bytes (merged PDF).
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.rpa", "PdfMergeProcessor"
        )

    def word_read(self) -> RouteBuilder:
        """Извлечь текст из .docx файла.

        Body: bytes или str (путь).
        Результат: {"text": "...", "paragraphs": [...]}
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.rpa", "WordReadProcessor"
        )

    def word_write(self) -> RouteBuilder:
        """Генерировать .docx документ из текста.

        Body: dict с ключами "paragraphs" (list[str]) или "text" (str).
        Результат: bytes (.docx файл).
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.rpa", "WordWriteProcessor"
        )

    def excel_read(self, *, sheet_name: str | None = None) -> RouteBuilder:
        """Читать Excel файл в list[dict].

        Body: bytes или str (путь).
        Результат: list[dict] (rows).
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.rpa",
            "ExcelReadProcessor",
            sheet_name=sheet_name,
        )

    def file_move(
        self, src: str | None = None, dst: str | None = None, *, mode: str = "copy"
    ) -> RouteBuilder:
        """Копировать или переместить файл.

        mode: "copy" (default), "move", "rename".
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.rpa",
            "FileMoveProcessor",
            src=src,
            dst=dst,
            mode=mode,
        )

    def archive(self, *, mode: str = "extract", format: str = "zip") -> RouteBuilder:
        """Создать или распаковать архив (ZIP/TAR).

        mode: "extract" (default), "create".
        format: "zip" (default), "tar", "gztar", "bztar", "xztar".
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.rpa",
            "ArchiveProcessor",
            mode=mode,
            format=format,
        )

    def ocr(self, *, lang: str = "eng+rus") -> RouteBuilder:
        """OCR — оптическое распознавание текста из изображений/PDF.

        Body: bytes (image/PDF) или str (путь к файлу).
        Результат: {"text": "...", "pages": [...]}
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.rpa", "ImageOcrProcessor", lang=lang
        )

    def image_resize(
        self,
        *,
        width: int | None = None,
        height: int | None = None,
        output_format: str = "PNG",
    ) -> RouteBuilder:
        """Изменить размер изображения.

        width/height: целевые размеры (None = авто).
        output_format: "PNG" (default), "JPEG", "GIF", "BMP", "WEBP".
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.rpa",
            "ImageResizeProcessor",
            width=width,
            height=height,
            output_format=output_format,
        )
