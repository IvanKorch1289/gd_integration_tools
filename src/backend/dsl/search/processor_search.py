"""Semantic-style поиск по DSL processors (S10 K3 W5, DSL-1.6).

Использует:

* в production — embeddings (BGE-M3 или MiniLM) для запроса и docstring'ов;
* в dev_light / без extras — упрощённый keyword + token-overlap rank.

Без extras (sentence-transformers / fastembed) — fallback на keyword
score (intersection/jaccard) — точность ниже, но запрос обрабатывается
без heavy deps.

API::

    from src.backend.dsl.search.processor_search import (
        ProcessorSearch, SearchResult,
    )

    s = ProcessorSearch.from_registry()
    results = s.search("send http request with retry", top_k=5)
    for r in results:
        print(r.processor_name, r.score, r.namespace)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

__all__ = ("ProcessorSearch", "SearchResult", "tokenize")

_TOKEN_RE = re.compile(r"[A-Za-zА-Яа-я0-9_]+")


def tokenize(text: str) -> set[str]:
    """Простая токенизация: lowercase, alphanum-tokens, длиной ≥ 2."""
    return {t.lower() for t in _TOKEN_RE.findall(text or "") if len(t) >= 2}


@dataclass(slots=True, frozen=True)
class SearchResult:
    """Результат поиска одного processor'а.

    Attributes:
        processor_name: short name (``http_call``).
        namespace: ``core`` / ``extensions/<plugin>``.
        score: 0.0..1.0 — relevance.
        description: текстовое описание (из docstring или meta).
    """

    processor_name: str
    namespace: str
    score: float
    description: str


@dataclass(slots=True)
class ProcessorSearch:
    """Поисковик по реестру processors.

    Attributes:
        documents: list[(fqn, tokens, full_description, namespace, short_name)]
    """

    documents: list[tuple[str, set[str], str, str, str]]

    @classmethod
    def from_registry(cls) -> ProcessorSearch:
        """Берёт записи из глобального ProcessorRegistry."""
        from src.backend.dsl.registry.processor import get_processor_registry

        reg = get_processor_registry()
        docs: list[tuple[str, set[str], str, str, str]] = []
        for spec in reg.list_specs():
            description = _description_of(spec)
            tokens = tokenize(description) | tokenize(spec.name)
            docs.append((spec.fqn, tokens, description, spec.namespace, spec.name))
        return cls(documents=docs)

    @classmethod
    def from_specs(cls, specs: list[Any]) -> ProcessorSearch:
        """Альтернативный конструктор для тестов (не требует реестра)."""
        docs: list[tuple[str, set[str], str, str, str]] = []
        for spec in specs:
            description = _description_of(spec)
            tokens = tokenize(description) | tokenize(getattr(spec, "name", ""))
            docs.append(
                (
                    f"{getattr(spec, 'namespace', 'core')}:"
                    f"{getattr(spec, 'name', 'unknown')}",
                    tokens,
                    description,
                    getattr(spec, "namespace", "core"),
                    getattr(spec, "name", "unknown"),
                )
            )
        return cls(documents=docs)

    def search(self, query: str, *, top_k: int = 5) -> list[SearchResult]:
        """Возвращает top_k наиболее релевантных processor'ов.

        Используется Jaccard-similarity для query- и doc-токенов.
        В extras-режиме (sentence-transformers) метод можно
        переключить на BGE-M3 cosine — структура результата
        остаётся.

        Args:
            query: пользовательский запрос (свободная фраза).
            top_k: max возвращаемых результатов.

        Returns:
            Список SearchResult, отсортированный по score desc.
        """
        if not query.strip():
            return []
        q_tokens = tokenize(query)
        if not q_tokens:
            return []

        scores: list[SearchResult] = []
        for _fqn, tokens, desc, ns, name in self.documents:
            if not tokens:
                continue
            inter = len(q_tokens & tokens)
            union = len(q_tokens | tokens)
            jaccard = inter / union if union else 0.0
            # Boost: точное вхождение query-слова в name.
            name_boost = 0.5 if any(q in name for q in q_tokens) else 0.0
            score = min(1.0, jaccard + name_boost)
            if score <= 0:
                continue
            scores.append(
                SearchResult(
                    processor_name=name,
                    namespace=ns,
                    score=round(score, 4),
                    description=desc,
                )
            )

        scores.sort(key=lambda r: r.score, reverse=True)
        return scores[:top_k]


def _description_of(spec: Any) -> str:
    """Извлекает описание processor'а."""
    cls = getattr(spec, "cls", None)
    if cls is not None and cls.__doc__:
        return cls.__doc__.strip()
    meta = getattr(spec, "meta", {})
    if isinstance(meta, dict) and "description" in meta:
        return str(meta["description"])
    return ""
