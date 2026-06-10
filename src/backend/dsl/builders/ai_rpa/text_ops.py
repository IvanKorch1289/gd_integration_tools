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

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backend.dsl.builder import RouteBuilder





class TextOpsMixin:
    """text utilities (regex / templates / hash / encrypt / decrypt) для ``RouteBuilder``. S52 W1 extraction."""

    __slots__ = ()

    # --- text operations (regex, templates, hashing, encryption) ---

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

