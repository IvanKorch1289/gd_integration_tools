"""Unit tests for APICompositionProcessor (S50 W2, v21 §7.3)."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.eip.api_composition import (
    APICompositionProcessor,
    APISource,
    InMemoryCacheStore,
    MergeStrategy,
    reset_cache_store,
)


def _ex(body: Any = None) -> Exchange[Any]:
    return Exchange(
        in_message=Message(body=body, headers={}),
        out_message=Message(body=body, headers={}),
    )


# ── APISource ──────────────────────────────────────────────────────────


def test_api_source_render_url_no_params() -> None:
    s = APISource(name="x", url="https://api.example.com/users")
    assert s.render_url() == "https://api.example.com/users"


def test_api_source_render_url_with_path_params() -> None:
    s = APISource(
        name="x",
        url="https://api.example.com/users/{user_id}",
        path_params={"user_id": "u-1"},
    )
    assert s.render_url() == "https://api.example.com/users/u-1"


# ── APICompositionProcessor: validation ───────────────────────────────


def test_processor_validates_empty_sources() -> None:
    with pytest.raises(ValueError, match="sources не может быть пустым"):
        APICompositionProcessor(sources=[])


def test_processor_validates_duplicate_names() -> None:
    with pytest.raises(ValueError, match="duplicate source name"):
        APICompositionProcessor(
            sources=[
                APISource(name="dup", url="https://a.com"),
                APISource(name="dup", url="https://b.com"),
            ]
        )


def test_processor_validates_custom_merger_required() -> None:
    with pytest.raises(ValueError, match="custom_merger обязателен"):
        APICompositionProcessor(
            sources=[APISource(name="x", url="https://a.com")],
            merge_strategy=MergeStrategy.CUSTOM,
        )


# ── APICompositionProcessor: merge strategies ─────────────────────────


@pytest.mark.asyncio
async def test_merge_dicts_strategy() -> None:
    async def fetcher(url, method, headers, body, timeout):
        if "user" in url:
            return {"user_id": "u-1", "name": "John"}
        if "orders" in url:
            return {"orders": [{"id": "o-1"}]}
        return {}

    reset_cache_store()
    proc = APICompositionProcessor(
        sources=[
            APISource(name="user", url="https://api/users", transform_fn=lambda r: r),
            APISource(name="orders", url="https://api/orders", transform_fn=lambda r: r),
        ],
        http_fetcher=fetcher,
    )
    ex = _ex()
    await proc.process(ex, None)  # type: ignore[arg-type]
    body = ex.out_message.body
    assert body["user_id"] == "u-1"
    assert body["name"] == "John"
    assert body["orders"] == [{"id": "o-1"}]


@pytest.mark.asyncio
async def test_list_strategy() -> None:
    async def fetcher(url, method, headers, body, timeout):
        return {"data": url}

    reset_cache_store()
    proc = APICompositionProcessor(
        sources=[
            APISource(name="a", url="https://api/a"),
            APISource(name="b", url="https://api/b"),
        ],
        merge_strategy=MergeStrategy.LIST,
        http_fetcher=fetcher,
    )
    ex = _ex()
    await proc.process(ex, None)  # type: ignore[arg-type]
    body = ex.out_message.body
    assert isinstance(body, list)
    assert len(body) == 2


@pytest.mark.asyncio
async def test_custom_strategy() -> None:
    async def fetcher(url, method, headers, body, timeout):
        return {"count": int(url[-1])}

    reset_cache_store()

    def custom_merger(results: dict[str, Any]) -> Any:
        return {"total": sum(r["count"] for r in results.values())}

    proc = APICompositionProcessor(
        sources=[
            APISource(name="a", url="https://api/1"),
            APISource(name="b", url="https://api/2"),
        ],
        merge_strategy=MergeStrategy.CUSTOM,
        custom_merger=custom_merger,
        http_fetcher=fetcher,
    )
    ex = _ex()
    await proc.process(ex, None)  # type: ignore[arg-type]
    assert ex.out_message.body == {"total": 3}


# ── Transform ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_transform_fn_applied() -> None:
    async def fetcher(url, method, headers, body, timeout):
        return {"raw": "data"}

    reset_cache_store()
    proc = APICompositionProcessor(
        sources=[
            APISource(
                name="x",
                url="https://api/x",
                transform_fn=lambda r: {"wrapped": r["raw"]},
            )
        ],
        http_fetcher=fetcher,
    )
    ex = _ex()
    await proc.process(ex, None)  # type: ignore[arg-type]
    assert ex.out_message.body == {"wrapped": "data"}


# ── Cache ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cache_hit_skips_fetch() -> None:
    call_count = {"n": 0}

    async def fetcher(url, method, headers, body, timeout):
        call_count["n"] += 1
        return {"data": call_count["n"]}

    cache = InMemoryCacheStore()
    cache.set("GET:https://api/x", {"data": 999}, ttl_seconds=60)

    proc = APICompositionProcessor(
        sources=[APISource(name="x", url="https://api/x", cache_ttl_seconds=60)],
        http_fetcher=fetcher,
        cache_store=cache,
    )
    ex = _ex()
    await proc.process(ex, None)  # type: ignore[arg-type]
    # Cache hit → fetcher not called
    assert call_count["n"] == 0
    assert ex.out_message.body == {"data": 999}


@pytest.mark.asyncio
async def test_cache_miss_fetches_and_caches() -> None:
    call_count = {"n": 0}

    async def fetcher(url, method, headers, body, timeout):
        call_count["n"] += 1
        return {"data": call_count["n"]}

    cache = InMemoryCacheStore()
    proc = APICompositionProcessor(
        sources=[APISource(name="x", url="https://api/x", cache_ttl_seconds=60)],
        http_fetcher=fetcher,
        cache_store=cache,
    )
    # First call: miss
    ex1 = _ex()
    await proc.process(ex1, None)  # type: ignore[arg-type]
    assert ex1.out_message.body == {"data": 1}
    # Second call: hit
    ex2 = _ex()
    await proc.process(ex2, None)  # type: ignore[arg-type]
    assert ex2.out_message.body == {"data": 1}  # from cache
    assert call_count["n"] == 1


# ── Fallback on error ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fallback_value_on_error() -> None:
    async def fetcher(url, method, headers, body, timeout):
        if "fail" in url:
            raise RuntimeError("upstream down")
        return {"ok": True}

    reset_cache_store()
    proc = APICompositionProcessor(
        sources=[
            APISource(name="ok", url="https://api/ok"),
            APISource(
                name="fail",
                url="https://api/fail",
                fallback_value={"degraded": True},
            ),
        ],
        http_fetcher=fetcher,
    )
    ex = _ex()
    await proc.process(ex, None)  # type: ignore[arg-type]
    # Both succeed (one with fallback)
    assert ex.out_message.body["ok"] is True
    assert ex.out_message.body["degraded"] is True
    # Errors recorded but doesn't fail
    assert "fail" in ex.properties["composition_errors"]


@pytest.mark.asyncio
async def test_no_fallback_records_error() -> None:
    async def fetcher(url, method, headers, body, timeout):
        raise RuntimeError("upstream down")

    reset_cache_store()
    proc = APICompositionProcessor(
        sources=[APISource(name="x", url="https://api/x")],  # no fallback
        http_fetcher=fetcher,
    )
    ex = _ex()
    await proc.process(ex, None)  # type: ignore[arg-type]
    # Error caught by @handle_processor_error
    assert ex.error is not None
    assert "upstream down" in ex.error


# ── Query params + path params ────────────────────────────────────────


@pytest.mark.asyncio
async def test_path_and_query_params() -> None:
    captured_urls: list[str] = []

    async def fetcher(url, method, headers, body, timeout):
        captured_urls.append(url)
        return {"ok": True}

    reset_cache_store()
    proc = APICompositionProcessor(
        sources=[
            APISource(
                name="x",
                url="https://api/users/{user_id}",
                path_params={"user_id": "u-1"},
                query_params={"include": "orders", "limit": 10},
            )
        ],
        http_fetcher=fetcher,
    )
    ex = _ex()
    await proc.process(ex, None)  # type: ignore[arg-type]
    assert "users/u-1" in captured_urls[0]
    assert "include=orders" in captured_urls[0]
    assert "limit=10" in captured_urls[0]


# ── Side effect classification ─────────────────────────────────────────


def test_processor_side_effects() -> None:
    from src.backend.core.types.side_effect import SideEffectKind

    proc = APICompositionProcessor(sources=[APISource(name="x", url="https://a")])
    assert proc.side_effect == SideEffectKind.SIDE_EFFECTING
    assert proc.compensatable is False
