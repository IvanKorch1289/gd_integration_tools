"""Unit-тесты PresidioSanitizerAdapter (S24 W1, ADR-NEW-16).

Покрывают граничные сценарии адаптера без обязательной установки presidio:

* Graceful fallback на :class:`AIDataSanitizer` при отсутствии presidio пакета;
* Sync API (`sanitize_text`, `sanitize_messages`, `restore_text`);
* Async API raises RuntimeError при недоступности Presidio;
* Singleton фабрика возвращает один и тот же экземпляр.

Интеграционные сценарии (с реальным Presidio + ru_core_news_lg) живут в
``tests/integration/ai/test_presidio_integration.py`` и используют
``pytest.importorskip``.
"""

from __future__ import annotations

import pytest

from src.backend.infrastructure.security.ai_sanitizer import SanitizationResult


def test_adapter_imports_without_presidio() -> None:
    """Модуль импортируется даже если presidio не установлен."""
    from src.backend.services.ai.pii.presidio_analyzer import (
        PresidioSanitizerAdapter,
        get_presidio_sanitizer_adapter,
    )

    assert PresidioSanitizerAdapter is not None
    assert callable(get_presidio_sanitizer_adapter)


def test_adapter_available_is_false_without_presidio() -> None:
    """Без установленного `presidio_analyzer` adapter.available == False."""
    from src.backend.services.ai.pii.presidio_analyzer import PresidioSanitizerAdapter

    adapter = PresidioSanitizerAdapter()
    # Если presidio установлен в окружении — пропускаем; иначе available=False.
    try:
        import presidio_analyzer  # noqa: F401
    except ImportError:
        assert adapter.available is False


def test_sync_sanitize_text_delegates_to_legacy() -> None:
    """Sync API возвращает SanitizationResult и маскирует через legacy regex."""
    from src.backend.services.ai.pii.presidio_analyzer import PresidioSanitizerAdapter

    adapter = PresidioSanitizerAdapter()
    result = adapter.sanitize_text("Email: user@example.com, тел +7 999 123-45-67")
    assert isinstance(result, SanitizationResult)
    assert "user@example.com" not in result.sanitized_text
    assert "[EMAIL_1]" in result.sanitized_text or "[EMAIL" in result.sanitized_text


def test_sync_sanitize_messages_returns_tuple() -> None:
    """sanitize_messages возвращает (sanitized_messages, mapping)."""
    from src.backend.services.ai.pii.presidio_analyzer import PresidioSanitizerAdapter

    adapter = PresidioSanitizerAdapter()
    messages = [
        {"role": "user", "content": "Мой email: foo@bar.ru"},
        {"role": "assistant", "content": "Ответ без PII"},
    ]
    sanitized, mapping = adapter.sanitize_messages(messages)
    assert isinstance(sanitized, list)
    assert len(sanitized) == 2
    assert sanitized[0]["role"] == "user"
    assert "foo@bar.ru" not in sanitized[0]["content"]
    assert isinstance(mapping, dict)


def test_static_restore_text_round_trip() -> None:
    """restore_text возвращает оригинал по mapping."""
    from src.backend.services.ai.pii.presidio_analyzer import PresidioSanitizerAdapter

    adapter = PresidioSanitizerAdapter()
    result = adapter.sanitize_text("Email: a@b.com")
    restored = adapter.restore_text(result.sanitized_text, result.replacements)
    assert "a@b.com" in restored


@pytest.mark.asyncio
async def test_async_sanitize_raises_when_presidio_unavailable() -> None:
    """async API явно бросает RuntimeError при недоступности Presidio."""
    from src.backend.services.ai.pii.presidio_analyzer import PresidioSanitizerAdapter

    try:
        import presidio_analyzer  # noqa: F401
    except ImportError:
        adapter = PresidioSanitizerAdapter()
        with pytest.raises(RuntimeError, match="Presidio"):
            await adapter.sanitize_async("foo@bar.com")


def test_singleton_factory_returns_same_instance() -> None:
    """get_presidio_sanitizer_adapter() возвращает один и тот же объект."""
    from src.backend.services.ai.pii.presidio_analyzer import (
        get_presidio_sanitizer_adapter,
    )

    a = get_presidio_sanitizer_adapter()
    b = get_presidio_sanitizer_adapter()
    assert a is b


def test_di_provider_uses_legacy_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_ai_sanitizer_provider() при PRESIDIO_PII_ENABLED=False → legacy AIDataSanitizer."""
    from src.backend.core.config import features
    from src.backend.core.di import providers

    monkeypatch.setattr(
        features.feature_flags, "presidio_pii_enabled", False, raising=True
    )
    # Сбросить override от предыдущих тестов
    providers._overrides.pop("ai_sanitizer", None)
    sanitizer = providers.get_ai_sanitizer_provider()
    assert type(sanitizer).__name__ == "AIDataSanitizer"


def test_di_provider_uses_presidio_adapter_when_flag_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_ai_sanitizer_provider() при PRESIDIO_PII_ENABLED=True → PresidioSanitizerAdapter."""
    from src.backend.core.config import features
    from src.backend.core.di import providers

    monkeypatch.setattr(
        features.feature_flags, "presidio_pii_enabled", True, raising=True
    )
    providers._overrides.pop("ai_sanitizer", None)
    sanitizer = providers.get_ai_sanitizer_provider()
    assert type(sanitizer).__name__ == "PresidioSanitizerAdapter"


def test_deprecation_shim_emits_warning() -> None:
    """Legacy `PresidioSanitizer` из infra поднимает DeprecationWarning."""
    with pytest.warns(DeprecationWarning, match="deprecated с S24 W1"):
        from src.backend.infrastructure.security.presidio_sanitizer import (
            PresidioSanitizer,
        )

        PresidioSanitizer(language="en")
