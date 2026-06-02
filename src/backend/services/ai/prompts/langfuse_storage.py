"""LangfusePromptStorage — storage backend для prompt-registry.

Назначение:
    Адаптер для хранения и версионирования промптов через Langfuse SDK.
    При включённом feature-flag ``prompt_registry_langfuse`` все операции
    get/save/list проксируются в Langfuse. При отключённом флаге или
    недоступности Langfuse используется in-memory fallback.

Принципы:
    - default-OFF через ``feature_flags.prompt_registry_langfuse``;
    - lazy-import Langfuse SDK (не является обязательной зависимостью);
    - in-memory fallback обязателен — unit-тесты не требуют Langfuse;
    - singleton через ``get_prompt_storage()``;
    - НЕ модифицирует и НЕ заменяет существующий ``PromptRegistry``.

Использование::

    storage = get_prompt_storage()
    await storage.save_prompt("ai_qa", content="Q: {q}\\nA:", metadata={})
    entry = await storage.get_prompt("ai_qa")
    names = await storage.list_prompts()
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from src.backend.core.config.features import feature_flags

__all__ = ("LangfusePromptStorage", "PromptEntry", "get_prompt_storage")

logger = logging.getLogger("services.ai.prompts.langfuse_storage")


@dataclass(slots=True)
class PromptEntry:
    """Запись промпта в хранилище.

    Attributes:
        name: Уникальное имя промпта.
        version: Версия промпта (строка или int).
        content: Содержимое промпта (шаблон).
        metadata: Произвольные метаданные (labels, owner, tags и т.д.).
        created_at: Момент создания записи (UTC).
    """

    name: str
    version: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class LangfusePromptStorage:
    """Storage backend для промптов с поддержкой Langfuse + in-memory fallback.

    При ``feature_flags.prompt_registry_langfuse == True`` и доступном Langfuse SDK:
        - ``get_prompt`` — fetch из Langfuse с fallback на in-memory;
        - ``save_prompt`` — upsert в Langfuse + зеркало в in-memory;
        - ``list_prompts`` — список имён из in-memory кэша.

    При ``feature_flags.prompt_registry_langfuse == False`` или недоступном Langfuse:
        - все операции работают только с in-memory store.

    Пример::

        storage = get_prompt_storage()
        await storage.save_prompt("greeting", "Hello, {name}!", {"owner": "k4"})
        entry = await storage.get_prompt("greeting")
        print(entry.content)  # "Hello, {name}!"
    """

    def __init__(self) -> None:
        """Инициализирует хранилище с пустым in-memory store."""
        # in-memory store: name → version → PromptEntry
        self._store: dict[str, dict[str, PromptEntry]] = {}
        self._langfuse: Any = None
        self._langfuse_available: bool = False
        self._try_init_langfuse()

    def _try_init_langfuse(self) -> None:
        """Попытка инициализировать Langfuse SDK (lazy-import).

        Импорт Langfuse выполняется только при включённом feature-flag.
        Если SDK недоступен или инициализация провалилась — хранилище
        продолжает работу в режиме in-memory fallback.
        """
        try:
            if not feature_flags.prompt_registry_langfuse:
                logger.debug(
                    "feature_flags.prompt_registry_langfuse=False, "
                    "LangfusePromptStorage работает в режиме in-memory fallback"
                )
                return

            # Lazy-import: не загружаем SDK при отключённом флаге
            from langfuse import Langfuse  

            self._langfuse = Langfuse()
            self._langfuse_available = True
            logger.info("LangfusePromptStorage: Langfuse SDK инициализирован")
        except ImportError:
            logger.debug("Langfuse SDK не установлен — используется in-memory fallback")
        except Exception as exc:
            logger.warning(
                "Langfuse инициализация провалилась: %s — fallback на in-memory", exc
            )

    async def get_prompt(self, name: str, version: str | None = None) -> dict[str, Any]:
        """Получает промпт по имени и опциональной версии.

        Порядок поиска:
            1. Langfuse (если доступен и флаг включён);
            2. in-memory fallback.

        Args:
            name: Имя промпта.
            version: Конкретная версия (None → последняя).

        Returns:
            Словарь с ключами: name, version, content, metadata, created_at.

        Raises:
            KeyError: Если промпт не найден ни в Langfuse, ни в in-memory.
        """
        if self._langfuse_available and self._langfuse is not None:
            try:
                lf_prompt = self._langfuse.get_prompt(name, version=version)
                content = (
                    lf_prompt.prompt if hasattr(lf_prompt, "prompt") else str(lf_prompt)
                )
                resolved_version = str(
                    getattr(lf_prompt, "version", version or "latest")
                )
                # Зеркалируем в in-memory для list_prompts
                entry = PromptEntry(
                    name=name,
                    version=resolved_version,
                    content=content,
                    metadata={"source": "langfuse"},
                )
                self._store.setdefault(name, {})[resolved_version] = entry
                return {
                    "name": entry.name,
                    "version": entry.version,
                    "content": entry.content,
                    "metadata": entry.metadata,
                    "created_at": entry.created_at,
                }
            except Exception as exc:
                logger.warning(
                    "Langfuse get_prompt('%s') провалился: %s — fallback на in-memory",
                    name,
                    exc,
                )

        return self._get_from_memory(name, version)

    def _get_from_memory(self, name: str, version: str | None) -> dict[str, Any]:
        """Получает промпт из in-memory store.

        Args:
            name: Имя промпта.
            version: Конкретная версия (None → последняя по алфавиту/добавлению).

        Returns:
            Словарь представления PromptEntry.

        Raises:
            KeyError: Если промпт отсутствует в store.
        """
        versions = self._store.get(name)
        if not versions:
            raise KeyError(f"Промпт '{name}' не найден в in-memory store")

        if version is not None:
            if version not in versions:
                raise KeyError(f"Промпт '{name}' версия '{version}' не найдена")
            entry = versions[version]
        else:
            # Последняя добавленная версия
            entry = next(reversed(versions.values()))

        return {
            "name": entry.name,
            "version": entry.version,
            "content": entry.content,
            "metadata": entry.metadata,
            "created_at": entry.created_at,
        }

    async def save_prompt(
        self, name: str, content: str, metadata: dict[str, Any]
    ) -> None:
        """Upsert промпта в хранилище.

        При доступном Langfuse — создаёт/обновляет промпт через SDK.
        Всегда зеркалирует в in-memory для offline-доступа и list_prompts.

        Args:
            name: Имя промпта.
            content: Содержимое шаблона.
            metadata: Метаданные (owner, tags, labels и т.д.).
        """
        version = str(metadata.get("version", "1"))
        entry = PromptEntry(
            name=name, version=version, content=content, metadata=metadata
        )

        if self._langfuse_available and self._langfuse is not None:
            try:
                self._langfuse.create_prompt(
                    name=name, prompt=content, labels=metadata.get("labels", [])
                )
                logger.debug("Langfuse: промпт '%s' сохранён", name)
            except Exception as exc:
                logger.warning(
                    "Langfuse save_prompt('%s') провалился: %s — сохранено только in-memory",
                    name,
                    exc,
                )

        self._store.setdefault(name, {})[version] = entry
        logger.debug("in-memory: промпт '%s' v%s сохранён", name, version)

    async def list_prompts(self) -> list[str]:
        """Возвращает список имён всех известных промптов.

        Возвращает имена из in-memory store (включает промпты, загруженные
        из Langfuse через get_prompt и сохранённые через save_prompt).

        Returns:
            Список уникальных имён промптов.
        """
        return list(self._store.keys())


_instance: LangfusePromptStorage | None = None


def get_prompt_storage() -> LangfusePromptStorage:
    """Возвращает singleton LangfusePromptStorage.

    Returns:
        Глобальный экземпляр LangfusePromptStorage.
    """
    global _instance
    if _instance is None:
        _instance = LangfusePromptStorage()
    return _instance
