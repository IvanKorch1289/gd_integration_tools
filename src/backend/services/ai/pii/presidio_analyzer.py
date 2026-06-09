"""Presidio + ru NER PII detector / anonymizer (S24 W1, ADR-NEW-16).

Реализует :class:`AISanitizerProtocol` (sync, backward-compat) и
:class:`AsyncPIISanitizerProtocol` (async, новый S24 W1 API). Используется
вместо legacy ``infrastructure.security.ai_sanitizer.AIDataSanitizer`` при
включённом feature-flag ``PRESIDIO_PII_ENABLED``.

Состав:
    * Lazy-init `AnalyzerEngine` (`NlpEngineProvider` с моделями en + ru);
    * `AnonymizerEngine` для replace/redact/hash-операторов;
    * 4 custom recognizers (INN, СНИЛС, паспорт РФ, номер кредитного дела);
    * Graceful fallback: при отсутствии установленных пакетов presidio/spaCy
      адаптер делегирует sync API legacy regex-санайзеру (`AIDataSanitizer`).

Multi-language switching:
    spaCy ``NlpEngineProvider`` поддерживает несколько моделей; язык на запрос
    выбирается явно (`PresidioSanitizerAdapter.sanitize_text(..., language="ru")`),
    а при отсутствии явного указания используется `default_language`
    из конструктора (по умолчанию ``ru`` для банковского домена).

Lazy-init pattern:
    Тяжёлые импорты (`presidio_analyzer`, `presidio_anonymizer`, `spacy`) и
    загрузка модели ``ru_core_news_lg`` (~1.5GB) выполняются при первом
    вызове ``_ensure_initialized()``. Это позволяет CLI / dev_light стартовать
    без presidio extra и не блокирует тесты, которые не активируют PII layer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.backend.core.interfaces.sanitization import SanitizationResult
from src.backend.core.logging import get_logger

if TYPE_CHECKING:
    from presidio_analyzer import AnalyzerEngine, EntityRecognizer
    from presidio_anonymizer import AnonymizerEngine

__all__ = ("PresidioSanitizerAdapter", "get_presidio_sanitizer_adapter")

logger = get_logger("services.ai.pii.presidio")


def _resolve_legacy_sanitizer() -> Any:
    """Lazy resolve legacy AIDataSanitizer через core/di/providers.

    Импорт infrastructure через composition root (`core.di.providers`)
    устраняет прямой layer violation `services → infrastructure`.
    Возвращает реализацию `AISanitizerProtocol` (legacy regex-стек).
    """
    from src.backend.core.di.providers import resolve_module

    module = resolve_module("security.ai_sanitizer")
    return module.get_ai_sanitizer()


class PresidioSanitizerAdapter:
    """Адаптер Presidio + ru NER под :class:`AISanitizerProtocol`.

    Sync API делегирует legacy `AIDataSanitizer` при отсутствии presidio
    (graceful fallback); async API всегда использует Presidio analyze
    (поднимает RuntimeError, если Presidio недоступен — async-callers
    обязаны иметь feature-flag guard перед вызовом).
    """

    def __init__(
        self, *, default_language: str = "ru", legacy_fallback: Any | None = None
    ) -> None:
        self._default_language = default_language
        # Lazy fallback: legacy AIDataSanitizer резолвится при первом
        # использовании через DI-composition-root, не на init.
        self._legacy_fallback: Any | None = legacy_fallback
        self._analyzer: AnalyzerEngine | None = None
        self._anonymizer: AnonymizerEngine | None = None
        self._available: bool | None = None  # tri-state: None=unknown

    @property
    def _legacy(self) -> Any:
        """Возвращает legacy sanitizer, резолвя его lazily через DI."""
        if self._legacy_fallback is None:
            self._legacy_fallback = _resolve_legacy_sanitizer()
        return self._legacy_fallback

    # ─── lazy-init ────────────────────────────────────────────────────────

    def _ensure_initialized(self) -> bool:
        """Инициализирует Presidio engine при первом вызове.

        Возвращает True, если Presidio доступен; False — если установка
        пакетов отсутствует или модель ``ru_core_news_lg`` не загружена.
        После первого вызова результат кэшируется в ``self._available``.

        При fallback на legacy regex-санитайзер инкрементирует Prometheus
        counter ``presidio_fallback_total{reason="<...>"}`` для алертов на
        утрату NER-покрытия в production.
        """
        if self._available is not None:
            return self._available
        try:
            from presidio_analyzer import AnalyzerEngine
            from presidio_analyzer.nlp_engine import NlpEngineProvider
            from presidio_anonymizer import AnonymizerEngine
        except ImportError as exc:
            logger.warning(
                "Presidio/spaCy недоступны, fallback на AIDataSanitizer: %s", exc
            )
            _record_presidio_fallback(reason="import_error")
            self._available = False
            return False

        try:
            provider = NlpEngineProvider(
                nlp_configuration={
                    "nlp_engine_name": "spacy",
                    "models": [
                        {"lang_code": "ru", "model_name": "ru_core_news_lg"},
                        {"lang_code": "en", "model_name": "en_core_web_lg"},
                    ],
                }
            )
            nlp_engine = provider.create_engine()
            analyzer = AnalyzerEngine(
                nlp_engine=nlp_engine, supported_languages=["ru", "en"]
            )
            for recognizer in self._build_custom_recognizers():
                analyzer.registry.add_recognizer(recognizer)
            self._analyzer = analyzer
            self._anonymizer = AnonymizerEngine()
            self._available = True
            logger.info(
                "Presidio AnalyzerEngine инициализирован (ru+en, %d custom recognizers)",
                len(list(self._build_custom_recognizers())),
            )
            return True
        except Exception as exc:
            logger.warning(
                "Presidio init failed (%s), fallback на AIDataSanitizer", exc
            )
            _record_presidio_fallback(reason="init_error")
            self._available = False
            return False

    @staticmethod
    def _build_custom_recognizers() -> list[EntityRecognizer]:
        """Регистрирует 7 custom recognizers для русских domain-сущностей.

        Импортируется отдельным методом, чтобы изолировать тяжёлые импорты
        от main module-load (lazy-pattern).

        S24 W1: INN, СНИЛС, паспорт, кредитное дело (4).
        S28 W5: адрес, банковский счёт, водительское удостоверение (+3 = 7).
        """
        from src.backend.services.ai.pii.recognizers import (
            AddressRuRecognizer,
            BankAccountRuRecognizer,
            CreditCaseRecognizer,
            DriverLicenseRuRecognizer,
            InnRecognizer,
            PassportRuRecognizer,
            SnilsRecognizer,
        )

        return [
            InnRecognizer(),
            SnilsRecognizer(),
            PassportRuRecognizer(),
            CreditCaseRecognizer(),
            AddressRuRecognizer(),  # S28 W5
            BankAccountRuRecognizer(),  # S28 W5
            DriverLicenseRuRecognizer(),  # S28 W5
        ]

    # ─── sync API (AISanitizerProtocol) ───────────────────────────────────

    def sanitize_text(self, text: str) -> SanitizationResult:
        """Sync-маскирование: делегирует legacy при отсутствии Presidio.

        Async-callers (RAG retrieval, Langfuse callback) должны использовать
        `sanitize_async()` — он гарантированно использует Presidio (с явной
        ошибкой при недоступности).
        """
        if not self._ensure_initialized():
            return self._legacy.sanitize_text(text)
        return self._presidio_sanitize_sync(text, language=self._default_language)

    def sanitize_messages(
        self, messages: list[dict[str, str]]
    ) -> tuple[list[dict[str, str]], dict[str, str]]:
        """Маскирует list[{role, content}] и возвращает кумулятивный mapping."""
        if not self._ensure_initialized():
            return self._legacy.sanitize_messages(messages)

        full_mapping: dict[str, str] = {}
        sanitized: list[dict[str, str]] = []
        for msg in messages:
            content = msg.get("content", "")
            result = self._presidio_sanitize_sync(
                content, language=self._default_language
            )
            full_mapping.update(result.replacements)
            sanitized.append({**msg, "content": result.sanitized_text})
        return sanitized, full_mapping

    @staticmethod
    def restore_text(text: str, mapping: dict[str, str]) -> str:
        """Восстанавливает оригиналы по mapping (placeholder → original)."""
        result = text
        for placeholder, original in mapping.items():
            result = result.replace(placeholder, original)
        return result

    # ─── async API (AsyncPIISanitizerProtocol) ────────────────────────────

    async def sanitize_async(
        self, text: str, *, language: str | None = None
    ) -> SanitizationResult:
        """Async-маскирование через Presidio.

        Raises:
            RuntimeError: если Presidio недоступен в production (`PRESIDIO_PII_ENABLED=True`,
                но `presidio_analyzer` не установлен или модель ru_core_news_lg не загружена).
                Callers обязаны иметь feature-flag guard перед вызовом.
        """
        if not self._ensure_initialized():
            raise RuntimeError(
                "PresidioSanitizerAdapter.sanitize_async вызван, но Presidio "
                "недоступен. Установите extra `[ai-safety]` и выполните "
                "`make pii-bootstrap` (загрузка ru_core_news_lg)."
            )
        return self._presidio_sanitize_sync(
            text, language=language or self._default_language
        )

    async def sanitize_messages_async(
        self, messages: list[dict[str, str]]
    ) -> tuple[list[dict[str, str]], dict[str, str]]:
        """Async-версия sanitize_messages."""
        if not self._ensure_initialized():
            raise RuntimeError(
                "PresidioSanitizerAdapter.sanitize_messages_async требует "
                "доступный Presidio. См. `make pii-bootstrap`."
            )

        full_mapping: dict[str, str] = {}
        sanitized: list[dict[str, str]] = []
        for msg in messages:
            content = msg.get("content", "")
            result = self._presidio_sanitize_sync(
                content, language=self._default_language
            )
            full_mapping.update(result.replacements)
            sanitized.append({**msg, "content": result.sanitized_text})
        return sanitized, full_mapping

    # ─── presidio internal ────────────────────────────────────────────────

    def _presidio_sanitize_sync(
        self, text: str, *, language: str
    ) -> SanitizationResult:
        """Внутренняя sync-операция: analyze + anonymize + mapping для restore.

        Возвращает :class:`SanitizationResult` (структура legacy `AIDataSanitizer`),
        чтобы callers получили совместимый объект и могли пользоваться `.restore()`.
        """
        if not text or not isinstance(text, str):
            return SanitizationResult(sanitized_text=text or "", replacements={})

        analyzer = self._analyzer
        if analyzer is None:
            # Защита от рассинхронизации lazy-init и _available; должна быть
            # недостижима после успешного _ensure_initialized().
            return self._legacy.sanitize_text(text)
        try:
            analyzer_results = analyzer.analyze(text=text, language=language)
        except Exception as exc:
            logger.warning(
                "Presidio analyze failed (%s), fallback на legacy regex", exc
            )
            return self._legacy.sanitize_text(text)

        replacements: dict[str, str] = {}
        sanitized = text
        for idx, r in enumerate(sorted(analyzer_results, key=lambda x: -x.start)):
            placeholder = f"[{r.entity_type}_{idx + 1}]"
            original = text[r.start : r.end]
            sanitized = sanitized[: r.start] + placeholder + sanitized[r.end :]
            replacements[placeholder] = original

        return SanitizationResult(sanitized_text=sanitized, replacements=replacements)

    # ─── introspection ────────────────────────────────────────────────────

    @property
    def available(self) -> bool:
        """True если Presidio engine инициализирован успешно."""
        self._ensure_initialized()
        return bool(self._available)


_instance: PresidioSanitizerAdapter | None = None


def get_presidio_sanitizer_adapter(
    *, default_language: str = "ru"
) -> PresidioSanitizerAdapter:
    """Singleton-фабрика PresidioSanitizerAdapter для DI providers.

    Используется в `core.di.providers.get_ai_sanitizer_provider()` под
    feature-flag `PRESIDIO_PII_ENABLED`. При повторных вызовах возвращает
    тот же экземпляр (engine инициализируется один раз).
    """
    global _instance
    if _instance is None:
        _instance = PresidioSanitizerAdapter(default_language=default_language)
    return _instance


def _record_presidio_fallback(*, reason: str) -> None:
    """Инкрементирует Prometheus counter ``presidio_fallback_total``.

    Block 1.1 (gap-ai-1.1) — production-enforcement: при включённом
    ``PRESIDIO_PII_ENABLED`` любой fallback на legacy regex-санайзер
    должен быть наблюдаемым. Алерт на ``rate(presidio_fallback_total[5m]) > 0``
    в production сигнализирует утрату NER-покрытия (отсутствует extra
    ``[security-pii]`` либо spaCy-модель не загружена).

    Реализация через ``metrics_registry`` (centralized) — при отсутствии
    prometheus_client (минимальный профиль) — no-op.

    Args:
        reason: Причина fallback (``import_error`` / ``init_error``).
    """
    try:
        from src.backend.core.utils.metrics_registry import metrics_registry

        counter = metrics_registry.counter(
            "presidio_fallback_total",
            "Fallback на legacy AIDataSanitizer при недоступном Presidio",
            labels=("reason",),
        )
        counter.labels(reason=reason).inc()
    except Exception as _:
        logger.debug("presidio_fallback metric emit failed", exc_info=True)
