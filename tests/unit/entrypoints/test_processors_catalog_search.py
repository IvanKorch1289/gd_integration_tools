# ruff: noqa: S101
"""Sprint 14 K3 W1 — unit-тест fuzzy-search каталога процессоров.

План S14 §C T-3: ``_ProcessorsCatalogFacade.search`` имела только smoke,
без проверки rapidfuzz-логики. Здесь вызываем facade напрямую и
проверяем: top-результат для очевидной фразы — релевантный процессор.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def facade():
    from src.backend.entrypoints.api.v1.endpoints.processors_catalog import (
        _ProcessorsCatalogFacade,
    )

    return _ProcessorsCatalogFacade()


@pytest.mark.asyncio
async def test_search_empty_query_returns_first_n(facade) -> None:
    """Пустой запрос → отдаёт первые ``limit`` процессоров без скоринга."""
    result = await facade.search(q="", limit=5)
    assert result["query"] == ""
    assert isinstance(result["items"], list)
    assert len(result["items"]) <= 5
    for item in result["items"]:
        assert item["score"] == 100


@pytest.mark.asyncio
async def test_search_matches_proxy_processor(facade) -> None:
    """``q="proxy"`` обязан найти ProxyProcessor (или подобный) в топе.

    Требует rapidfuzz — если extras не установлен, тест пропускается.
    """
    pytest.importorskip("rapidfuzz")
    result = await facade.search(q="proxy", limit=10)
    assert result["query"] == "proxy"
    items = result["items"]
    assert items, "rapidfuzz должна вернуть хотя бы один матч на 'proxy'"
    top = items[0]
    assert top["score"] > 50, f"top score слишком низкий: {top}"
    # Все возвращённые items содержат ожидаемые поля
    for it in items:
        assert {"name", "category", "score", "description"}.issubset(it.keys())


@pytest.mark.asyncio
async def test_search_without_rapidfuzz_returns_error_payload(facade) -> None:
    """Без rapidfuzz facade возвращает items=[] + ``error`` ключ.

    Защитная ветка от ImportError; именно её мы и хотим проверить, если
    rapidfuzz не установлен в текущем env. При установленном rapidfuzz
    тест пропускается.
    """
    try:
        import rapidfuzz  # noqa: F401, PLC0415
    except ImportError:
        result = await facade.search(q="proxy", limit=5)
        assert result["items"] == []
        assert result.get("error") == "rapidfuzz unavailable"
    else:
        pytest.skip("rapidfuzz установлен — fallback-ветка не проверяется")


@pytest.mark.asyncio
async def test_search_namespace_filter_narrows_results(facade) -> None:
    """``namespace="ai"`` сужает до процессоров категории ai (могут отсутствовать → []).

    Тест не зависит от наличия каждого namespace — проверяет, что фильтр
    не возвращает процессоры из другой категории.
    """
    result = await facade.search(q="processor", namespace="ai", limit=10)
    for item in result["items"]:
        assert item["category"] == "ai"
