"""RAG retrieval PII masker (Sprint 11 K1 W1; S24 W1 ADR-NEW-16 расширение).

Тонкая обёртка над :class:`PIIMasker` для применения маскировки к
``augment_result["citations"]`` или ``augment_result["raw_results"]``,
полученным из vector store.

Feature-flag путь:
    * ``PRESIDIO_PII_ENABLED=False`` (default) — legacy regex (8 паттернов
      из ``core.security.pii_masker``): CC/SSN/email/phone/IP/passport/IBAN/SNILS;
    * ``PRESIDIO_PII_ENABLED=True`` (S24 W1) — Presidio + ru NER + 4 custom
      recognizers через :class:`PresidioSanitizerAdapter`. Покрывает русские
      ФИО, организации, локации, ИНН/СНИЛС/паспорт/кредитное дело с
      checksum-валидацией.

Feature-flag активации DSL-процессора:
    Отдельный флаг ``rag_pii_retrieval_mask`` контролирует, вызывается ли
    маскер в `RagPIIRedactionProcessor` (рекомендуется default-ON в
    production-config после S24 W1 closure).
"""

from __future__ import annotations

from typing import Any

from src.backend.core.security.pii_masker import PIIMasker, default_masker

__all__ = ("mask_augment_result", "mask_retrieval_documents")


def _mask_string(text: str, masker: PIIMasker | None) -> str:
    """Маскирует один фрагмент текста через legacy regex или Presidio.

    Выбор реализации определяется feature-flag ``PRESIDIO_PII_ENABLED``:
    при True используется ``PresidioSanitizerAdapter`` через DI-provider
    (с graceful fallback на legacy при отсутствии presidio пакета); при
    False используется переданный или модуль-уровневый ``default_masker``.
    """
    from src.backend.core.config.features import feature_flags

    if feature_flags.presidio_pii_enabled:
        from src.backend.core.di.providers import get_ai_sanitizer_provider

        sanitizer = get_ai_sanitizer_provider()
        return sanitizer.sanitize_text(text).sanitized_text
    instance = masker if masker is not None else default_masker()
    return instance.mask_text(text)


def mask_retrieval_documents(
    documents: list[dict[str, Any]], *, masker: PIIMasker | None = None
) -> list[dict[str, Any]]:
    """Применить PII-маскер к каждому ``document.content`` retrieval result.

    Args:
        documents: Список dict'ов с обязательным полем ``content`` (str)
            и опциональным ``metadata`` (dict).
        masker: Опционально, кастомный :class:`PIIMasker`. По умолчанию —
            модуль-уровневый ``default_masker``. Игнорируется при
            ``PRESIDIO_PII_ENABLED=True`` (используется DI-provider).

    Returns:
        Новый список dict'ов с замаскированным ``content``.
        Остальные поля копируются как есть.
    """
    out: list[dict[str, Any]] = []
    for doc in documents:
        cloned = dict(doc)
        content = cloned.get("content")
        if isinstance(content, str) and content:
            cloned["content"] = _mask_string(content, masker)
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
    cloned = dict(payload)
    documents = cloned.get("documents")
    if isinstance(documents, list):
        cloned["documents"] = mask_retrieval_documents(documents, masker=masker)
    citations = cloned.get("citations")
    if isinstance(citations, list):
        new_citations: list[Any] = []
        for cit in citations:
            if isinstance(cit, dict):
                cit_copy = dict(cit)
                content = cit_copy.get("content")
                if isinstance(content, str) and content:
                    cit_copy["content"] = _mask_string(content, masker)
                new_citations.append(cit_copy)
            else:
                new_citations.append(cit)
        cloned["citations"] = new_citations
    prompt = cloned.get("prompt")
    if isinstance(prompt, str) and prompt:
        cloned["prompt"] = _mask_string(prompt, masker)
    return cloned
