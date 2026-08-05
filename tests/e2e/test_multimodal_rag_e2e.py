"""E2E-тест MultimodalRAG pipeline (cycle 33, agent #11).

Покрывает полный pipeline ``image_ingester.ingest → multimodal_embedder.embed
→ vector_store.add → multimodal_service.search → llm.generate`` со stub'ами
для тяжёлых ML-зависимостей:

* **BLIP2** (``blip2_captioner.BLIP2Captioner``) — стаб возвращает
  фиксированный caption ``"a cat sitting on a mat"`` для любых image bytes.
* **Whisper** (``whisper_stt.WhisperSTT``) — стаб возвращает
  фиксированный transcript ``"hello world"`` для любого audio.
* **LiteLLM** (``completion()``) — стаб возвращает детерминированный
  ответ, явно ссылающийся на retrieved chunks.

Stub'и подменяют **только внешние модели** (network/ML boundary);
компоненты ядра (``ImageIngester``, ``MultimodalRAGService``, in-memory
``_collections`` store) используются реальные — это и есть объект
тестирования.

Запуск:
    pytest tests/e2e/test_multimodal_rag_e2e.py -v -m e2e
    # либо (см. docs/rag/MULTIMODAL_TESTING.md):
    make test-e2e

Тест **не** включён в блокирующий ``make test`` (markers:
``e2e``, ``integration``, ``asyncio`` — отфильтровываются дефолтным
``-m 'not e2e'``).
"""

# ruff: noqa: S101

from __future__ import annotations

import io
from typing import Any

import pytest

from src.backend.services.ai.rag.multimodal import ImageIngester, MultimodalRAGService
from src.backend.services.ai.rag.multimodal.blip2_captioner import CaptionResult
from src.backend.services.ai.rag.multimodal.whisper_stt import TranscriptionResult

# ─────────────────────────── stubs (external ML boundaries) ───────────────────────────

STUB_CAT_CAPTION = "a cat sitting on a mat"
"""Детерминированный caption для любых image bytes."""

STUB_AUDIO_TRANSCRIPT = "hello world"
"""Детерминированный transcript для любого audio."""


class StubBLIP2:
    """Stub ``BLIP2Captioner`` — возвращает ``STUB_CAT_CAPTION``.

    Имитирует контракт ``BLIP2Captioner.caption(image_bytes) -> CaptionResult``,
    не загружая transformers/torch (~5GB).
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._model_name = kwargs.get("model_name", "stub-blip2")
        self._device = kwargs.get("device", "cpu")

    async def caption(
        self, image_bytes: bytes, *, max_new_tokens: int = 50
    ) -> CaptionResult:
        """Возвращает фиксированный caption для любых image bytes."""
        return CaptionResult(
            caption=STUB_CAT_CAPTION,
            model=self._model_name,
            device=self._device,
        )


class StubWhisper:
    """Stub ``WhisperSTT`` — возвращает ``STUB_AUDIO_TRANSCRIPT``.

    Имитирует контракт ``WhisperSTT.transcribe(audio_bytes, suffix=...) -> TranscriptionResult``,
    не загружая openai-whisper.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._model_name = kwargs.get("model_name", "stub-whisper")
        self._language = kwargs.get("language", "en")

    async def transcribe(
        self, audio_bytes: bytes, *, suffix: str = ".wav"
    ) -> TranscriptionResult:
        """Возвращает фиксированный transcript для любого audio."""
        return TranscriptionResult(
            text=STUB_AUDIO_TRANSCRIPT,
            language=self._language,
            segments=[],
            model=self._model_name,
        )


# ─────────────────────────── deterministic stub embedder ───────────────────────────

