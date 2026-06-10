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

from src.backend.dsl.builders.ai_rpa.ai_llm import AILlMMixin  # S51 W1: MRO composition


class AIRPAMixin(AILlMMixin):
    """Поведенческий миксин AI / RPA / Banking-AI для ``RouteBuilder``.

S51 W1: 18 AI/LLM methods вынесены в ``ai_llm.py`` (AILlMMixin).
W2+: RPA / automation / scripts groups follow.
Stateless: использует ``self._add`` / ``self._add_lazy`` через MRO.
"""

    __slots__ = ()

    # --- remaining methods (after S51 W1 extraction) ---

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



    def regex(
        self, pattern: str, *, action: str = "extract", replacement: str = ""
    ) -> RouteBuilder:
        """Извлечь или заменить текст по регулярному выражению.

        action: "extract" (default), "replace", "match", "split", "findall".
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.rpa",
            "RegexProcessor",
            pattern=pattern,
            action=action,
            replacement=replacement,
        )



    def render_template(self, template: str) -> RouteBuilder:
        """Рендеринг Jinja2-шаблона.

        Body: dict с переменными контекста.
        Результат: str (отрендеренный шаблон).
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.rpa",
            "TemplateRenderProcessor",
            template=template,
        )



    def hash(self, *, algorithm: str = "sha256") -> RouteBuilder:
        """Хеширование тела сообщения.

        algorithm: "sha256" (default), "md5", "sha1", "sha512", "blake2b".
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.rpa",
            "HashProcessor",
            algorithm=algorithm,
        )



    def encrypt(self, key: str) -> RouteBuilder:
        """Шифрование тела сообщения (AES-GCM).

        key: Base64-encoded AES-ключ (16, 24 или 32 байта).
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.rpa", "EncryptProcessor", key=key
        )



    def decrypt(self, key: str) -> RouteBuilder:
        """Дешифрование AES-GCM-сообщения.

        key: тот же ключ, что использовался для encrypt.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.rpa", "DecryptProcessor", key=key
        )



    def shell(
        self,
        command: str,
        *,
        args: list[str] | None = None,
        allowed_commands: list[str] | None = None,
        timeout_seconds: float = 30.0,
    ) -> RouteBuilder:
        """Выполнить shell-команду.

        command: имя команды (не full path).
        allowed_commands: whitelist допустимых команд (security).
        timeout_seconds: лимит времени выполнения.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.rpa",
            "ShellExecProcessor",
            command=command,
            args=args,
            allowed_commands=allowed_commands,
            timeout_seconds=timeout_seconds,
        )



    def email(self, to: str, subject: str, body_template: str) -> RouteBuilder:
        """Compose + отправка email через SMTP.

        Body: dict с переменными для template или str.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.rpa",
            "EmailComposeProcessor",
            to=to,
            subject=subject,
            body_template=body_template,
        )



    def citrix(self, operation: str, session_id: str) -> RouteBuilder:
        """Citrix/RDP-сессия (launch/click/type/screenshot/close)."""
        from src.backend.dsl.engine.processors.rpa_banking import CitrixSessionProcessor

        return self._add(  # type: ignore[attr-defined]
            CitrixSessionProcessor(operation=operation, session_id=session_id)
        )



    def terminal_3270(
        self, host: str, port: int = 23, action: str = "query"
    ) -> RouteBuilder:
        """IBM 3270 терминал-эмулятор (мейнфрейм)."""
        from src.backend.dsl.engine.processors.rpa_banking import (
            TerminalEmulator3270Processor,
        )

        return self._add(  # type: ignore[attr-defined]
            TerminalEmulator3270Processor(host=host, port=port, action=action)
        )



    def appium_mobile(
        self, platform: str, app_package: str, operation: str
    ) -> RouteBuilder:
        """Appium автоматизация мобильных приложений (android/ios)."""
        from src.backend.dsl.engine.processors.rpa_banking import AppiumMobileProcessor

        return self._add(  # type: ignore[attr-defined]
            AppiumMobileProcessor(
                platform=platform, app_package=app_package, operation=operation
            )
        )



    def email_driven(
        self,
        mailbox: str = "INBOX",
        subject_filter: str | None = None,
        extract: str = "body_table",
    ) -> RouteBuilder:
        """IMAP → structured data pipeline."""
        from src.backend.dsl.engine.processors.rpa_banking import EmailDrivenProcessor

        return self._add(  # type: ignore[attr-defined]
            EmailDrivenProcessor(
                mailbox=mailbox, subject_filter=subject_filter, extract=extract
            )
        )



    def keystroke_replay(self, script_name: str) -> RouteBuilder:
        """Воспроизведение записанного сценария клавиатуры/мыши."""
        from src.backend.dsl.engine.processors.rpa_banking import (
            KeystrokeReplayProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            KeystrokeReplayProcessor(script_name=script_name)
        )



    def kyc_aml_verify(self, jurisdiction: str = "ru") -> RouteBuilder:
        """KYC/AML верификация клиента."""
        from src.backend.dsl.engine.processors.ai_banking import KycAmlVerifyProcessor

        return self._add(  # type: ignore[attr-defined]
            KycAmlVerifyProcessor(jurisdiction=jurisdiction)
        )



    def antifraud_score(self, model: str = "default") -> RouteBuilder:
        """LLM-скоринг антифрода (поверх детерминистических правил)."""
        from src.backend.dsl.engine.processors.ai_banking import AntiFraudScoreProcessor

        return self._add(  # type: ignore[attr-defined]
            AntiFraudScoreProcessor(model=model)
        )



    def credit_scoring_rag(self, product: str = "retail") -> RouteBuilder:
        """Кредитный скоринг через RAG."""
        from src.backend.dsl.engine.processors.ai_banking import (
            CreditScoringRagProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            CreditScoringRagProcessor(product=product)
        )



    def customer_chatbot(self, channel: str = "web") -> RouteBuilder:
        """Клиентский чат-бот (tool-use: balance, statement, faq, escalate)."""
        from src.backend.dsl.engine.processors.ai_banking import (
            CustomerChatbotProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            CustomerChatbotProcessor(channel=channel)
        )



    def appeal_ai(self) -> RouteBuilder:
        """Автоматическая обработка клиентских обращений."""
        from src.backend.dsl.engine.processors.ai_banking import AppealProcessorAI

        return self._add(AppealProcessorAI())  # type: ignore[attr-defined]



    def tx_categorize(self, taxonomy: str = "mcc") -> RouteBuilder:
        """Категоризация транзакций (MCC + merchant normalization)."""
        from src.backend.dsl.engine.processors.ai_banking import (
            TransactionCategorizerProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            TransactionCategorizerProcessor(taxonomy=taxonomy)
        )



    def findoc_ocr_llm(self, doc_type: str = "invoice") -> RouteBuilder:
        """OCR + LLM для финансовых документов."""
        from src.backend.dsl.engine.processors.ai_banking import FinDocOcrLlmProcessor

        return self._add(  # type: ignore[attr-defined]
            FinDocOcrLlmProcessor(doc_type=doc_type)
        )



    def script_python(
        self,
        code: str,
        *,
        timeout_seconds: float = 30.0,
        env: dict[str, str] | None = None,
        allowed_languages: list[str] | None = None,
    ) -> RouteBuilder:
        """Выполнить inline Python-код через текущий интерпретатор.

        Результат пишется в exchange body как
        ``{"stdout", "stderr", "exit_code", "language"}``.
        """
        from src.backend.dsl.engine.processors.script_runner import (
            ScriptRunnerProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            ScriptRunnerProcessor(
                language="python",
                code=code,
                timeout_seconds=timeout_seconds,
                env=env,
                allowed_languages=allowed_languages,
            )
        )



    def script_node(
        self,
        code: str,
        *,
        timeout_seconds: float = 30.0,
        env: dict[str, str] | None = None,
        allowed_languages: list[str] | None = None,
    ) -> RouteBuilder:
        """Выполнить inline Node.js-код (требует ``node`` в PATH)."""
        from src.backend.dsl.engine.processors.script_runner import (
            ScriptRunnerProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            ScriptRunnerProcessor(
                language="node",
                code=code,
                timeout_seconds=timeout_seconds,
                env=env,
                allowed_languages=allowed_languages,
            )
        )



    def script_ruby(
        self,
        code: str,
        *,
        timeout_seconds: float = 30.0,
        env: dict[str, str] | None = None,
        allowed_languages: list[str] | None = None,
    ) -> RouteBuilder:
        """Выполнить inline Ruby-код (требует ``ruby`` в PATH)."""
        from src.backend.dsl.engine.processors.script_runner import (
            ScriptRunnerProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            ScriptRunnerProcessor(
                language="ruby",
                code=code,
                timeout_seconds=timeout_seconds,
                env=env,
                allowed_languages=allowed_languages,
            )
        )



    def script_shell(
        self,
        code: str,
        *,
        timeout_seconds: float = 30.0,
        env: dict[str, str] | None = None,
        allowed_languages: list[str] | None = None,
    ) -> RouteBuilder:
        """Выполнить shell-скрипт через ``/bin/sh`` (whitelist рекомендуется)."""
        from src.backend.dsl.engine.processors.script_runner import (
            ScriptRunnerProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            ScriptRunnerProcessor(
                language="shell",
                code=code,
                timeout_seconds=timeout_seconds,
                env=env,
                allowed_languages=allowed_languages,
            )
        )

