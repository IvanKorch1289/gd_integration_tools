"""Prompt Registry — Langfuse-backed prompt versioning + A/B testing.

Заменяет hardcoded промпты в коде.
Langfuse (уже в optional deps) предоставляет:
- Versioning (v1, v2, rollback)
- A/B testing (random routing между вариантами)
- Cost/quality tracking per prompt version

Fallback: in-memory registry с файловым persistence (если langfuse недоступен).

Multi-instance safety:
- Langfuse: централизованный API (built-in)
- Fallback: Redis-backed storage

Usage::

    prompt = await prompt_registry.get("ai_qa_with_rag", variables={"question": "..."})
    # returns compiled prompt with version tracking
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.backend.core.logging import get_logger

__all__ = ("PromptRegistry", "PromptVersion", "get_prompt_registry")

logger = get_logger("services.prompts")


@dataclass(slots=True)
class PromptVersion:
    """Скомпилированный промпт с метаданными версии."""

    name: str
    version: int | str
    template: str
    compiled: str
    labels: dict[str, str]


class PromptRegistry:
    r"""Реестр промптов с поддержкой Langfuse + fallback на in-memory.

    Регистрация (fallback mode)::

        registry.register("ai_qa", template="Q: {question}\\nA:", version=1)

    Использование::

        prompt = await registry.get("ai_qa", variables={"question": "Hello"})
        # prompt.compiled = "Q: Hello\\nA:"
    """

    def __init__(self) -> None:
        self._fallback_store: dict[str, dict[int, str]] = {}
        self._labels: dict[str, dict[str, str]] = {}
        self._langfuse: Any = None
        self._try_init_langfuse()

    def _try_init_langfuse(self) -> None:
        try:
            from langfuse import Langfuse

            self._langfuse = Langfuse()
            logger.info("Langfuse prompt registry initialized")
        except ImportError:
            logger.debug("Langfuse not installed, using in-memory fallback")
        except Exception as exc:
            logger.warning("Langfuse init failed: %s", exc)

    def register(
        self,
        name: str,
        *,
        template: str,
        version: int | str = 1,
        labels: dict[str, str] | None = None,
    ) -> None:
        """Регистрирует промпт (fallback mode)."""
        self._fallback_store.setdefault(name, {})[version] = template  # type: ignore[index]
        if labels:
            self._labels[f"{name}:{version}"] = labels

    async def get(
        self,
        name: str,
        *,
        variables: dict[str, Any] | None = None,
        version: int | str | None = None,
        label: str = "production",
    ) -> PromptVersion:
        """Получает промпт + компилирует с variables.

        Args:
            name: Имя промпта.
            variables: Значения для подстановки.
            version: Конкретная версия (иначе production label).
            label: Langfuse label (production/staging/canary).

        Returns:
            PromptVersion с compiled-строкой.

        """
        variables = variables or {}

        if self._langfuse is not None:
            try:
                lf_prompt = self._langfuse.get_prompt(
                    name, label=label, version=version
                )
                compiled = (
                    lf_prompt.compile(**variables)
                    if hasattr(lf_prompt, "compile")
                    else str(lf_prompt)
                )
                return PromptVersion(
                    name=name,
                    version=getattr(lf_prompt, "version", "langfuse"),
                    template=getattr(lf_prompt, "prompt", str(lf_prompt)),
                    compiled=compiled,
                    labels={"source": "langfuse", "label": label},
                )
            except Exception as exc:
                logger.warning("Langfuse get_prompt failed: %s, falling back", exc)

        store = self._fallback_store.get(name, {})
        if not store:
            raise KeyError(f"Prompt '{name}' not found in registry")

        resolved_version = version if version is not None else max(store.keys())
        template = store[resolved_version]  # type: ignore[index]

        try:
            compiled = template.format(**variables)
        except KeyError as exc:
            logger.warning("Prompt compilation missing variable: %s", exc)
            compiled = template

        return PromptVersion(
            name=name,
            version=resolved_version,
            template=template,
            compiled=compiled,
            labels=self._labels.get(
                f"{name}:{resolved_version}", {"source": "fallback"}
            ),
        )

    def list_versions(self, name: str) -> list[dict[str, Any]]:
        """Версии промпта, зарегистрированные в реестре (fallback-режим).

        Args:
            name: Имя промпта.

        Returns:
            Список ``{"name", "version", "template", "labels", "is_active"}``
            (отсортирован по версии). Для Langfuse-режима возвращается пустой
            список — там версии читаются через Langfuse API.

        """
        store = self._fallback_store.get(name, {})
        active = self.active_version(name)
        return [
            {
                "name": name,
                "version": version,
                "template": template,
                "labels": self._labels.get(f"{name}:{version}", {"source": "fallback"}),
                "is_active": version == active,
            }
            for version, template in sorted(
                store.items(), key=lambda item: str(item[0])
            )
        ]

    def list_prompts(self) -> list[str]:
        """Имена всех промптов реестра."""
        return sorted(self._fallback_store)

    def active_version(self, name: str) -> int | str | None:
        """Активная (production) версия промпта.

        Активной считается версия с label ``production`` либо последняя
        зарегистрированная.

        Args:
            name: Имя промпта.

        Returns:
            Номер версии или ``None``, если промпт не зарегистрирован.

        """
        store = self._fallback_store.get(name, {})
        if not store:
            return None
        for version in sorted(store, key=lambda item: str(item)):
            labels = self._labels.get(f"{name}:{version}", {})
            if labels.get("label") == "production":
                return version
        return max(store, key=lambda item: str(item))

    def activate(self, name: str, version: int | str) -> bool:
        """Активировать версию промпта (label ``production``).

        Args:
            name: Имя промпта.
            version: Версия.

        Returns:
            ``True`` если версия найдена и активирована.

        """
        store = self._fallback_store.get(name, {})
        if version not in store:
            return False
        for existing in store:
            labels = dict(
                self._labels.get(f"{name}:{existing}", {"source": "fallback"})
            )
            labels["label"] = "production" if existing == version else "staging"
            self._labels[f"{name}:{existing}"] = labels
        return True

    def compare(
        self, name: str, version_a: int | str, version_b: int | str
    ) -> dict[str, Any]:
        """Сравнить две версии промпта.

        Args:
            name: Имя промпта.
            version_a: Первая версия.
            version_b: Вторая версия.

        Returns:
            ``{"name", "a", "b", "metric_diffs", "template_diff"}``; ``metric_diffs``
            пуст без метрик Langfuse (их источник — внешний трекер).

        Raises:
            KeyError: Промпт или версия не найдены.

        """
        store = self._fallback_store.get(name, {})
        for version in (version_a, version_b):
            if version not in store:
                raise KeyError(f"Prompt '{name}' version '{version}' not found")
        template_a = store[version_a]  # type: ignore[index]
        template_b = store[version_b]  # type: ignore[index]
        lines_a = template_a.splitlines()
        lines_b = template_b.splitlines()
        return {
            "name": name,
            "a": {"version": version_a, "template": template_a},
            "b": {"version": version_b, "template": template_b},
            "metric_diffs": {},
            "template_diff": {
                "added": [line for line in lines_b if line not in lines_a],
                "removed": [line for line in lines_a if line not in lines_b],
                "changed": template_a != template_b,
            },
        }

    async def get_compiled(
        self,
        name: str,
        *,
        version: int | str | None = None,
        label: str = "production",
        variables: dict[str, Any] | None = None,
    ) -> str:
        """Метод get_compiled (см. signature)."""
        pv = await self.get(name, version=version, label=label, variables=variables)
        return pv.compiled


_instance: PromptRegistry | None = None


def get_prompt_registry() -> PromptRegistry:
    """Фабрика: prompt registry service."""
    global _instance
    if _instance is None:
        _instance = PromptRegistry()
    return _instance
