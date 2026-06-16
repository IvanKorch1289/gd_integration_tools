"""S68 W1 - scrape_and_store blueprint extracted from macros.py.

web scrape + store to data store.
"""

from __future__ import annotations

from src.backend.dsl.builder import RouteBuilder
from src.backend.dsl.engine.pipeline import Pipeline


def scrape_and_store(
    route_id: str,
    url: str,
    selectors: dict[str, str],
    store_action: str,
    *,
    paginate: bool = False,
    max_pages: int = 5,
    next_selector: str = "a.next",
    sort_field: str | None = None,
    description: str = "",
) -> Pipeline:
    """Web scraping pipeline: scrape → paginate → sort → store.

    Полный цикл извлечения данных с сайта:
    - CSS-selector extraction
    - Опциональная пагинация
    - Сортировка результатов
    - Сохранение через action

    Args:
        route_id: Уникальный идентификатор маршрута.
        url: URL для парсинга.
        selectors: CSS-селекторы {field_name: selector}.
        store_action: Action для сохранения результатов.
        paginate: Включить пагинацию.
        max_pages: Максимум страниц при пагинации.
        next_selector: CSS-селектор кнопки "далее".
        sort_field: Поле для сортировки результатов.
        description: Описание маршрута.

    Returns:
        Pipeline: Готовый scraping pipeline.
    """
    builder = RouteBuilder.from_(
        route_id, source=f"scrape:{url}", description=description or f"Scrape: {url}"
    )
    builder = builder.scrape(url, selectors=selectors)

    if paginate:
        builder = builder.paginate(
            next_selector=next_selector, max_pages=max_pages, start_url=url
        )

    if sort_field:
        builder = builder.sort(key_field=sort_field)

    builder = builder.dispatch_action(store_action).log("Scraping complete")
    return builder.build()
