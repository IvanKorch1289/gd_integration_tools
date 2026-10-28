"""AI / RPA / Banking-AI миксин для RouteBuilder.

Группа: call_llm / call_llm_with_fallback / cache / cache_write /
guardrails / semantic_route / mcp_tool / agent_graph / rag_search /
compose_prompt / parse_llm_output / token_budget / sanitize_pii /
restore_pii / get_feedback_examples / publish_event / load_memory /
save_memory; banking AI (kyc_aml_verify / antifraud_score /
credit_scoring_rag / customer_chatbot / appeal_ai / tx_categorize /
findoc_ocr_llm); RPA (navigate / click / fill_form / extract /
screenshot / browser_launch / wait_for_selector / print_pdf / run_scenario /
csv_read / csv_write / file_delete / file_list / ftp_upload / http_request /
email_read / terminal_exec / citrix / terminal_3270 / appium_mobile /
email_driven / keystroke_replay / scrape / paginate / api_proxy).

Stateless — см. контракт в ``base.py``.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from src.backend.dsl.engine.exchange import Exchange

if TYPE_CHECKING:
    from src.backend.dsl.builder import RouteBuilder

_PROD_ENV_NAMES = frozenset({"prod", "production"})


def _dev_only_password(password: str | None, *, field: str) -> str:
    """Отклонить plaintext-пароль в prod (секрет — только из Vault).

    Args:
        password: Значение пароля (``None``/``""`` — не задан).
        field: Имя DSL-шага для сообщения об ошибке.

    Returns:
        Пустая строка, если пароль не задан; иначе сам пароль.

    Raises:
        ValueError: В prod передан непустой plaintext-пароль.

    """
    if password and os.environ.get("APP_ENV", "").lower() in _PROD_ENV_NAMES:
        raise ValueError(
            f"{field}: plaintext password is dev-only; "
            "in prod read the secret from Vault (vault_read) — prod — Vault"
        )
    return password or ""


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
        kwargs: dict[str, Any] = {
            "selector": selector,
            "to": f"property:{output_property}",
        }
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
            "src.backend.dsl.engine.processors.rpa_browser", "ScreenshotProcessor"
        )

    def browser_launch(self, *, url: str | None = None) -> RouteBuilder:
        """Запустить browser-сессию через Playwright pool (P3 gap closure).

        Args:
            url: Опциональный URL — перейти сразу после старта сессии.

        Returns:
            ``RouteBuilder`` для chaining.

        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.rpa_browser",
            "BrowserLaunchProcessor",
            url=url,
        )

    def wait_for_selector(
        self,
        selector: str | None = None,
        *,
        state: str = "load",
        timeout: float = 30.0,
    ) -> RouteBuilder:
        """Ждать селектор или load-state страницы (P3 gap closure).

        Args:
            selector: CSS/XPath-селектор; если не задан — ждём ``state``.
            state: ``load`` / ``domcontentloaded`` / ``networkidle``.
            timeout: Таймаут ожидания в секундах.

        Returns:
            ``RouteBuilder`` для chaining.

        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.rpa_browser",
            "WaitForProcessor",
            selector=selector,
            state=state,
            timeout=timeout,
        )

    def print_pdf(
        self,
        *,
        format: str = "A4",
        path: str | None = None,
        landscape: bool = False,
    ) -> RouteBuilder:
        """Сохранить текущую страницу как PDF (P3 gap closure).

        Args:
            format: Размер страницы PDF (``"A4"`` по умолчанию).
            path: Куда сохранить файл; ``None`` — в property ``rpa.pdf``.
            landscape: Альбомная ориентация.

        Returns:
            ``RouteBuilder`` для chaining.

        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.rpa_browser",
            "PdfProcessor",
            format=format,
            path=path,
            landscape=landscape,
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

    # --- RPA-шаги, недостижимые из YAML до ADR-0369 (решение D6) ---

    def csv_read(
        self,
        *,
        src: str | None = None,
        content: str | None = None,
        delimiter: str = ",",
        to: str = "body.rows",
    ) -> RouteBuilder:
        """Прочитать CSV (файл или inline-контент) → ``body.rows``.

        Args:
            src: Путь к CSV-файлу.
            content: Inline CSV-строка (альтернатива ``src``).
            delimiter: Разделитель CSV (по умолчанию ``","``).
            to: Куда записать rows.

        Returns:
            ``RouteBuilder`` для chaining.

        Raises:
            ValueError: Не задан ни ``src``, ни ``content``.

        """
        if src is None and content is None:
            raise ValueError("csv_read: требуется src или content")
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.rpa.operations.csvreadprocessor",
            "CsvReadProcessor",
            src=src,
            content=content,
            delimiter=delimiter,
            to=to,
        )

    def csv_write(
        self,
        *,
        dst: str,
        rows: list[dict[str, Any]],
        delimiter: str = ",",
    ) -> RouteBuilder:
        """Записать список dict → CSV-файл.

        Args:
            dst: Путь output-файла.
            rows: Строки (header = ключи первого dict).
            delimiter: Разделитель CSV (по умолчанию ``","``).

        Returns:
            ``RouteBuilder`` для chaining.

        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.rpa.operations.csvwriteprocessor",
            "CsvWriteProcessor",
            dst=dst,
            rows=rows,
            delimiter=delimiter,
        )

    def file_delete(
        self, *, path: str | None = None, missing_ok: bool = True
    ) -> RouteBuilder:
        """Удалить файл или директорию (recursive).

        Args:
            path: Путь к файлу/директории; ``None`` — взять из ``body.path``.
            missing_ok: Не падать, если пути нет (по умолчанию ``True``).

        Returns:
            ``RouteBuilder`` для chaining.

        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.rpa.operations.filedeleteprocessor",
            "FileDeleteProcessor",
            path=path,
            missing_ok=missing_ok,
        )

    def file_list(
        self,
        *,
        pattern: str | None = None,
        recursive: bool = False,
        to: str = "body.files",
    ) -> RouteBuilder:
        """Список файлов по glob-паттерну.

        Args:
            pattern: Glob-паттерн (например ``"/tmp/*.txt"``); ``None`` —
                взять из ``body.pattern``.
            recursive: Рекурсивный поиск (``**``).
            to: Куда записать список.

        Returns:
            ``RouteBuilder`` для chaining.

        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.rpa.operations.filelistprocessor",
            "FileListProcessor",
            pattern=pattern,
            recursive=recursive,
            to=to,
        )

    def ftp_upload(
        self,
        *,
        host: str,
        local_path: str,
        remote_path: str,
        port: int = 21,
        user: str = "",
        password: str | None = None,
        allow_insecure_ftp: bool = False,
    ) -> RouteBuilder:
        """Загрузить локальный файл на FTP/SFTP-сервер.

        Args:
            host: FTP-хост.
            local_path: Путь к локальному файлу.
            remote_path: Путь на сервере.
            port: FTP-порт (по умолчанию ``21``).
            user: Пользователь.
            password: Пароль — **только dev**. В prod пароль обязателен
                из Vault (``prod — Vault``): plaintext-пароль в prod
                отклоняется, секрет читается через ``vault_read(...)``.
            allow_insecure_ftp: Разрешить plaintext-FTP (нужны также
                ``FTP_INSECURE_OK=1`` в env и не-prod профиль).

        Returns:
            ``RouteBuilder`` для chaining.

        Raises:
            ValueError: В prod передан plaintext-пароль.

        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.rpa.operations.ftpuploadprocessor",
            "FtpUploadProcessor",
            host=host,
            port=port,
            user=user,
            password=_dev_only_password(password, field="ftp_upload"),
            local_path=local_path,
            remote_path=remote_path,
            allow_insecure_ftp=allow_insecure_ftp,
        )

    def http_request(
        self,
        *,
        url: str,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: Any = None,
        timeout: float = 30.0,
        to: str = "body",
    ) -> RouteBuilder:
        """Асинхронный HTTP-запрос (GET/POST/PUT/DELETE/PATCH).

        Args:
            url: Target URL.
            method: HTTP-метод.
            headers: Заголовки запроса.
            body: Тело запроса (dict/list → JSON, str → raw).
            timeout: Таймаут в секундах.
            to: Куда записать ``{status, headers, data}``; ``"body"`` —
                само тело exchange.

        Returns:
            ``RouteBuilder`` для chaining.

        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.rpa.operations.httprequestprocessor",
            "HttpRequestProcessor",
            method=method,
            url=url,
            headers=headers,
            body=body,
            timeout=timeout,
            to=to,
        )

    def email_read(
        self,
        *,
        host: str,
        port: int = 993,
        user: str = "",
        password: str | None = None,
        folder: str = "INBOX",
        to: str = "body.emails",
    ) -> RouteBuilder:
        """Прочитать письма IMAP-папки → ``body.emails``.

        Args:
            host: IMAP-хост.
            port: IMAP-порт (по умолчанию ``993``).
            user: Пользователь.
            password: Пароль — **только dev**. В prod пароль обязателен
                из Vault (``prod — Vault``): plaintext-пароль в prod
                отклоняется, секрет читается через ``vault_read(...)``.
            folder: Папка IMAP (по умолчанию ``"INBOX"``).
            to: Куда записать письма.

        Returns:
            ``RouteBuilder`` для chaining.

        Raises:
            ValueError: В prod передан plaintext-пароль.

        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.rpa.system",
            "EmailReadProcessor",
            host=host,
            port=port,
            user=user,
            password=_dev_only_password(password, field="email_read"),
            folder=folder,
            to=to,
        )

    def terminal_exec(
        self,
        *,
        command: str,
        timeout: float = 30.0,
        to: str = "body.output",
        shell: bool = False,
    ) -> RouteBuilder:
        """Выполнить команду терминала (async subprocess).

        Args:
            command: Команда.
            timeout: Таймаут в секундах.
            to: Куда записать stdout.
            shell: ``True`` — ``/bin/sh -c`` (по умолчанию выключено:
                shell-метасимволы не интерпретируются).

        Returns:
            ``RouteBuilder`` для chaining.

        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.rpa.system",
            "TerminalExecProcessor",
            command=command,
            timeout=timeout,
            to=to,
            shell=shell,
        )
