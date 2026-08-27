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
        """Открыть URL в браузере (Playwright).

        Cycle 29 (production-grade plan): мигрирован с deprecated web.py
        (services.io.web_automation) на rpa_browser (Playwright + capability-gate).
        Поведение улучшено: capability-gate, audit events, cookies persistence.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.rpa_browser",
            "NavigateProcessor",
            url=url,
        )

    def click(self, url: str, selector: str) -> RouteBuilder:
        """Клик по CSS-селектору.

        Cycle 29: Playwright-based (rpa_browser) вместо deprecated web.py.
        Page берётся из предыдущей browser сессии (``rpa.browser.launch``
        + ``rpa_navigate``); ``url`` arg игнорируется (Playwright session).
        """
        if url is not None:
            import warnings as _w

            _w.warn(
                f"rpa.click(url='{url}') — url игнорируется в Playwright mode. "
                f"Используйте rpa_navigate(url) для установки page.",
                DeprecationWarning,
                stacklevel=2,
            )
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.rpa_browser",
            "ClickProcessor",
            selector=selector,
        )

    def fill_form(
        self, url: str, fields: dict | None = None, submit: str | None = None
    ) -> RouteBuilder:
        """Заполнение формы по полям + опциональный submit.

        Cycle 29: остаётся на web.py (FillFormProcessor — единственный
        multi-field form processor в legacy module). Playwright-based
        multi-field эквивалент — Sprint 180+ migration.
        """
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
        """Извлечение текста по CSS-селектору.

        Cycle 29: Playwright-based (rpa_browser) вместо deprecated web.py.
        Page берётся из предыдущей browser сессии (``rpa.browser.launch``
        + ``rpa_navigate``); ``url`` arg игнорируется (Playwright session).

        ``output_property`` → ``to='property:<name>'``.
        """
        kwargs: dict[str, Any] = {"selector": selector, "to": f"property:{output_property}"}
        if url is not None:
            # Backward-compat: warn if explicit url passed (Playwright uses session page)
            import warnings as _w

            _w.warn(
                f"rpa.extract(url='{url}') — url игнорируется в Playwright mode. "
                f"Используйте rpa_navigate(url) для установки page.",
                DeprecationWarning,
                stacklevel=2,
            )
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.rpa_browser",
            "ExtractProcessor",
            **kwargs,
        )

    def screenshot(self, url: str | None = None) -> RouteBuilder:
        """Скриншот страницы как bytes.

        Cycle 29: Playwright-based (rpa_browser) вместо deprecated web.py.
        Page берётся из предыдущей browser сессии (``rpa.browser.launch``
        + ``rpa_navigate``); ``url`` arg игнорируется (Playwright session).
        """
        if url is not None:
            import warnings as _w

            _w.warn(
                f"rpa.screenshot(url='{url}') — url игнорируется в Playwright mode. "
                f"Используйте rpa_navigate(url) для установки page.",
                DeprecationWarning,
                stacklevel=2,
            )
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.rpa_browser",
            "ScreenshotProcessor",
        )

    def browser_launch(self, *, headless: bool = True) -> RouteBuilder:
        """Запустить browser сессию через Playwright pool (P3 gap closure).

        Cycle 30 P3: добавлен builder method для BrowserLaunchProcessor.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.rpa_browser",
            "BrowserLaunchProcessor",
            headless=headless,
        )

    def wait_for_selector(
        self, selector: str, *, timeout_s: float = 30.0
    ) -> RouteBuilder:
        """Ждать появления элемента на странице (P3 gap closure).

        Cycle 30 P3: добавлен builder method для WaitForProcessor.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.rpa_browser",
            "WaitForProcessor",
            selector=selector,
            timeout_s=timeout_s,
        )

    def print_pdf(self, *, format: str = "A4") -> RouteBuilder:
        """Сохранить текущую страницу как PDF (P3 gap closure).

        Cycle 30 P3: добавлен builder method для PdfProcessor.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.rpa_browser",
            "PdfProcessor",
            format=format,
        )

    # P4 (cycle 15, production-grade plan): 5 missing builder methods для
    # rpa_browser.py processors (NavigateProcessor, ClickProcessor,
    # FillProcessor, ExtractProcessor, ScreenshotProcessor). Старые
    # ``navigate()`` / ``click()`` / etc. ссылаются на legacy web.py —
    # эти ``rpa_*()`` builder methods используют правильный rpa_browser.py
    # path (Playwright pool, capability-gated).
    def rpa_navigate(self, *, url: str) -> RouteBuilder:
        """Browser navigate через Playwright (Cycle 15 / P4-A)."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.rpa_browser",
            "NavigateProcessor",
            url=url,
        )

    def rpa_click(self, *, selector: str, timeout: float = 30.0) -> RouteBuilder:
        """Browser click по CSS/XPath селектору (Cycle 15 / P4-A)."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.rpa_browser",
            "ClickProcessor",
            selector=selector,
            timeout=timeout,
        )

    def rpa_fill(self, *, selector: str, value: str) -> RouteBuilder:
        """Browser fill input (Cycle 15 / P4-A)."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.rpa_browser",
            "FillProcessor",
            selector=selector,
            value=value,
        )

    def rpa_extract(
        self, *, selector: str, attribute: str | None = None
    ) -> RouteBuilder:
        """Browser extract text/attribute (Cycle 15 / P4-A)."""
        kwargs: dict[str, Any] = {"selector": selector}
        if attribute is not None:
            kwargs["attribute"] = attribute
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.rpa_browser",
            "ExtractProcessor",
            **kwargs,
        )

    def rpa_screenshot(
        self, *, full_page: bool = False, path: str | None = None
    ) -> RouteBuilder:
        """Browser screenshot (Cycle 15 / P4-A)."""
        kwargs: dict[str, Any] = {"full_page": full_page}
        if path is not None:
            kwargs["path"] = path
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.rpa_browser",
            "ScreenshotProcessor",
            **kwargs,
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
