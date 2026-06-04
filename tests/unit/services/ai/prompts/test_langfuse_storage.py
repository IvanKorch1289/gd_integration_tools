"""Unit-тесты для LangfusePromptStorage.

Покрывают:
    - in-memory fallback при отключённом feature-flag;
    - get_prompt из in-memory;
    - save_prompt в in-memory;
    - list_prompts;
    - lazy-import Langfuse при включённом флаге (мок).
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.backend.services.ai.prompts.langfuse_storage import LangfusePromptStorage

# ─── Вспомогательная фабрика ────────────────────────────────────────────────


def _make_storage(langfuse_flag: bool = False) -> LangfusePromptStorage:
    """Создаёт свежий экземпляр LangfusePromptStorage с нужным флагом.

    Синглтон сбрасывается перед каждым тестом через этот хелпер.
    Патчим модульный атрибут feature_flags.prompt_registry_langfuse напрямую.

    Args:
        langfuse_flag: Значение feature_flags.prompt_registry_langfuse.

    Returns:
        Новый экземпляр LangfusePromptStorage.
    """
    import src.backend.services.ai.prompts.langfuse_storage as mod

    # Сбрасываем синглтон
    mod._instance = None

    # Патчим атрибут на уже импортированном объекте feature_flags
    with patch.object(mod.feature_flags, "prompt_registry_langfuse", langfuse_flag):
        storage = mod.LangfusePromptStorage()

    return storage


# ─── Тест 1 ─────────────────────────────────────────────────────────────────


def test_storage_uses_inmemory_when_flag_off() -> None:
    """При prompt_registry_langfuse=False хранилище работает в in-memory режиме.

    Langfuse SDK не импортируется и _langfuse_available=False.
    """
    storage = _make_storage(langfuse_flag=False)

    assert storage._langfuse is None, (
        "Langfuse не должен инициализироваться при флаге OFF"
    )
    assert storage._langfuse_available is False, "_langfuse_available должен быть False"


# ─── Тест 2 ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_storage_get_prompt_fallback_inmemory() -> None:
    """get_prompt возвращает данные из in-memory store без Langfuse.

    Промпт предварительно сохраняется напрямую в _store,
    затем get_prompt должен его найти.
    """
    from src.backend.services.ai.prompts.langfuse_storage import PromptEntry

    storage = _make_storage(langfuse_flag=False)

    # Вручную кладём промпт в in-memory
    entry = PromptEntry(
        name="test_prompt", version="1", content="Hello {name}!", metadata={}
    )
    storage._store["test_prompt"] = {"1": entry}

    result = await storage.get_prompt("test_prompt")

    assert result["name"] == "test_prompt"
    assert result["content"] == "Hello {name}!"
    assert result["version"] == "1"
    assert isinstance(result["created_at"], datetime)


# ─── Тест 3 ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_storage_save_prompt_inmemory() -> None:
    """save_prompt сохраняет промпт в in-memory store при флаге OFF.

    После сохранения get_prompt должен вернуть сохранённые данные.
    """
    storage = _make_storage(langfuse_flag=False)

    await storage.save_prompt(
        name="greeting",
        content="Привет, {user}!",
        metadata={"owner": "k4", "version": "2"},
    )

    result = await storage.get_prompt("greeting", version="2")

    assert result["name"] == "greeting"
    assert result["content"] == "Привет, {user}!"
    assert result["version"] == "2"
    assert result["metadata"]["owner"] == "k4"


# ─── Тест 4 ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_storage_list_prompts() -> None:
    """list_prompts возвращает имена всех сохранённых промптов.

    После сохранения нескольких промптов list_prompts должен вернуть
    их имена в виде списка.
    """
    storage = _make_storage(langfuse_flag=False)

    await storage.save_prompt("alpha", "A", {"version": "1"})
    await storage.save_prompt("beta", "B", {"version": "1"})
    await storage.save_prompt("gamma", "G", {"version": "1"})

    names = await storage.list_prompts()

    assert set(names) == {"alpha", "beta", "gamma"}


# ─── Тест 5 ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_storage_lazy_imports_langfuse_when_flag_on() -> None:
    """При флаге ON выполняется lazy-import Langfuse (мокируется SDK).

    Проверяем, что при prompt_registry_langfuse=True код пытается
    импортировать langfuse.Langfuse и использует его для get_prompt.
    """
    import src.backend.services.ai.prompts.langfuse_storage as mod

    mod._instance = None

    mock_lf_prompt = MagicMock()
    mock_lf_prompt.prompt = "Mocked content"
    mock_lf_prompt.version = "lf-v1"

    mock_langfuse_instance = MagicMock()
    mock_langfuse_instance.get_prompt.return_value = mock_lf_prompt

    mock_langfuse_class = MagicMock(return_value=mock_langfuse_instance)

    with (
        patch.object(mod.feature_flags, "prompt_registry_langfuse", True),
        patch.dict(
            "sys.modules", {"langfuse": MagicMock(Langfuse=mock_langfuse_class)}
        ),
    ):
        storage = mod.LangfusePromptStorage()
        # При включённом флаге и доступном SDK — Langfuse должен быть инициализирован
        assert storage._langfuse_available is True, (
            "_langfuse_available должен быть True при флаге ON"
        )
        assert storage._langfuse is not None

        result = await storage.get_prompt("mocked_prompt")

    assert result["content"] == "Mocked content"
    assert result["version"] == "lf-v1"
    mock_langfuse_instance.get_prompt.assert_called_once_with(
        "mocked_prompt", version=None
    )