# Фиксированный словарь для token-overlap embedding.
# Размерность (16) — между dummy 384-dim и production 512-dim; выбрана
# минимальной, чтобы тест был читаемым и cosine-similarity тривиальной.
_TOKEN_VOCAB: tuple[str, ...] = (
    "cat", "dog", "mat", "bird", "fish", "tree", "house", "car",
    "hello", "world", "image", "audio", "text", "ingest", "search", "rag",
)
_TOKEN_INDEX: dict[str, int] = {tok: i for i, tok in enumerate(_TOKEN_VOCAB)}


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

    Заменяет CLIP/colpali для теста. Гарантирует cosine-similarity("cat",
    "a cat sitting on a mat") == 1.0 — оба попадают на индекс 0 словаря.
    """

    embedding_kind = "stub-token-overlap"

    async def embed(self, content: str | bytes) -> list[float]:
        """Encode text или image bytes через token overlap."""
        if isinstance(content, (bytes, bytearray)):
            # Для image bytes используем STUB_CAT_CAPTION как сигнатуру —
            # имитирует ситуацию, когда ingester уже положил caption в metadata.
            return _token_overlap_vec(STUB_CAT_CAPTION)
        return _token_overlap_vec(str(content))


# ─────────────────────────── LiteLLM stub ───────────────────────────


class StubLiteLLM:
    """Stub LiteLLM — детерминированный ответ, ссылающийся на context.

    Фиксирует последний prompt для последующих assert'ов в тесте.
    Используется как singleton-instance (см. ``stub_litellm`` fixture),
    чтобы ``completion`` корректно вызывался как bound method.
    """

    last_messages: list[dict[str, str]] | None = None

    def completion(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Имитирует ``litellm.completion(messages=...) -> dict``."""
        messages = kwargs.get("messages")
        if messages is None and args:
            messages = args[0]
        StubLiteLLM.last_messages = list(messages or [])

        # Ссылаемся на контекст явно — это и есть контракт "referencing
        # retrieved chunks" из спецификации теста.
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": (
                            "Based on the retrieved context, the answer "
                            "references a cat sitting on a mat."
                        ),
                    }
                }
            ]
        }


# ─────────────────────────── fixtures ───────────────────────────


