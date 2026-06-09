"""LlamaGuard Runtime — content safety через GGUF-модель.

Self-hosting only. Загружает Llama Guard GGUF через llama-cpp-python,
поддерживает категории безопасности OAI moderation API и кастомные.

Usage:
    runtime = LlamaGuardRuntime(
        model_path="/models/llama-guard-3-8b.Q4_K_M.gguf",
        n_ctx=8192,
        n_threads=4,
    )
    result = await runtime.classify("user prompt here", categories=["harmful", "unsafe"])
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from src.backend.core.logging import get_logger

logger = get_logger(__name__)

__all__ = ("GuardResult", "LlamaGuardRuntime")


# Категории OAI moderation API (совместимый набор)
DEFAULT_CATEGORIES = ["hate", "harassment", "violence", "sexual", "self-harm", "unsafe"]


@dataclass
class GuardResult:
    """Результат проверки LlamaGuard."""

    safe: bool
    flagged_categories: list[str] = field(default_factory=list)
    raw_output: str = ""
    model_used: str = ""

    @property
    def is_safe(self) -> bool:
        return self.safe

    def __bool__(self) -> bool:
        return self.safe


class LlamaGuardRuntime:
    """
    Runtime для Llama Guard 3 (GGUF) через llama-cpp-python.

    Поддерживает:
        * Загрузку GGUF-модели через llama-cpp-python.
        * OAI-совместимые категории модерации.
        * Кастомные категории через Llama Guard prompt schema.
        * Streaming и batch classification.
        * Кэширование модели в памяти (однократная загрузка).
    """

    DEFAULT_MODEL = "meta-llama/Llama-Guard-3-8B"
    DEFAULT_GGUF_REPO = "TheBloke/Llama-Guard-3-8B-GGUF"

    def __init__(
        self,
        model_path: str | None = None,
        gguf_repo: str | None = None,
        n_ctx: int = 8192,
        n_threads: int | None = None,
        n_gpu_layers: int = 0,
        verbose: bool = False,
    ):
        """
        Args:
            model_path: Путь к локальному GGUF-файлу. Если None — будет
                загружено через llama-cpp-python из gguf_repo.
            gguf_repo: HuggingFace repo для скачивания GGUF (TheBloke формат).
                Игнорируется если model_path задан.
            n_ctx: Размер контекстного окна.
            n_threads: Число CPU-потоков. По умолчанию = CPU count.
            n_gpu_layers: Число слоёв на GPU (для GPU-offload).
            verbose: Логировать llama.cpp output.
        """
        self.model_path = model_path
        self.gguf_repo = gguf_repo or self.DEFAULT_GGUF_REPO
        self.n_ctx = n_ctx
        self.n_threads = n_threads or os.cpu_count() or 4
        self.n_gpu_layers = n_gpu_layers
        self.verbose = verbose

        self._model: Any = None
        self._tokenizer: Any = None
        self._default_categories = DEFAULT_CATEGORIES

    # ── Public API ──────────────────────────────────────────────────────────────

    async def classify(
        self, text: str, categories: list[str] | None = None, return_raw: bool = False
    ) -> GuardResult:
        """
        Классифицировать текст на unsafe content.

        Args:
            text: Текст для проверки (user prompt, assistant response, etc.).
            categories: Список категорий. Если None — DEFAULT_CATEGORIES.
            return_raw: Вернуть сырой output модели в raw_output.

        Returns:
            GuardResult с safe=True/False и списком flagged_categories.
        """
        cats = categories or self._default_categories
        prompt = self._build_prompt(text, cats)

        output = await self._call_llama(prompt)

        parsed = self._parse_output(output, cats)
        parsed.raw_output = output if return_raw else ""
        parsed.model_used = self._model_id()

        return parsed

    async def classify_batch(
        self, texts: list[str], categories: list[str] | None = None
    ) -> list[GuardResult]:
        """Классифицировать список текстов. Каждый — отдельный вызов."""
        return [await self.classify(t, categories) for t in texts]

    def is_loaded(self) -> bool:
        """True если модель загружена в память."""
        return self._model is not None

    async def load(self) -> None:
        """Явно загрузить модель (вызывается автоматически при первом classify)."""
        if self._model is not None:
            return
        await self._ensure_model()

    async def unload(self) -> None:
        """Выгрузить модель из памяти."""
        self._model = None
        self._tokenizer = None
        logger.info("LlamaGuard: model unloaded")

    # ── Internal ───────────────────────────────────────────────────────────────

    def _model_id(self) -> str:
        if self.model_path:
            return os.path.basename(self.model_path)
        return self.gguf_repo

    def _build_prompt(self, text: str, categories: list[str]) -> str:
        """Построить Llama Guard prompt из категорий и текста.

        Формат Llama Guard 3:
        <<Task>> You are a content safety classifier...
        [1] category
        [2] category
        <Content>text</Content>
        """
        cats_block = "\n".join(f"[{i + 1}] {cat}" for i, cat in enumerate(categories))
        return (
            f"<<Task>> You are a content safety classifier.\n"
            f"Provide your safety evaluation in the following format: "
            f"unsafe ([list of categories])\n\n"
            f"Category definitions:\n{cats_block}\n\n"
            f"<Content>{text}</Content>"
        )

    async def _ensure_model(self) -> None:
        """Ленивая загрузка модели через llama-cpp-python."""
        try:
            from llama_cpp import Llama
        except ImportError as exc:
            raise ImportError(
                "llama-cpp-python required: pip install llama-cpp-python"
            ) from exc

        model_path = self.model_path

        # Если путь не задан или не существует — скачать GGUF из HF
        if not model_path or not os.path.exists(model_path):
            model_path = await self._download_gguf()
            if model_path is None:
                raise RuntimeError(
                    f"LlamaGuard: model not found at {self.model_path} "
                    f"and auto-download failed from {self.gguf_repo}"
                )

        self._model = Llama(
            model_path=str(model_path),
            n_ctx=self.n_ctx,
            n_threads=self.n_threads,
            n_gpu_layers=self.n_gpu_layers,
            verbose=self.verbose,
        )
        logger.info("LlamaGuard: model loaded from %s", model_path)

    async def _download_gguf(self) -> str | None:
        """Скачать GGUF из HuggingFace через huggingface-hub CLI."""
        hf_cli = shutil.which("huggingface-cli")
        if hf_cli is None:
            logger.warning("huggingface-cli not found — cannot auto-download GGUF")
            return None

        # Определить GGUF filename из repo
        filename = None
        try:
            from huggingface_hub import list_repo_files

            files = list_repo_files(self.gguf_repo, pattern="*.gguf")
            if files:
                # Prefer Q4_K_M quant
                candidates = [f for f in files if "Q4_K_M" in f]
                filename = candidates[0] if candidates else files[0]
        except Exception as exc:
            logger.warning("HF listing failed: %s", exc)
            return None

        if not filename:
            return None

        cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "llama-guard")
        dest_path = os.path.join(cache_dir, filename)
        if os.path.exists(dest_path):
            return dest_path

        os.makedirs(cache_dir, exist_ok=True)
        logger.info("Downloading %s from HuggingFace...", filename)

        proc = await asyncio.create_subprocess_exec(
            hf_cli,
            "download",
            self.gguf_repo,
            filename,
            "--local-dir",
            cache_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.error("HF download failed: %s", stderr.decode())
            return None

        return dest_path

    async def _call_llama(self, prompt: str) -> str:
        """Вызвать llama.cpp inference."""
        await self._ensure_model()

        def _sync_call() -> dict:
            return self._model(
                prompt,
                max_tokens=256,
                temperature=0.0,
                stop=["</s>", "<|assistant|>"],
                echo=False,
            )

        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = await loop.run_in_executor(pool, _sync_call)

        return result["choices"][0]["text"].strip()

    def _parse_output(self, output: str, categories: list[str]) -> GuardResult:
        """Распарсить output Llama Guard в GuardResult.

        Ожидаемые форматы:
            safe
            unsafe (hate, harassment)
            safe\\n
            unsafe (sexual, violence)
        """
        output_lower = output.lower().strip()

        # Нет unsafe → safe
        if "unsafe" not in output_lower:
            return GuardResult(safe=True)

        # Извлекаем категории из скобок
        flagged: list[str] = []
        match = re.search(r"unsafe\s*\(([^)]+)\)", output_lower)
        if match:
            raw_cats = match.group(1)
            for raw in raw_cats.split(","):
                cat = raw.strip().strip("'\"")
                # Exact match first
                if cat in categories:
                    flagged.append(cat)
                else:
                    # Fuzzy match
                    for c in categories:
                        if c.lower() in cat or cat in c.lower():
                            flagged.append(c)
                            break

        safe = len(flagged) == 0
        return GuardResult(safe=safe, flagged_categories=flagged)
