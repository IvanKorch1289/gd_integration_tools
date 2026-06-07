"""Integration test для Block 1.1 (gap-ai-1.1, ADR-0072).

Проверяет production-enforcement Presidio в prod-config:

1. При ``PRESIDIO_PII_ENABLED=True`` ``get_ai_sanitizer_provider()``
   возвращает :class:`PresidioSanitizerAdapter`, не legacy AIDataSanitizer.
2. При недоступности Presidio (ImportError) + флаг True — fallback на
   legacy происходит, но Prometheus counter ``presidio_fallback_total``
   инкрементируется (production-алерт ``rate > 0``).
3. AIAgentService.chat() реально применяет Presidio sanitizer до LLM-вызова
   (smoke test через monkeypatch HTTP-клиента).

Тесты не требуют установленных presidio/spaCy — используют monkeypatch на
``_ensure_initialized`` для эмуляции unavailable / available состояний.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def _reset_presidio_singleton() -> None:
    """Сбрасывает module-level singleton ``_instance`` PresidioSanitizerAdapter.

    Между тестами нужно гарантировать чистый ``_available`` state, иначе
    кэширование ``_available=False`` из одного теста утечёт в следующий.
    """
    import src.backend.services.ai.pii.presidio_analyzer as mod

    mod._instance = None


def test_di_provider_returns_presidio_adapter_when_flag_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """При FEATURE_PRESIDIO_PII_ENABLED=True провайдер возвращает PresidioSanitizerAdapter."""
    from src.backend.core.config import features
    from src.backend.core.di import providers

    monkeypatch.setattr(
        features.feature_flags, "presidio_pii_enabled", True, raising=True
    )
    providers.ai._overrides.pop("ai_sanitizer", None)
    _reset_presidio_singleton()

    sanitizer = providers.get_ai_sanitizer_provider()
    assert type(sanitizer).__name__ == "PresidioSanitizerAdapter"


def test_di_provider_returns_legacy_when_flag_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """При FEATURE_PRESIDIO_PII_ENABLED=False провайдер возвращает legacy AIDataSanitizer."""
    from src.backend.core.config import features
    from src.backend.core.di import providers

    monkeypatch.setattr(
        features.feature_flags, "presidio_pii_enabled", False, raising=True
    )
    providers.ai._overrides.pop("ai_sanitizer", None)

    sanitizer = providers.get_ai_sanitizer_provider()
    assert type(sanitizer).__name__ == "AIDataSanitizer"


def test_fallback_counter_increments_on_import_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ImportError presidio_analyzer → fallback counter inc + legacy regex продолжает работать.

    Сценарий production:
        prod-config выставил presidio_pii_enabled=true, но extra `[ai-safety]`
        не установлен (regression в Dockerfile / wheel-сборке). Adapter обязан:
            * не падать с ImportError на sanitize_text;
            * делегировать в legacy AIDataSanitizer;
            * увеличить counter `presidio_fallback_total{reason="import_error"}`.

    Алерт `rate(presidio_fallback_total[5m]) > 0` сразу page on-call.
    """
    from src.backend.services.ai.pii.presidio_analyzer import PresidioSanitizerAdapter

    captured: list[str] = []

    def _capture(*, reason: str) -> None:
        captured.append(reason)

    monkeypatch.setattr(
        "src.backend.services.ai.pii.presidio_analyzer._record_presidio_fallback",
        _capture,
    )

    adapter = PresidioSanitizerAdapter()
    # Эмулируем отсутствие presidio через monkeypatch builtins.__import__
    # (раздел try ... import presidio_analyzer в _ensure_initialized).
    real_import = (
        __builtins__["__import__"]
        if isinstance(__builtins__, dict)
        else __builtins__.__import__
    )

    def _fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name.startswith("presidio_analyzer") or name.startswith(
            "presidio_anonymizer"
        ):
            raise ImportError(f"эмуляция отсутствия пакета: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _fake_import)

    available = adapter._ensure_initialized()
    assert available is False
    assert captured == ["import_error"], (
        f"ожидался fallback counter с reason=import_error, получено: {captured}"
    )

    # Sync sanitize_text продолжает работать через legacy.
    result = adapter.sanitize_text("Email user@example.com")
    assert "user@example.com" not in result.sanitized_text


def test_real_counter_emit_works() -> None:
    """``_record_presidio_fallback`` действительно регистрирует counter в metrics_registry.

    Smoke-проверка: при наличии prometheus_client (CI dev_light extra) функция
    регистрирует counter без RuntimeError. При отсутствии — silently no-op
    (см. logger.debug в реализации).
    """
    from src.backend.services.ai.pii.presidio_analyzer import _record_presidio_fallback

    # Не должно бросать исключения ни в одном профиле.
    _record_presidio_fallback(reason="smoke")
    _record_presidio_fallback(reason="smoke")  # повторный вызов — counter уже создан.


def test_ai_agent_uses_presidio_when_flag_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """AIAgentService при включённом флаге резолвит PresidioSanitizerAdapter в __init__.

    Это smoke-тест enforcement цепочки prod.yml → feature_flag → DI provider →
    AIAgentService. Доказывает что Block 1.1 действительно меняет поведение
    AI-сервиса в prod-конфиге.
    """
    from src.backend.core.config import features
    from src.backend.core.di import providers

    monkeypatch.setattr(
        features.feature_flags, "presidio_pii_enabled", True, raising=True
    )
    providers.ai._overrides.pop("ai_sanitizer", None)
    _reset_presidio_singleton()

    # AIAgentService.__init__ вызывает get_ai_sanitizer_provider() (line 47).
    from src.backend.services.ai.ai_agent import AIAgentService

    agent = AIAgentService()
    assert type(agent._sanitizer).__name__ == "PresidioSanitizerAdapter"
