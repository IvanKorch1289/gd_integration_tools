"""E2E-тест text-RAG pipeline (cycle-7/D-AUDIT-705).

Покрывает полный pipeline ``ingest → chunking → embedding → retrieval →
rerank → LLM stub`` для текстового RAG, используя реальный
``RAGService`` с in-memory :class:`BaseVectorStore` (FAISS/Qdrant
не поднимаются) и :class:`StubEmbedder` (token-overlap, без
sentence-transformers).

* **Embedder** — стаб возвращает детерминированный 16-dim vector
  по token-overlap (аналогично multimodal тесту).
* **LLM** (``litellm.completion``) — стаб возвращает фиксированный
  ответ, явно ссылающийся на retrieved chunks.
* **Rerank** — стаб отбрасывает фрод-mentions до подачи в LLM
  (compliance policy).

Stub'ы подменяют **только внешние модели** (network/ML boundary);
компоненты ядра (``RAGService``, ``RecursiveChunker``, in-memory
``BaseVectorStore``) используются реальные — это и есть объект
тестирования.

Запуск:
    pytest tests/e2e/test_text_rag_e2e.py -v -m e2e
    # либо (см. docs/rag/MULTIMODAL_TESTING.md):
    make test-e2e

Тест **не** включён в блокирующий ``make test`` (markers:
``e2e``, ``integration``, ``asyncio`` — отфильтровываются дефолтным
``-m 'not e2e'``).
"""

# ruff: noqa: S101

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from src.backend.core.interfaces.vector_store import BaseVectorStore
from src.backend.services.ai.rag_service import RAGService

# ─────────────────────────── deterministic stub embedder ───────────────────────────

# Фиксированный словарь для token-overlap embedding (16-dim).
# Размерность выбрана минимальной, чтобы cosine-similarity была
# тривиальной (один общий токен → 1.0).
_TOKEN_VOCAB: tuple[str, ...] = (
    "банк", "кредит", "платёж", "клиент", "счёт", "карта", "сбер",
    "овердрафт", "ипотека", "депозит", "валюта", "ставка", "риск",
    "скоринг", "фрод", "комплаенс",
)
_TOKEN_INDEX: dict[str, int] = {tok: i for i, tok in enumerate(_TOKEN_VOCAB)}
_DROP_TOKEN = "фрод"


def _token_overlap_vec(text: str) -> list[float]:
    """Возвращает 16-dim unit-vector: 1.0 на позициях присутствующих токенов."""
    lower = text.lower()
    vec = [0.0] * len(_TOKEN_VOCAB)
    for tok, idx in _TOKEN_INDEX.items():
        if tok in lower:
            vec[idx] = 1.0
    norm = sum(v * v for v in vec) ** 0.5
    if norm > 0.0:
        vec = [v / norm for v in vec]
    return vec


class StubEmbedder:
    """Deterministic embedder с token-overlap кодированием.

    Заменяет sentence-transformers/BGE для теста. Гарантирует
    cosine-similarity("кредит", "условия кредита") == 1.0 — оба
    попадают на индекс 1 словаря.
    """

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Encode list of texts через token overlap."""
        return [_token_overlap_vec(t) for t in texts]


# ─────────────────────────── in-memory vector store ───────────────────────────


class InMemoryVectorStore(BaseVectorStore):
    """Простейший BaseVectorStore для E2E — cosine similarity + upsert/query.

    Не подменяет реальный backend (Qdrant/FAISS), но реализует
    минимальный контракт для pipeline: upsert/query/delete/count +
    delete_where/count_where (нужны для collection_mixin).
    """

    def __init__(self) -> None:
        """Stores: list[dict[{id, embedding, document, metadata}]]."""
        self._items: list[dict[str, Any]] = []

    async def upsert(
        self,
        embeddings: list[list[float]],
        documents: list[str],
        ids: list[str],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> None:
        """Upsert vectors + documents + metadata (idempotent по id)."""
        for i, (chunk_id, embedding, document) in enumerate(
            zip(ids, embeddings, documents)
        ):
            metadata = (metadatas or [{}] * len(documents))[i] or {}
            self._items = [it for it in self._items if it["id"] != chunk_id]
            self._items.append(
                {
                    "id": chunk_id,
                    "embedding": embedding,
                    "document": document,
                    "metadata": metadata,
                }
            )

    async def query(
        self,
        embedding: list[float],
        top_k: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Cosine similarity search + optional ``where`` filter."""
        scored: list[tuple[float, dict[str, Any]]] = []
        for item in self._items:
            if where:
                meta = item.get("metadata") or {}
                if any(meta.get(k) != v for k, v in where.items()):
                    continue
            scored.append((_cosine(embedding, item["embedding"]), item))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [
            {
                "id": item["id"],
                "document": item["document"],
                "metadata": item["metadata"],
                "score": float(score),
                "distance": float(1.0 - score),
            }
            for score, item in scored[:top_k]
        ]

    async def delete(self, ids: list[str]) -> None:
        """Удаляет по chunk-id."""
        id_set = set(ids)
        self._items = [it for it in self._items if it["id"] not in id_set]

    async def count(self) -> int:
        """Общее количество vectors."""
        return len(self._items)

    async def delete_where(self, where: dict[str, Any]) -> int:
        """Удаляет по metadata-фильтру; возвращает количество удалённых."""
        before = len(self._items)
        self._items = [
            it
            for it in self._items
            if any((it.get("metadata") or {}).get(k) != v for k, v in where.items())
        ]
        return before - len(self._items)

    async def count_where(self, where: dict[str, Any]) -> int:
        """Количество vectors, проходящих metadata-фильтр."""
        return sum(
            1
            for it in self._items
            if all((it.get("metadata") or {}).get(k) == v for k, v in where.items())
        )


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity двух equal-length vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


