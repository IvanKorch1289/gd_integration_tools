"""FW4: smoke-тесты российских LLM-провайдеров (YandexGPT, GigaChat, SaluteSpeech).

Проверяют:
- class import (no real API call)
- instantiation with defaults from settings
- name attribute matches documented provider name
- model + base_url populated from settings
- extract_text работает на OpenAI-format response
- ``RuntimeError("API key not set")`` если ключ пустой
- Один позитивный smoke-тест: extract_text парсит dict
"""
from __future__ import annotations

import pytest



def test_yandexgpt_instantiation_with_defaults() -> None:
    """YandexGPTProvider() — api_key может быть пустой (settings default),
    но model + base_url populated."""
    from src.backend.services.ai.ai_providers.russian import YandexGPTProvider

    p = YandexGPTProvider()
    assert p.name == "yandexgpt"
    assert p.model == "yandexgpt/latest"
    assert p.base_url == "https://llm.api.cloud.yandex.net/v1"
    # api_key from env (YANDEXGPT_API_KEY); likely empty in test env
    assert isinstance(p.api_key, str)


def test_gigachat_instantiation_with_defaults() -> None:
    """GigaChatProvider() — default model ``GigaChat:latest``."""
    from src.backend.services.ai.ai_providers.russian import GigaChatProvider

    p = GigaChatProvider()
    assert p.name == "gigachat"
    assert p.model == "GigaChat:latest"
    assert p.base_url == "https://gigachat.devices.sberbank.ru/api/v1"


def test_salute_speech_instantiation_with_defaults() -> None:
    """SaluteSpeechProvider() — default model ``salute-speech/latest``."""
    from src.backend.services.ai.ai_providers.russian import SaluteSpeechProvider

    p = SaluteSpeechProvider()
    assert p.name == "salute_speech"
    assert p.model == "salute-speech/latest"
    assert p.base_url == "https://salute.online.sberbank.ru:8000/v1"


def test_yandexgpt_extract_text() -> None:
    """extract_text парсит OpenAI-format dict (litellm response)."""
    from src.backend.services.ai.ai_providers.russian import YandexGPTProvider

    p = YandexGPTProvider()
    response = {
        "choices": [
            {"message": {"role": "assistant", "content": "Привет, мир!"}},
        ],
    }
    assert p.extract_text(response) == "Привет, мир!"


def test_yandexgpt_extract_text_empty() -> None:
    """extract_text возвращает ``""`` на пустых/невалидных responses."""
    from src.backend.services.ai.ai_providers.russian import YandexGPTProvider

    p = YandexGPTProvider()
    assert p.extract_text({}) == ""
    assert p.extract_text({"choices": []}) == ""
    assert p.extract_text({"choices": [{}]}) == ""


def test_all_three_providers_registered() -> None:
    """Все 3 провайдера импортируются из top-level пакета (backward-compat)."""
    from src.backend.services.ai.ai_providers import (
        GigaChatProvider,
        SaluteSpeechProvider,
        YandexGPTProvider,
    )

    assert YandexGPTProvider.name == "yandexgpt"
    assert GigaChatProvider.name == "gigachat"
    assert SaluteSpeechProvider.name == "salute_speech"


def test_settings_classes_loaded() -> None:
    """Settings-классы из core.config.ai созданы и singleton'ы доступны."""
    from src.backend.core.config.ai import (
        gigachat_settings,
        salute_speech_settings,
        yandexgpt_settings,
    )

    # Defaults из settings (поля, не значения).
    assert hasattr(yandexgpt_settings, "api_key")
    assert hasattr(yandexgpt_settings, "folder_id")
    assert hasattr(yandexgpt_settings, "base_url")
    assert hasattr(gigachat_settings, "credentials")
    assert hasattr(gigachat_settings, "scope")
    assert hasattr(salute_speech_settings, "credentials")
    assert hasattr(salute_speech_settings, "scope")


@pytest.mark.asyncio
async def test_yandexgpt_chat_raises_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """``chat()`` без API key → ``RuntimeError("API key not set")``."""
    from src.backend.core.config.ai import yandexgpt_settings
    from src.backend.services.ai.ai_providers.russian import YandexGPTProvider

    # Force empty API key
    monkeypatch.setattr(yandexgpt_settings, "api_key", "")

    p = YandexGPTProvider(api_key="")
    with pytest.raises(RuntimeError, match="API key not set"):
        await p.chat([{"role": "user", "content": "hi"}])


def test_provider_litellm_prefix() -> None:
    """YandexGPT + SaluteSpeech используют ``openai/`` prefix (OpenAI-compat);
    GigaChat — ``gigachat/`` (NOT OpenAI-compat)."""
    from src.backend.services.ai.ai_providers.russian import (
        GigaChatProvider,
        SaluteSpeechProvider,
        YandexGPTProvider,
    )

    assert YandexGPTProvider()._provider_prefix() == "openai"
    assert SaluteSpeechProvider()._provider_prefix() == "openai"
    assert GigaChatProvider()._provider_prefix() == "gigachat"
