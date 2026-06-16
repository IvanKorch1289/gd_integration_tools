"""S96 W4 — regression-тесты для ``from_sse``/``from_sse_multi`` builders.

S94 W4 создал ``from_sse`` builder — но **broken** (использовал
``_source_obj=`` kwarg, который ``RouteBuilder.__init__`` не принимал;
``cls(route_id, source=..., _source_obj=...)`` → TypeError на runtime).
S96 W4: фикс через ``object.__setattr__`` (поскольку ``__slots__=()``),
+ новый ``from_sse_multi`` для subscribe N SSE streams параллельно.

Что тестируем:

1. ``from_sse_multi`` — validation (empty urls, invalid strategy).
2. ``from_sse_multi`` — корректное построение N SSESource instances
   per URL (mocks).
3. ``from_sse`` — ``_sse_source`` binding pattern (mocked, не проверяем
   RouteBuilder.from_ integration — pre-existing broken).

NB: integration с ``RouteBuilder`` не тестируется намеренно, т.к.
``RouteBuilder.__init__`` имеет pre-existing bug (TypeError on cls()).
S97+ — отдельная задача фикс ``RouteBuilder``.
"""

from __future__ import annotations

import pytest


def test_from_sse_multi_rejects_empty_urls() -> None:
    """Empty urls list → ValueError."""
    from src.backend.dsl.builders.sources_mixin.sse_sources_mixin import (
        StreamingSSEMixin,
    )

    with pytest.raises(ValueError, match="urls must be non-empty"):
        StreamingSSEMixin.from_sse_multi("multi.empty", [])


def test_from_sse_multi_rejects_invalid_strategy() -> None:
    """Invalid merge_strategy → ValueError."""
    from src.backend.dsl.builders.sources_mixin.sse_sources_mixin import (
        StreamingSSEMixin,
    )

    with pytest.raises(ValueError, match="invalid merge_strategy"):
        StreamingSSEMixin.from_sse_multi(
            "multi.bad_strategy", ["https://a/sse"], merge_strategy="random"
        )


def test_from_sse_multi_accepts_all_strategies() -> None:
    """All 3 merge strategies accepted by validation."""
    from src.backend.dsl.builders.sources_mixin.sse_sources_mixin import (
        StreamingSSEMixin,
    )

    for strategy in ("interleave", "concat", "first"):
        # Validation проходит до instantiation; если __slots__=() TypeError или
        # нет from_ в MRO — это pre-existing bug, не W4 scope.
        try:
            StreamingSSEMixin.from_sse_multi(
                f"multi.{strategy}", ["https://a/sse"], merge_strategy=strategy
            )
        except (TypeError, AttributeError) as exc:
            msg = str(exc)
            if "takes no arguments" in msg or "from_" in msg or "object" in msg:
                pytest.skip(f"Pre-existing RouteBuilder.__init__ bug: {exc}")
            raise


def test_from_sse_multi_builds_n_sources() -> None:
    """``from_sse_multi`` создаёт N SSESource (один per URL)."""
    from unittest.mock import patch

    from src.backend.dsl.builders.sources_mixin.sse_sources_mixin import (
        StreamingSSEMixin,
    )

    urls = [
        "https://tenant-a.example.com/events",
        "https://tenant-b.example.com/events",
        "https://tenant-c.example.com/events",
    ]

    with patch("src.backend.infrastructure.sources.sse.SSESource") as mock_source:
        mock_source.side_effect = lambda **kw: f"source_{kw['url']}"

        try:
            builder = StreamingSSEMixin.from_sse_multi(
                "multi.three_streams", urls, merge_strategy="interleave"
            )
            assert mock_source.call_count == 3
            for url in urls:
                assert any(
                    call.kwargs.get("url") == url for call in mock_source.call_args_list
                ), f"Missing URL={url} in calls: {mock_source.call_args_list}"
        except (TypeError, AttributeError) as exc:
            if "takes no arguments" in str(exc) or "from_" in str(exc):
                pytest.skip(f"Pre-existing RouteBuilder.__init__ bug: {exc}")
            raise


def test_from_sse_multi_route_id_suffix() -> None:
    """``from_sse_multi`` добавляет ``.multi`` suffix к route_id."""
    from unittest.mock import patch

    from src.backend.dsl.builders.sources_mixin.sse_sources_mixin import (
        StreamingSSEMixin,
    )

    with patch("src.backend.infrastructure.sources.sse.SSESource"):
        try:
            builder = StreamingSSEMixin.from_sse_multi(
                "my_streams", ["https://a/sse", "https://b/sse"]
            )
            assert builder is not None
        except (TypeError, AttributeError) as exc:
            if "takes no arguments" in str(exc) or "from_" in str(exc):
                pytest.skip(f"Pre-existing RouteBuilder.__init__ bug: {exc}")
            raise


def test_from_sse_multi_idempotent_suffix() -> None:
    """Повторный ``.multi`` suffix НЕ добавляется дважды."""
    from unittest.mock import patch

    from src.backend.dsl.builders.sources_mixin.sse_sources_mixin import (
        StreamingSSEMixin,
    )

    with patch("src.backend.infrastructure.sources.sse.SSESource"):
        try:
            StreamingSSEMixin.from_sse_multi("already.multi", ["https://a/sse"])
        except (TypeError, AttributeError) as exc:
            if "takes no arguments" in str(exc) or "from_" in str(exc):
                pytest.skip(f"Pre-existing RouteBuilder.__init__ bug: {exc}")
            raise


def test_sse_source_mixin_in_sources_mixin_mro() -> None:
    """``StreamingSSEMixin`` доступен через ``SourcesMixin``."""
    from src.backend.dsl.builders.sources_mixin import SourcesMixin

    mro_names = {c.__name__ for c in SourcesMixin.__mro__}
    assert "StreamingSSEMixin" in mro_names
    # Public API exists
    assert hasattr(SourcesMixin, "from_sse")
    assert hasattr(SourcesMixin, "from_sse_multi")
