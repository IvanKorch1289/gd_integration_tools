# MultimodalRAG — E2E Testing Guide

Sprint 36 / cycle 33 · agent #11 · pipeline: image → embed → search → LLM.

## Что это

End-to-end тест для мультимодального RAG-пайплайна
(`MultimodalRAGService` + `ImageIngester` + внешние модели).

Покрывает реальный production-flow, но **без загрузки тяжёлых ML-deps**
(CLIP, BLIP2, Whisper, sentence-transformers, torch) — внешние модели
подменяются детерминированными stub'ами на границе сети/ML.

## Pipeline

```
image_ingester.ingest(fake_image_bytes)
   └─► ChunkDoc (kind="image", metadata.caption="a cat sitting on a mat")
         └─► StubEmbedder.embed(content) → 16-dim token-overlap vector
               └─► MultimodalRAGService._collections["e2e_images"][chunk_id]
                     └─► MultimodalRAGService.search("cat", top_k=3)
                           └─► top hit (cosine=1.0)
                                 └─► StubLiteLLM.completion(messages=[...])
                                       └─► "Based on the retrieved context, the answer references a cat..."
```

## Stubs (внешние ML-границы)

| Реальный компонент | Stub | Возвращает |
|---|---|---|
| `BLIP2Captioner.caption(bytes)` | `StubBLIP2` | `"a cat sitting on a mat"` |
| `WhisperSTT.transcribe(bytes, ...)` | `StubWhisper` | `"hello world"` |
| `litellm.completion(messages=...)` | `StubLiteLLM` | фиксированный dict, ссылающийся на контекст |
| `CLIPEmbedder.embed(content)` | `StubEmbedder` | 16-dim token-overlap unit-vector |

Stub'и подменяют **только** модели и сетевые вызовы. Ядро пайплайна —
`ImageIngester`, `MultimodalRAGService`, in-memory `_collections` — тестируется
реальное.

## Token-overlap embedder

`StubEmbedder` кодирует контент через 16-токенный словарь
(`cat`, `dog`, `mat`, ..., `rag`). Возвращает unit-vector с 1.0 на позициях
присутствующих токенов.

* `embed("cat")`              → `[1, 0, 0, ...]` (cosine=1.0 сам с собой)
* `embed("a cat ... mat")`    → `[1, 0, 1, ...]` (cosine=1.0 с "cat" из-за общего `cat`)

Гарантирует, что `search("cat")` ранжирует cat-chunk на первом месте.

## Запуск

```bash
# Только этот e2e файл (быстро):
pytest tests/e2e/test_multimodal_rag_e2e.py -v -m e2e

# Через make (документированная команда — make target test-e2e ожидается):
make test-e2e

# Все e2e тесты проекта:
pytest -v -m e2e
```

Тест **не** входит в блокирующий `make test` (markers `e2e`/`integration` отфильтровываются).
Запускается явно через `make test-e2e` или прямой вызов `pytest -m e2e`.

## Assertions

* `test_image_caption_pipeline_e2e` — проверяет весь image→caption→embed→search→LLM pipeline.
  - retrieved chunks содержат `caption` с упоминанием `cat`;
  - LLM answer содержит слово `cat`;
  - LLM prompt содержит retrieved caption в context (smoke на честный RAG-pass).
* `test_audio_transcript_pipeline_e2e` — проверяет audio→Whisper→embed→search.
  - `service.transcribe_audio` использует stub Whisper;
  - audio chunk с `kind="audio"` доступен через search.
* `test_public_api_exports_complete` — guard от удаления/переименования экспортов
  в `src/backend/services/ai/rag/multimodal/__init__.py`.

## Фикстуры

| Fixture | Scope | Назначение |
|---|---|---|
| `stub_blip2` | function | monkeypatch `BLIP2Captioner` → `StubBLIP2` |
| `stub_whisper` | function | monkeypatch `WhisperSTT` → `StubWhisper` |
| `stub_litellm` | function | подмена `litellm.completion` через `sys.modules` |
| `multimodal_service` | function | свежий `MultimodalRAGService` со `StubEmbedder` |

Все fixture cleanup через `monkeypatch` (autouse rollback).

## Расширение

### Добавить новый stub

1. Описать класс в секции **stubs (external ML boundaries)** с docstring "контракт X".
2. Передать через `monkeypatch.setattr(module, "ClassName", Stub)`.
3. При желании — добавить отдельную fixture в секции **Фикстуры**.

### Добавить новый pipeline-шаг

1. Расширить `test_image_caption_pipeline_e2e` или создать новый test.
2. Использовать **только** публичные экспорты из `multimodal.__init__`
   (см. `test_public_api_exports_complete` для guard'а).
3. Придерживаться mark'еров: `@pytest.mark.e2e`, `@pytest.mark.asyncio`,
   `@pytest.mark.integration`.

## Известные ограничения

* `StubEmbedder` детерминированный — не покрывает edge-cases реального CLIP
  (семантически близкие, но лексически разные тексты).
* `StubLiteLLM.completion` не валидирует структуру prompt'а — только
  сохраняет `last_messages` для assert'а.
* `MultimodalRAGService.ingest_document` поддерживает только PDF/image MIME;
  audio — отдельный путь через legacy `ingest_audio` (см.
  `test_audio_transcript_pipeline_e2e`).
* Feature-flag `multimodal_rag_enabled` имеет default `True` (см.
  `src/backend/core/config/features/ai.py:149`), но если окружение выставляет
  `FEATURE_MULTIMODAL_RAG_ENABLED=false`, тест нужно запускать с
  `FEATURE_MULTIMODAL_RAG_ENABLED=true` или патчить `feature_flags`.

## Связанные документы

* `docs/RAG_INGEST.md` — общий обзор RAG-индексации документации.
* `src/backend/services/ai/rag/multimodal/__init__.py` — публичный API пакета.
* `src/backend/services/ai/rag/multimodal/service.py` — фасад `MultimodalRAGService`.
* `src/backend/core/config/features/ai.py` — feature-flags (включая
  `multimodal_rag_enabled`).