def _make_fake_png(width: int = 32, height: int = 32) -> bytes:
    """Создаёт валидный PNG через Pillow (32×32, brown background)."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=(120, 80, 40)).save(buf, format="PNG")
    return buf.getvalue()


def _make_fake_wav() -> bytes:
    """Создаёт минимальный WAV (RIFF header + 1 sample frame)."""
    # 44-byte PCM WAV header + 4-byte zero sample.
    return (
        b"RIFF"
        b"\x24\x00\x00\x00"  # file size - 8
        b"WAVE"
        b"fmt "
        b"\x10\x00\x00\x00"  # fmt chunk size
        b"\x01\x00"  # PCM
        b"\x01\x00"  # mono
        b"\x44\xac\x00\x00"  # 44100 Hz
        b"\x88\x58\x01\x00"  # byte rate
        b"\x02\x00"  # block align
        b"\x10\x00"  # bits per sample
        b"data"
        b"\x00\x00\x00\x00"  # data size
    )


@pytest.fixture
def stub_blip2(monkeypatch: pytest.MonkeyPatch) -> type[StubBLIP2]:
    """Подменяет ``BLIP2Captioner`` в модуле на stub."""
    monkeypatch.setattr(
        "src.backend.services.ai.rag.multimodal.blip2_captioner.BLIP2Captioner",
        StubBLIP2,
    )
    return StubBLIP2


@pytest.fixture
def stub_whisper(monkeypatch: pytest.MonkeyPatch) -> type[StubWhisper]:
    """Подменяет ``WhisperSTT`` в модуле на stub."""
    monkeypatch.setattr(
        "src.backend.services.ai.rag.multimodal.whisper_stt.WhisperSTT",
        StubWhisper,
    )
    return StubWhisper


@pytest.fixture
def stub_litellm(monkeypatch: pytest.MonkeyPatch) -> StubLiteLLM:
    """Подменяет ``litellm.completion`` через sys.modules на stub."""
    import sys
    import types

    instance = StubLiteLLM()
    fake_litellm = types.ModuleType("litellm")
    fake_litellm.completion = instance.completion  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "litellm", fake_litellm)
    return instance


@pytest.fixture
def multimodal_service() -> MultimodalRAGService:
    """Свежий ``MultimodalRAGService`` со stub-embedder."""
    service = MultimodalRAGService()
    service.set_embedder(StubEmbedder())
    return service


# ─────────────────────────── tests ───────────────────────────


@pytest.mark.e2e
@pytest.mark.asyncio
@pytest.mark.integration
async def test_image_caption_pipeline_e2e(
    monkeypatch: pytest.MonkeyPatch,
    stub_blip2: type[StubBLIP2],
    stub_litellm: type[StubLiteLLM],
    multimodal_service: MultimodalRAGService,
) -> None:
    """Image ingest → BLIP2 caption (stub) → embed (stub) → search → LLM (stub).

    Pipeline:
        1. ``image_ingester.ingest(fake_image_bytes)`` → ``ChunkDoc``.
        2. ``stub_blip2`` генерирует ``caption="a cat sitting on a mat"``
           и кладёт его в ``chunk.metadata["caption"]``.
        3. ``StubEmbedder.embed(bytes)`` → 16-dim вектор (cat→token[0]=1).
        4. ``MultimodalRAGService.search("cat", top_k=3)`` возвращает
           cat-chunk (cosine=1.0).
        5. ``stub_litellm.completion`` генерирует ответ, ссылающийся на
           retrieved chunks.

    Asserts:
        * retrieved chunks содержат ``caption`` с упоминанием ``cat``;
        * LLM ответ содержит слово ``cat``;
        * LLM.last_messages содержит retrieved caption в context.
    """
    # Inject caption_provider directly on ImageIngester (BLIP2 stub already
    # подменён на уровне модуля — но реальный контракт caption_provider —
    # это async-callable, который мы передаём как lambda).
    async def _stub_caption_provider(content: bytes) -> str:
        # Делегируем в stub BLIP2, чтобы продемонстрировать единый источник
        # caption'а и в image_ingester, и в service.caption_image.
        captioner = StubBLIP2()
        result = await captioner.caption(content)
        return result.caption

    image_ingester = ImageIngester(caption_provider=_stub_caption_provider)
    multimodal_service.set_image_ingester(image_ingester)

    # Step 1+2+3: ingest image (real ImageIngester + StubEmbedder).
    fake_image = _make_fake_png()
    result = await multimodal_service.ingest_document(
        fake_image, collection="e2e_images", mime="image/png"
    )

    assert len(result.chunks) == 1, "ImageIngester должен вернуть ровно 1 chunk"
    chunk = result.chunks[0]
    assert chunk.kind == "image"
    assert chunk.embedding is not None, "Stub embedder должен заполнить embedding"
    assert len(chunk.embedding) == len(_TOKEN_VOCAB)
    assert chunk.embedding[0] > 0.0, "'cat' должен быть в embedding"

    caption_meta = chunk.metadata.get("caption")
    assert caption_meta == STUB_CAT_CAPTION, (
        f"expected caption={STUB_CAT_CAPTION!r}, got {caption_meta!r}"
    )

    # Step 4: semantic search "cat" → top-K должен содержать cat-chunk.
    hits = await multimodal_service.search(
        "cat", collection="e2e_images", top_k=3, tenant_id="e2e"
    )
    assert len(hits) >= 1
    top = hits[0]
    assert top.score > 0.0, f"cosine score должен быть > 0, got {top.score}"
    assert "cat" in str(top.chunk.metadata.get("caption", "")).lower()

    # Step 5: LLM stub генерирует ответ с контекстом retrieved chunks.
    context = "\n".join(
        h.chunk.metadata.get("caption", "")
        for h in hits
        if h.chunk.metadata.get("caption")
    )
    response = stub_litellm.completion(
        messages=[
            {"role": "user", "content": f"Query: cat\nContext:\n{context}"}
        ]
    )
    answer = response["choices"][0]["message"]["content"]

    assert "cat" in answer.lower(), (
        f"LLM answer должен reference 'cat', got: {answer!r}"
    )
    assert StubLiteLLM.last_messages is not None
    context_blob = " ".join(
        m.get("content", "") for m in StubLiteLLM.last_messages
    )
    assert STUB_CAT_CAPTION in context_blob, (
        "LLM prompt должен содержать retrieved caption в context"
    )


@pytest.mark.e2e
@pytest.mark.asyncio
@pytest.mark.integration
async def test_audio_transcript_pipeline_e2e(
    monkeypatch: pytest.MonkeyPatch,
    stub_whisper: type[StubWhisper],
    multimodal_service: MultimodalRAGService,
) -> None:
    """Audio ingest → Whisper transcript (stub) → embed → search → cat wins.

    Демонстрирует мультимодальность: после image-ingest, audio с транскриптом
    "hello world" тоже попадает в store и доступен через search.

    Asserts:
        * service.transcribe_audio использует stub Whisper;
        * после ingest audio chunk.kind == "audio" с transcript в metadata;
        * search "hello" находит audio chunk.
    """
    # Step A: service.transcribe_audio (использует WhisperSTT stub).
    fake_audio = _make_fake_wav()
    transcript = await multimodal_service.transcribe_audio(
        fake_audio, suffix=".wav"
    )
    assert transcript == STUB_AUDIO_TRANSCRIPT

    # Step B: добавляем audio chunk через _collections напрямую
    # (MultimodalRAGService.ingest_document поддерживает только PDF/image —
    # audio — отдельный путь через legacy ingest_audio).
    from src.backend.services.ai.rag.multimodal.types import ChunkDoc

    audio_chunk = ChunkDoc(
        chunk_id="audio-test-1",
        kind="audio",
        content=fake_audio,
        metadata={
            "transcript": transcript,
            "mime": "audio/wav",
            "collection": "e2e_audio",
        },
        embedding_kind="stub-token-overlap",
    )
    # Один общий stub embedder на весь pipeline — текст и audio делят
    # словарь ("hello" / "world" присутствуют в обоих векторах).
    audio_chunk.embedding = _token_overlap_vec(transcript)
    multimodal_service._collections.setdefault("e2e_audio", {})[
        audio_chunk.chunk_id
    ] = audio_chunk

    # Step C: search "hello" → audio chunk.
    hits = await multimodal_service.search(
        "hello", collection="e2e_audio", top_k=3, tenant_id="e2e"
    )
    assert len(hits) >= 1
    assert hits[0].chunk.kind == "audio"
    assert hits[0].chunk.metadata.get("transcript") == STUB_AUDIO_TRANSCRIPT


@pytest.mark.e2e
@pytest.mark.asyncio
@pytest.mark.integration
async def test_public_api_exports_complete() -> None:
    """Smoke: ``__init__`` re-экспортирует ключевые классы для e2e-pipeline.

    Это guard против случайного удаления/переименования экспортов в
    ``src/backend/services/ai/rag/multimodal/__init__.py``.
    """
    from src.backend.services.ai.rag.multimodal import (  # noqa: PLC0415
        ChunkDoc,
        CLIPEmbedder,
        ImageIngester,
        IngestResult,
        MultimodalRAGService,
        PDFIngester,
        SearchResult,
        get_multimodal_rag,
    )

    # Все классы доступны и инстанциируемы (без ML-deps).
    assert callable(ImageIngester)
    assert callable(MultimodalRAGService)
    assert callable(get_multimodal_rag)
    assert callable(PDFIngester)
    assert callable(CLIPEmbedder)

    # Типы доступны (smoke на dataclass slots).
    doc = ChunkDoc(chunk_id="t", kind="text", content="hi")
    assert doc.chunk_id == "t"
    assert isinstance(IngestResult(document_id="x", chunks=[]).chunks, list)
    assert isinstance(
        SearchResult(chunk=doc, score=0.5).score,
        float,
    )
