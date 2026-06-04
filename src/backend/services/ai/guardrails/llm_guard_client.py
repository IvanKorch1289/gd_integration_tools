"""LLM Guard self-hosted scanner client (S35 W1).

Self-hosted replacement for Rebuff/Lakera external APIs.
LLM Guard — MIT-licensed, CPU-based, no external calls.

Scanner mapping:
  rebuff:*     → PromptInjectionScanner
  lakera:pii  → AnonymizeScanner
  lakera:toxic → ToxicityScanner
  lakera:*     → PromptInjectionScanner + ToxicityScanner

Usage::

    client = LLMGuardClient()
    result = await client.scan("user prompt here")
    # result.flagged = True if any scanner detected issue
    # result.categories = list of failed scanner names
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

__all__ = ("LLMGuardClient", "LLMGuardResult")

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LLMGuardResult:
    """Результат LLM Guard scan.

    Attributes:
        flagged: True если хотя бы один scanner пометил текст как unsafe.
        score: Максимальный danger_score среди failed scanners [0.0..1.0].
        categories: Имена scanners которые зафейлили.
        details: Детали по каждому scanner'у {name: {danger_level, ...}}.
    """

    flagged: bool = False
    score: float = 0.0
    categories: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def is_safe(self) -> bool:
        return not self.flagged


class LLMGuardClient:
    """Self-hosted LLM Guard scanner client.

    Scanners are CPU-based, no GPU required, no external API calls.

    Args:
        timeout: Максимальное время на scan (сек). Default 5.
        fail_open: Если True (default) — при ошибке scanner'а возвращает safe.
                   Если False — при ошибке считаем что flagged.
        scanners: Список scanner names для rebuff-совместимого интерфейса.
                  Если None — используется DEFAULT_SCANNERS.
    """

    DEFAULT_SCANNERS = ("PromptInjection", "Toxicity")
    SCANNER_MAP: dict[str, list[str]] = {
        "PromptInjection": ["PromptInjection"],
        "Toxicity": ["Toxicity"],
        "Anonymize": ["Anonymize"],
        "Sensitive": ["Sensitive"],
        "BanTopics": ["BanTopics"],
        "EncodedKeywords": ["EncodedKeywords"],
    }

    def __init__(
        self,
        timeout: float = 5.0,
        fail_open: bool = True,
        scanners: tuple[str, ...] | None = None,
    ) -> None:
        self._timeout = timeout
        self._fail_open = fail_open
        self._scanner_names = scanners or self.DEFAULT_SCANNERS

    # ── Public API ─────────────────────────────────────────────────────────────

    async def scan(self, text: str) -> LLMGuardResult:
        """Scan text through configured LLM Guard scanners.

        Runs scanners in thread pool (they are CPU-bound).

        Args:
            text: Prompt or content to scan.

        Returns:
            LLMGuardResult с flagged/categories/score.
        """
        try:
            scanner_names = self._resolve_scanner_names()
            results = await self._run_scanners(text, scanner_names)
            return self._aggregate_results(results)
        except Exception as exc:
            logger.warning("LLMGuardClient.scan failed: %s", exc)
            if self._fail_open:
                return LLMGuardResult()
            return LLMGuardResult(
                flagged=True,
                score=1.0,
                categories=["llm_guard_error"],
                details={"error": str(exc)},
            )

    async def detect_injection(self, text: str) -> LLMGuardResult:
        """Detect prompt injection attempts (rebuff:* compatibility)."""
        return await self._run_single_scanner(text, "PromptInjection")

    async def detect_toxicity(self, text: str) -> LLMGuardResult:
        """Detect toxic content."""
        return await self._run_single_scanner(text, "Toxicity")

    # ── Internal ──────────────────────────────────────────────────────────────

    def _resolve_scanner_names(self) -> list[str]:
        """Resolve scanner names to actual LLM Guard scanner classes."""
        resolved: list[str] = []
        for name in self._scanner_names:
            if name in self.SCANNER_MAP:
                resolved.extend(self.SCANNER_MAP[name])
            else:
                resolved.append(name)
        return resolved

    async def _run_scanners(
        self, text: str, scanner_names: list[str]
    ) -> list[dict[str, Any]]:
        """Run scanners sequentially, each in thread pool."""

        results: list[dict[str, Any]] = []

        for scanner_name in scanner_names:
            result = await self._run_single_scanner(text, scanner_name)
            results.append(
                {
                    "scanner": scanner_name,
                    "flagged": result.flagged,
                    "score": result.score,
                    "categories": result.categories,
                    "details": result.details,
                }
            )
            # Early stop if flagged
            if result.flagged and not self._fail_open:
                break

        return results

    async def _run_single_scanner(self, text: str, scanner_name: str) -> LLMGuardResult:
        """Run a single scanner in thread pool."""

        def _sync_scan() -> dict[str, Any]:
            try:
                scanner = self._load_scanner(scanner_name)
                sanitized, result = scanner.scan(text)
                return {
                    "scanner": scanner_name,
                    "flagged": not result.is_safe,
                    "score": result.danger_score
                    if hasattr(result, "danger_score")
                    else 0.0,
                    "is_safe": result.is_safe,
                    "danger_level": getattr(result, "danger_level", "LOW"),
                    "sanitized": sanitized,
                }
            except ImportError as exc:
                logger.warning(
                    "LLMGuard: scanner %r not available: %s", scanner_name, exc
                )
                if self._fail_open:
                    return {"scanner": scanner_name, "flagged": False, "score": 0.0}
                return {"scanner": scanner_name, "flagged": True, "score": 1.0}
            except Exception as exc:
                logger.warning("LLMGuard: scanner %r failed: %s", scanner_name, exc)
                if self._fail_open:
                    return {"scanner": scanner_name, "flagged": False, "score": 0.0}
                return {"scanner": scanner_name, "flagged": True, "score": 1.0}

        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = await loop.run_in_executor(pool, _sync_scan)

        return LLMGuardResult(
            flagged=result["flagged"],
            score=result["score"],
            categories=[scanner_name] if result["flagged"] else [],
            details={
                "danger_level": result.get("danger_level", "LOW"),
                "sanitized": result.get("sanitized"),
            },
        )

    def _load_scanner(self, scanner_name: str) -> Any:
        """Lazily load LLM Guard scanner class."""
        from llm_guard.input_scanners import (
            Anonymize,
            BanTopics,
            EncodedKeywords,
            PromptInjection,
            Sensitive,
            Toxicity,
        )

        SCANNER_CLASSES: dict[str, Any] = {
            "PromptInjection": PromptInjection,
            "Toxicity": Toxicity,
            "Anonymize": Anonymize,
            "Sensitive": Sensitive,
            "BanTopics": BanTopics,
            "EncodedKeywords": EncodedKeywords,
        }

        cls = SCANNER_CLASSES.get(scanner_name)
        if cls is None:
            raise ImportError(f"Unknown scanner: {scanner_name}")
        return cls()

    def _aggregate_results(self, results: list[dict[str, Any]]) -> LLMGuardResult:
        """Aggregate scanner results into single LLMGuardResult."""
        flagged_results = [r for r in results if r.get("flagged")]
        if not flagged_results:
            return LLMGuardResult()

        categories = [r["scanner"] for r in flagged_results]
        max_score = max(r.get("score", 0.0) for r in flagged_results)
        details = {
            r["scanner"]: {
                "danger_level": r.get("danger_level", "LOW"),
                "score": r.get("score", 0.0),
            }
            for r in flagged_results
        }

        return LLMGuardResult(
            flagged=True, score=max_score, categories=categories, details=details
        )