# ─────────────────────────── LiteLLM stub ───────────────────────────


class StubLiteLLM:
    """Stub LiteLLM — детерминированный ответ, ссылающийся на context.

    Фиксирует последний prompt для последующих assert'ов в тесте.
    """

    last_messages: list[dict[str, str]] | None = None

    def completion(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Имитирует ``litellm.completion(messages=...) -> dict``."""
        messages = kwargs.get("messages")
        if messages is None and args:
            messages = args[0]
        StubLiteLLM.last_messages = list(messages or [])
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": (
                            "Согласно retrieved контексту, кредитная ставка "
                            "определяется скорингом клиента."
                        ),
                    }
                }
            ]
        }


# ─────────────────────────── rerank stage ───────────────────────────


def stub_rerank(chunks: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
    """Rerank stub: drop chunks, содержащие ``_DROP_TOKEN`` (фрод).

    Демонстрирует stage 'rerank' в pipeline: после retrieval мы
    отбрасываем фрод-mentions до подачи в LLM (compliance policy).
    Возвращает до ``top_k`` chunks.
    """
    filtered = [
        c
        for c in chunks
        if _DROP_TOKEN not in (c.get("document") or "").lower()
    ]
    return filtered[:top_k]


# ─────────────────────────── fixtures ───────────────────────────


@pytest.fixture
def vector_store() -> InMemoryVectorStore:
    """Свежий InMemoryVectorStore."""
    return InMemoryVectorStore()


@pytest.fixture
def rag_service(vector_store: InMemoryVectorStore) -> RAGService:
    """RAGService со stub-embedder + in-memory store."""
    return RAGService(store=vector_store, embedder=StubEmbedder(), cache=None)


@pytest.fixture
def stub_litellm(monkeypatch: pytest.MonkeyPatch) -> StubLiteLLM:
    """Подменяет ``litellm.completion`` через sys.modules на stub."""
    instance = StubLiteLLM()
    fake_litellm = types.ModuleType("litellm")
    fake_litellm.completion = instance.completion  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "litellm", fake_litellm)
    return instance


# ─────────────────────────── tests ───────────────────────────


# Банковский demo-документ: 5 длинных параграфов, разделённых ``\n\n``.
# Каждый параграф содержит 1-2 уникальных токена для embedding.
# Размер ~1500 символов → RecursiveChunker режет на ≥3 chunks
# (default chunk_size=512, overlap=50).
_BANK_DOCUMENT = (
    "Кредитная политика банка определяет условия выдачи кредитов клиентам. "
    "Клиент предоставляет документы, банк проводит скоринг и оценку риска "
    "по внутренним моделям скоринга. Решение о выдаче кредита принимается "
    "на основе комплексного анализа заёмщика и его кредитной истории.\n\n"
    "Скоринг клиента основан на оценке риска, кредитной истории и платёже "
    "способности. При высоком скоринге клиент получает сниженную ставку "
    "по кредиту и увеличенный лимит по карте. Скоринг пересчитывается "
    "ежемесячно с учётом новых данных из бюро кредитных историй.\n\n"
    "Ипотека выдаётся под залог недвижимости с фиксированной ставкой на "
    "длительный срок. Клиент может выбрать аннуитетный или дифференцированный "
    "платёж по графику. Ставка по ипотеке зависит от скоринга и размера "
    "первоначального взноса за квартиру или дом.\n\n"
    "Депозит позволяет клиенту разместить средства на счёте под процент "
    "с ежемесячной капитализацией. Валюта вклада может быть рубль или "
    "другая иностранная валюта по выбору клиента. Депозит застрахован "
    "государственной системой страхования вкладов.\n\n"
    "Комплаенс контролирует операции для предотвращения фрода, отмывания "
    "средств и финансирования терроризма. Карта клиента блокируется при "
    "подозрении на компрометацию. Банк соблюдает все требования "
    "регулятора по противодействию отмыванию доходов."
)


@pytest.mark.e2e
@pytest.mark.asyncio
@pytest.mark.integration
async def test_text_ingest_chunk_embed_pipeline(
    vector_store: InMemoryVectorStore,
    rag_service: RAGService,
) -> None:
    """text ingest → chunking (RecursiveChunker) → embedding (stub) → store.

    Pipeline:
        1. ``RAGService.ingest(_BANK_DOCUMENT, namespace='docs')`` → ``doc_id``.
        2. ``chunk_text`` разрезает на предложения/параграфы (≥3 chunks).
        3. ``StubEmbedder.embed(chunks)`` возвращает 16-dim vectors.
        4. ``InMemoryVectorStore.upsert`` сохраняет chunks + metadata.

    Asserts:
        * doc_id — 16 hex chars (sha256 prefix);
        * ≥3 chunks в store после ingest;
        * metadata содержит ``namespace``, ``doc_id``, ``chunk_idx``;
        * vector search «кредит» находит chunk с этим токеном.
    """
    doc_id = await rag_service.ingest(
        _BANK_DOCUMENT, metadata={"source": "credit_policy.pdf"}, namespace="docs"
    )
    assert len(doc_id) == 16, "doc_id должен быть sha256[:16]"

    all_chunks = await vector_store.query(
        embedding=[0.0] * len(_TOKEN_VOCAB), top_k=100
    )
    assert len(all_chunks) >= 3, (
        f"RecursiveChunker должен разрезать на ≥3 chunks, got {len(all_chunks)}"
    )

    for chunk in all_chunks:
        meta = chunk.get("metadata") or {}
        assert meta.get("namespace") == "docs"
        assert meta.get("doc_id") == doc_id
        assert isinstance(meta.get("chunk_idx"), int)
        assert isinstance(chunk.get("document"), str)

    cred_emb = _token_overlap_vec("кредит")
    credit_hits = await vector_store.query(embedding=cred_emb, top_k=10)
    assert len(credit_hits) >= 1
    assert any(
        "кредит" in (h.get("document") or "").lower() for h in credit_hits
    ), "vector search должен находить chunk с 'кредит'"


@pytest.mark.e2e
@pytest.mark.asyncio
@pytest.mark.integration
async def test_text_retrieval_rerank_llm_pipeline(
    rag_service: RAGService,
    stub_litellm: StubLiteLLM,
) -> None:
    """ingest → retrieval → rerank (drop fraud) → LLM stub.

    Pipeline:
        1. ingest _BANK_DOCUMENT (5 параграфов: 'кредит', 'скоринг',
           'ипотека', 'депозит', 'фрод');
        2. ``search("кредит ставка", top_k=5, namespace='docs')``;
        3. ``stub_rerank`` отбрасывает chunk про фрод;
        4. ``stub_litellm.completion`` генерирует ответ, ссылающийся
           на retrieved chunks.

    Asserts:
        * rerank отбросил chunk, содержащий ``_DROP_TOKEN``;
        * LLM ответ содержит слово «кредит» / «скоринг»;
        * LLM.last_messages содержит retrieved context.
    """
    await rag_service.ingest(_BANK_DOCUMENT, namespace="docs")

    raw_chunks = await rag_service.search(
        "кредит ставка", top_k=5, namespace="docs"
    )
    assert len(raw_chunks) >= 1, "search должен вернуть ≥1 chunk"

    reranked = stub_rerank(raw_chunks, top_k=3)
    assert len(reranked) >= 1
    assert all(
        _DROP_TOKEN not in (c.get("document") or "").lower() for c in reranked
    ), "rerank должен отбросить chunk про фрод"

    context = "\n\n".join(c.get("document", "") for c in reranked)
    response = stub_litellm.completion(
        messages=[
            {"role": "user", "content": f"Вопрос: кредит ставка\nКонтекст:\n{context}"}
        ]
    )
    answer = response["choices"][0]["message"]["content"]

    assert "кредит" in answer.lower() or "скоринг" in answer.lower(), (
        f"LLM answer должен reference retrieved context, got: {answer!r}"
    )
    assert StubLiteLLM.last_messages is not None
    context_blob = " ".join(
        m.get("content", "") for m in StubLiteLLM.last_messages
    )
    assert "кредит" in context_blob.lower(), (
        "LLM prompt должен содержать retrieved context"
    )
    assert _DROP_TOKEN not in context_blob.lower(), (
        "rerank должен вырезать фрод-mention из LLM-промпта"
    )


@pytest.mark.e2e
@pytest.mark.asyncio
@pytest.mark.integration
async def test_text_augment_prompt_includes_citations(
    rag_service: RAGService,
) -> None:
    """``augment_prompt_with_citations`` возвращает prompt + структурированные citations.

    Pipeline:
        1. ingest document с metadata.source='policy_v3.pdf';
        2. ``augment_prompt_with_citations(query, namespace='docs')``
           возвращает :class:`AugmentResult` с citations.

    Asserts:
        * prompt содержит «Контекст из базы знаний» + retrieved chunk;
        * ``citations`` non-empty;
        * каждый citation имеет score в [0..1] и source_doc='policy_v3.pdf'.
    """
    await rag_service.ingest(
        _BANK_DOCUMENT,
        metadata={"source": "policy_v3.pdf"},
        namespace="docs",
    )

    result = await rag_service.augment_prompt_with_citations(
        query="условия кредита", system_prompt="", namespace="docs", top_k=3
    )

    assert "Контекст из базы знаний" in result.prompt
    assert "кредит" in result.prompt.lower()
    assert len(result.citations) >= 1
    for cit in result.citations:
        assert 0.0 <= cit.score <= 1.0, f"score out of range: {cit.score}"
        assert cit.source_doc == "policy_v3.pdf", (
            f"citation.source_doc должен быть 'policy_v3.pdf', got {cit.source_doc!r}"
        )


@pytest.mark.e2e
@pytest.mark.asyncio
@pytest.mark.integration
async def test_namespace_filter_isolates_collections(
    rag_service: RAGService,
) -> None:
    """Namespace-фильтр изолирует коллекции: search 'docs' не видит 'other'.

    Pipeline:
        1. ingest doc в namespace='docs' (про кредит);
        2. ingest другой doc в namespace='other' (про ипотеку);
        3. ``search('кредит', namespace='docs')`` → только docs-chunks.

    Asserts:
        * search в 'docs' возвращает chunks только с namespace='docs';
        * search в 'other' возвращает chunks только с namespace='other';
        * 'docs' search не возвращает 'other' chunks (cross-namespace leak).
    """
    await rag_service.ingest(
        "Кредитная политика банка и скоринг клиентов.",
        metadata={"source": "policy.pdf"},
        namespace="docs",
    )
    await rag_service.ingest(
        "Ипотека под залог квартиры с фиксированной ставкой.",
        metadata={"source": "mortgage.pdf"},
        namespace="other",
    )

    docs_hits = await rag_service.search("кредит", top_k=10, namespace="docs")
    other_hits = await rag_service.search(
        "ипотека", top_k=10, namespace="other"
    )

    assert len(docs_hits) >= 1
    assert all(
        (h.get("metadata") or {}).get("namespace") == "docs" for h in docs_hits
    ), "docs-search не должен возвращать other-chunks"
    assert len(other_hits) >= 1
    assert all(
        (h.get("metadata") or {}).get("namespace") == "other" for h in other_hits
    ), "other-search не должен возвращать docs-chunks"


@pytest.mark.e2e
@pytest.mark.asyncio
@pytest.mark.integration
async def test_delete_collection_clears_namespace(
    rag_service: RAGService,
) -> None:
    """``delete_collection`` очищает namespace, count возвращается к 0.

    Pipeline:
        1. ingest → ≥1 doc chunks in namespace='docs';
        2. ``delete_collection('docs')`` → 0 chunks;
        3. ``count('docs')`` == 0.

    Asserts:
        * count > 0 до удаления;
        * delete_collection возвращает > 0 удалённых chunks;
        * count == 0 после удаления.
    """
    await rag_service.ingest(
        _BANK_DOCUMENT, metadata={"source": "policy.pdf"}, namespace="docs"
    )

    before = await rag_service.count(collection="docs")
    assert before > 0, "count > 0 после ingest"

    removed = await rag_service.delete_collection("docs")
    assert removed > 0, "delete_collection должен вернуть >0"

    after = await rag_service.count(collection="docs")
    assert after == 0, f"count после delete должен быть 0, got {after}"
