"""Transformation EIP-методы: split / aggregate / sort / sample / claim_check / normalize / resequence.

Sprint 60 W4 — split из eip.py (1354 LOC).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from src.backend.dsl.builders.eip._base import EIPMixinBase
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors import (
    AggregatorProcessor,
    BaseProcessor,
    ClaimCheckProcessor,
    NormalizerProcessor,
    ResequencerProcessor,
    SplitterProcessor,
)

if TYPE_CHECKING:
    from src.backend.dsl.builder import RouteBuilder

__all__ = ("TransformationEIPsMixin",)


class TransformationEIPsMixin(EIPMixinBase):
    """EIP transformation patterns: split, aggregate, sort, sample, claim_check, normalize, resequence."""

    def split(self, expression: str, processors: list[BaseProcessor]) -> "RouteBuilder":
        """Splitter: разбиение массива на отдельные Exchange по JMESPath."""
        return self._add(  # type: ignore[attr-defined]
            SplitterProcessor(expression=expression, processors=processors)
        )

    def aggregate(
        self,
        correlation_key: Callable[[Exchange[Any]], str],
        *,
        batch_size: int = 10,
        timeout_seconds: float = 30.0,
    ) -> "RouteBuilder":
        """Aggregator: собирает N Exchange по correlation_key в batch."""
        return self._add(  # type: ignore[attr-defined]
            AggregatorProcessor(
                correlation_key=correlation_key,
                batch_size=batch_size,
                timeout_seconds=timeout_seconds,
            )
        )

    def sort(
        self,
        *,
        key_fn: Callable[[Any], Any] | None = None,
        key_field: str | None = None,
        reverse: bool = False,
    ) -> "RouteBuilder":
        """Sort — сортировка list body по функции ключа или имени поля."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.eip",
            "SortProcessor",
            key_fn=key_fn,
            key_field=key_field,
            reverse=reverse,
        )

    def claim_check_in(
        self,
        *,
        store: str = "redis",
        ttl_seconds: int = 3600,
        threshold_bytes: int = 256 * 1024,
    ) -> "RouteBuilder":
        """Claim Check (store): сохраняет body в Redis/S3, body → {_claim_token: ...}.

        Args:
            store: "redis" | "s3" | "auto" (auto = S3 если payload >= threshold).
            ttl_seconds: Время жизни токена.
            threshold_bytes: Порог в байтах для переключения на S3 (по умолчанию 256 KB).
        """
        return self._add(  # type: ignore[attr-defined]
            ClaimCheckProcessor(
                mode="store",
                store=store,
                ttl_seconds=ttl_seconds,
                threshold_bytes=threshold_bytes,
            )
        )

    def claim_check_out(self) -> "RouteBuilder":
        """Claim Check (retrieve): восстанавливает body по _claim_token."""
        return self._add(ClaimCheckProcessor(mode="retrieve"))  # type: ignore[attr-defined]

    def normalize(self, target_schema: type | None = None) -> "RouteBuilder":
        """Normalizer: автоопределение формата (XML/CSV/YAML/JSON) → canonical dict."""
        return self._add(NormalizerProcessor(target_schema=target_schema))  # type: ignore[attr-defined]

    def resequence(
        self,
        correlation_key: Callable[[Exchange[Any]], str],
        *,
        sequence_field: str = "seq",
        batch_size: int = 10,
        timeout_seconds: float = 30.0,
    ) -> "RouteBuilder":
        """Resequencer: восстановление порядка сообщений по sequence_field."""
        return self._add(  # type: ignore[attr-defined]
            ResequencerProcessor(
                correlation_key=correlation_key,
                sequence_field=sequence_field,
                batch_size=batch_size,
                timeout_seconds=timeout_seconds,
            )
        )
