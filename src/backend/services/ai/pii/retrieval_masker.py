"""RAG retrieval PII masker (Sprint 11 K1 W1).

Тонкая обёртка над :class:`PIIMasker` для применения маскировки к
``augment_result["citations"]`` или ``augment_result["raw_results"]``,
полученным из vector store. Все contents маскируются по существующим
8 паттернам (CC/SSN/email/phone/IP/passport/IBAN/SNILS).

Lazy-инициализация: ``default_masker`` — модуль-уровневый singleton
из ``core.security.pii_masker``, без аллокации новой структуры на
каждый чанк.

Feature-flag: контроль активации задаётся снаружи (RagPIIRedactionProcessor)
через ``feature_flags.rag_pii_retrieval_mask``.
"""

from __future__ import annotations

from typing import Any

from src.backend.core.security.pii_masker import PIIMasker, default_masker

__all__ = ("mask_retrieval_documents", "mask_augment_result")


def mask_retrieval_documents(
    documents: list[dict[str, Any]], *, masker: PIIMasker | None = None
) -> list[dict[str, Any]]:
    """Применить PII-маскер к каждому ``document.content`` retrieval result.

    Args:
        documents: Список dict'ов с обязательным полем ``content`` (str)
            и опциональным ``metadata`` (dict).
        masker: Опционально, кастомный :class:`PIIMasker`. По умолчанию —
            модуль-уровневый ``default_masker``.

    Returns:
        Новый список dict'ов с замаскированным ``content``.
        Остальные поля копируются как есть.
    """
    instance = masker if masker is not None else default_masker()
    out: list[dict[str, Any]] = []
    for doc in documents:
        cloned = dict(doc)
        content = cloned.get("content")
        if isinstance(content, str) and content:
            cloned["content"] = instance.mask_text(content)
        out.append(cloned)
    return out


def mask_augment_result(
    payload: dict[str, Any], *, masker: PIIMasker | None = None
) -> dict[str, Any]:
    """Применить маскер к augment-результату in-place-копией.

    Маскирует:
    * ``payload["documents"][*].content``
    * ``payload["citations"][*].content``
    * ``payload["prompt"]`` (final assembled context)

    Возвращает новый dict (не мутирует исходник).
    """
    instance = masker if masker is not None else default_masker()
    cloned = dict(payload)
    documents = cloned.get("documents")
    if isinstance(documents, list):
        cloned["documents"] = mask_retrieval_documents(documents, masker=instance)
    citations = cloned.get("citations")
    if isinstance(citations, list):
        new_citations: list[Any] = []
        for cit in citations:
            if isinstance(cit, dict):
                cit_copy = dict(cit)
                content = cit_copy.get("content")
                if isinstance(content, str) and content:
                    cit_copy["content"] = instance.mask_text(content)
                new_citations.append(cit_copy)
            else:
                new_citations.append(cit)
        cloned["citations"] = new_citations
    prompt = cloned.get("prompt")
    if isinstance(prompt, str) and prompt:
        cloned["prompt"] = instance.mask_text(prompt)
    return cloned
