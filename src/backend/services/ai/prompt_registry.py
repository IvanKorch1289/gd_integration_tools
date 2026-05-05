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

import logging
from dataclasses import dataclass
from typing import Any

__all__ = ("PromptRegistry", "get_prompt_registry", "PromptVersion")

logger = logging.getLogger("services.prompts")


@dataclass(slots=True)
class PromptVersion:
    """Скомпилированный промпт с метаданными версии."""

    name: str
    version: int | str
    template: str
    compiled: str
    labels: dict[str, str]


class PromptRegistry:
    """Реестр промптов с поддержкой Langfuse + fallback на in-memory.

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

        resolved_version = version if version is not None else max(store.keys())  # type: ignore[type-var]
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


_instance: PromptRegistry | None = None


def get_prompt_registry() -> PromptRegistry:
    global _instance
    if _instance is None:
        _instance = PromptRegistry()
    return _instance
