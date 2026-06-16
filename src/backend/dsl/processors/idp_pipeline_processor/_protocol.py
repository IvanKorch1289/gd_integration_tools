"""Structural protocol for IDPPipelineProcessor mixins.

Sprint 36 (tech-debt): объявляет cross-mixin атрибуты и методы, чтобы
mypy видел ``self._doc_type``, ``self._threshold``, ``self._route`` и т.д.
"""

from __future__ import annotations

from typing import Any, Protocol

from src.backend.dsl.processors.idp_pipeline_processor.state import IDPResult


class _IDPPipelineProtocol(Protocol):
    """Общий контракт для IDPPipelineProcessor mixins."""

    _doc_type: str
    _threshold: float
    _extractors: dict[str, list[str]] | None
    _validators: list[str] | None
    _hitl_property: str
    _result_property: str

    def _pattern_count(self, doc_type: str) -> int: ...

    def _result_to_dict(self, result: IDPResult) -> dict[str, Any]: ...

    def _route(self, result: IDPResult) -> None: ...
