"""Focused builder-тест :class:`TransformationEIPsMixin` — claim_check_in/out.

P3 message claim-check: процессор :class:`ClaimCheckProcessor` уже покрыт
``tests/unit/dsl/engine/processors/eip/test_transformation.py``. Builder-методы
не имели прямой проверки — этот файл закрывает gap: убедиться, что builder
возвращает процессор с корректным ``mode`` (store / retrieve) и выставленными
параметрами (store, ttl, threshold).
"""


from __future__ import annotations

import pytest

from src.backend.dsl.builders.base import RouteBuilder
from src.backend.dsl.engine.processors.eip.transformation import ClaimCheckProcessor


class TestClaimCheckBuilder:
    """Builder-методы ``claim_check_in`` / ``claim_check_out``."""

    def test_claim_check_in_returns_store_processor(self) -> None:
        rb = RouteBuilder.from_("test", source="http:/test").claim_check_in()
        assert len(rb._processors) == 1
        proc = rb._processors[0]
        assert isinstance(proc, ClaimCheckProcessor)
        assert proc._mode == "store"
        # Дефолты builder.
        assert proc._store == "redis"
        assert proc._ttl == 3600
        assert proc._threshold == 256 * 1024

    def test_claim_check_in_custom_args(self) -> None:
        rb = (
            RouteBuilder.from_("test", source="http:/test")
            .claim_check_in(store="s3", ttl_seconds=60, threshold_bytes=1024)
        )
        proc = rb._processors[0]
        assert isinstance(proc, ClaimCheckProcessor)
        assert proc._mode == "store"
        assert proc._store == "s3"
        assert proc._ttl == 60
        assert proc._threshold == 1024

    def test_claim_check_out_returns_retrieve_processor(self) -> None:
        rb = (
            RouteBuilder.from_("test", source="http:/test")
            .claim_check_in()
            .claim_check_out()
        )
        assert len(rb._processors) == 2
        assert all(isinstance(p, ClaimCheckProcessor) for p in rb._processors)
        # Пара в правильном порядке: store → retrieve.
        assert rb._processors[0]._mode == "store"
        assert rb._processors[1]._mode == "retrieve"

    def test_claim_check_out_default_store(self) -> None:
        """claim_check_out без предыдущего claim_check_in — допустимо (mode=retrieve)."""
        rb = RouteBuilder.from_("test", source="http:/test").claim_check_out()
        proc = rb._processors[0]
        assert isinstance(proc, ClaimCheckProcessor)
        assert proc._mode == "retrieve"

    def test_mixin_has_claim_check_methods(self) -> None:
        """Mixin :class:`TransformationEIPsMixin` предоставляет оба builder-метода."""
        from src.backend.dsl.builders.eip.transformation import TransformationEIPsMixin

        assert hasattr(TransformationEIPsMixin, "claim_check_in")
        assert hasattr(TransformationEIPsMixin, "claim_check_out")
        # Сигнатура: оба — instance methods, без обязательных аргументов (дефолты).
        import inspect

        for name in ("claim_check_in", "claim_check_out"):
            sig = inspect.signature(getattr(TransformationEIPsMixin, name))
            assert "self" in sig.parameters
            assert len(sig.parameters) >= 1


@pytest.mark.parametrize("store", ["redis", "s3"])
def test_claim_check_in_store_options(store: str) -> None:
    rb = RouteBuilder.from_("test", source="http:/test").claim_check_in(store=store)
    proc = rb._processors[0]
    assert isinstance(proc, ClaimCheckProcessor)
    assert proc._store == store
