"""Общие UI components и helpers для Streamlit pages (Sprint 43 W1).

Consolidates patterns repeated across 66+ pages (per Sprint 42 W3 audit):
- setup_page(): replaces 5-line st.set_page_config boilerplate
- metric_row(): replaces 3-column st.metric pattern (36 pages)
- dataframe_view(): replaces st.dataframe with consistent styling

Usage:
    from src.frontend.streamlit_app.shared.components import (
        setup_page, metric_row, dataframe_view,
    )

    setup_page("My Page", "🚀")
    metric_row([("Label 1", value1), ("Label 2", value2)])
    dataframe_view(df)
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import streamlit as st

from src.frontend.streamlit_app.shared.page_registry import get_page_metadata

if TYPE_CHECKING:
    import pandas as pd

__all__ = (
    "setup_page",
    "metric_row",
    "dataframe_view",
    "require_auth",
    "related_pages_footer",
)


# Manual mapping of related pages (within-domain navigation).
# Каждый key — filename-stem из PAGE_METADATA.
# Values — список связанных pages (2-4 на каждую).
_RELATED_PAGES: dict[str, list[str]] = {
    # Workflow group
    "16_Воркфлоу": ["17_Replay_Воркфлоу", "18_Версионирование_Воркфлоу", "66_Логи_Воркфлоу"],
    "17_Replay_Воркфлоу": ["16_Воркфлоу", "18_Версионирование_Воркфлоу", "66_Логи_Воркфлоу"],
    "18_Версионирование_Воркфлоу": ["16_Воркфлоу", "17_Replay_Воркфлоу", "66_Логи_Воркфлоу"],
    "19_Saga_Компенсации": ["16_Воркфлоу", "66_Логи_Воркфлоу"],
    "66_Логи_Воркфлоу": ["16_Воркфлоу", "17_Replay_Воркфлоу", "54_Replay_DLQ"],
    "15_Оценка_стоимости_Workflow": ["16_Воркфлоу", "66_Логи_Воркфлоу"],
    # DSL group
    "30_DSL_Площадка": ["31_DSL_Визуальный_редактор", "32_DSL_Конструктор", "33_DSL_Шаблоны"],
    "31_DSL_Визуальный_редактор": ["30_DSL_Площадка", "32_DSL_Конструктор", "39_Консоль_вызовов"],
    "32_DSL_Конструктор": ["30_DSL_Площадка", "31_DSL_Визуальный_редактор", "33_DSL_Шаблоны"],
    "33_DSL_Шаблоны": ["30_DSL_Площадка", "32_DSL_Конструктор", "95_Покрытие_EIP"],
    "34_DSL_Отладчик": ["30_DSL_Площадка", "39_Консоль_вызовов"],
    "35_Мастер_генерации_кода": ["30_DSL_Площадка", "33_DSL_Шаблоны"],
    "36_Экспресс_боты": ["30_DSL_Площадка", "39_Консоль_вызовов"],
    "38_Галерея_блюпринтов": ["30_DSL_Площадка", "33_DSL_Шаблоны"],
    "39_Консоль_вызовов": ["37_API_Вызовы", "31_DSL_Визуальный_редактор"],
    "46_DSL_Пробный_прогон": ["30_DSL_Площадка", "31_DSL_Визуальный_редактор"],
    "86_Аудит_использования_DSL": ["95_Покрытие_EIP", "30_DSL_Площадка"],
    "95_Покрытие_EIP": ["86_Аудит_использования_DSL", "33_DSL_Шаблоны"],
    # AI/RAG group
    "20_AI_Чат": ["21_AI_Обратная_связь", "22_RAG_Консоль", "23_AI_Учёт_затрат"],
    "21_AI_Обратная_связь": ["20_AI_Чат", "48_Лаборатория_промптов"],
    "22_RAG_Консоль": ["75_Мастер_загрузки_RAG", "85_Массовая_загрузка_RAG", "81_Адаптивная_RAG_панель"],
    "23_AI_Учёт_затрат": ["20_AI_Чат", "47_AI_Безопасность"],
    "47_AI_Безопасность": ["20_AI_Чат", "48_Лаборатория_промптов", "49_Реестр_моделей"],
    "48_Лаборатория_промптов": ["20_AI_Чат", "21_AI_Обратная_связь", "47_AI_Безопасность"],
    "49_Реестр_моделей": ["47_AI_Безопасность", "23_AI_Учёт_затрат"],
    "75_Мастер_загрузки_RAG": ["22_RAG_Консоль", "85_Массовая_загрузка_RAG"],
    "81_Адаптивная_RAG_панель": ["22_RAG_Консоль", "48_Лаборатория_промптов"],
    "85_Массовая_загрузка_RAG": ["22_RAG_Консоль", "75_Мастер_загрузки_RAG"],
    # Domain (Orders/Routes)
    "10_Заказы": ["11_Маршруты", "12_Логи"],
    "11_Маршруты": ["10_Заказы", "59_Отладчик_маршрутов", "12_Логи"],
    # DevOps / Monitoring
    "12_Логи": ["43_Логи_в_реальном_времени", "66_Логи_Воркфлоу", "61_Журнал_аудита"],
    "41_Поиск": ["12_Логи", "61_Журнал_аудита"],
    "43_Логи_в_реальном_времени": ["12_Логи", "53_Монитор_очереди"],
    "51_Проверка_здоровья": ["52_Устойчивость", "96_Монитор_зависших_сообщений"],
    "52_Устойчивость": ["51_Проверка_здоровья", "54_Replay_DLQ", "79_Редактор_профиля_устойчивости"],
    "53_Монитор_очереди": ["43_Логи_в_реальном_времени", "54_Replay_DLQ"],
    "54_Replay_DLQ": ["52_Устойчивость", "53_Монитор_очереди", "66_Логи_Воркфлоу"],
    "55_Монитор_пула": ["51_Проверка_здоровья", "53_Монитор_очереди"],
    "56_Процессы": ["51_Проверка_здоровья", "55_Монитор_пула"],
    "57_Файлы_S3": ["58_Шина_действий", "60_Админ_кеша"],
    "58_Шина_действий": ["39_Консоль_вызовов", "57_Файлы_S3"],
    "59_Отладчик_маршрутов": ["11_Маршруты", "12_Логи"],
    "61_Журнал_аудита": ["12_Логи", "41_Поиск"],
    "78_Плавная_деградация": ["52_Устойчивость", "79_Редактор_профиля_устойчивости"],
    "79_Редактор_профиля_устойчивости": ["52_Устойчивость", "78_Плавная_деградация"],
    "80_Параллелизм_конвейера": ["52_Устойчивость", "78_Плавная_деградация"],
    "96_Монитор_зависших_сообщений": ["53_Монитор_очереди", "54_Replay_DLQ"],
    # Admin
    "45_Админ": ["50_Фича_флаги", "73_Просмотр_конфига", "76_Подключение_плагинов"],
    "50_Фича_флаги": ["45_Админ", "88_Тенантные_фича_флаги"],
    "60_Админ_кеша": ["45_Админ", "73_Просмотр_конфига"],
    "64_SQL_Админ": ["45_Админ", "73_Просмотр_конфига"],
    "65_Сервисы": ["45_Админ", "73_Просмотр_конфига"],
    "67_Задачи": ["45_Админ", "51_Проверка_здоровья"],
    "68_Маркетплейс_плагинов": ["45_Админ", "76_Подключение_плагинов"],
    "73_Просмотр_конфига": ["45_Админ", "76_Подключение_плагинов", "50_Фича_флаги"],
    "76_Подключение_плагинов": ["45_Админ", "68_Маркетплейс_плагинов"],
    "77_Каталог_процессоров": ["45_Админ", "76_Подключение_плагинов"],
    # Tenants
    "70_Тенанты": ["71_Матрица_возможностей", "72_HITL_Панель", "83_Инспекция_тенанта"],
    "71_Матрица_возможностей": ["70_Тенанты", "76_Подключение_плагинов"],
    "72_HITL_Панель": ["70_Тенанты", "83_Инспекция_тенанта"],
    "83_Инспекция_тенанта": ["70_Тенанты", "72_HITL_Панель", "88_Тенантные_фича_флаги"],
    "88_Тенантные_фича_флаги": ["50_Фича_флаги", "83_Инспекция_тенанта"],
}


def related_pages_footer(current_key: str) -> None:
    """Render footer with related pages (max 4) using ``st.page_link``.

    Использует ``_RELATED_PAGES`` mapping для определения связанных pages
    в пределах домена (workflow, DSL, AI, DevOps, admin, tenants).
    Pages без mapping — footer не показывается.

    Args:
        current_key: Filename-stem текущей page (например "16_Воркфлоу").
    """
    from src.frontend.streamlit_app.shared.page_registry import PAGE_METADATA

    related = _RELATED_PAGES.get(current_key, [])
    if not related:
        return

    # Фильтруем только существующие pages (defense against typos)
    valid = [k for k in related if k in PAGE_METADATA]
    if not valid:
        return

    st.divider()
    st.markdown("**Связанные разделы:**")
    cols = st.columns(len(valid))
    for i, key in enumerate(valid):
        meta = PAGE_METADATA[key]
        cols[i].page_link(
            f"pages/{key}.py",
            label=meta["title"],
            icon=meta["icon"],
        )


def require_auth(*, label: str = "этот раздел") -> bool:
    """Gate страницы за аутентификацией.

    Если пользователь не залогинен — показывает warning + кнопку
    «Войти» (redirect на 00_Вход) + ``st.stop()``.

    Это дополнительная защита (frontend layer). Backend всё равно
    проверяет RBAC через JWT — этот gate просто не показывает admin UI
    неаутентифицированным.

    Args:
        label: Название раздела для сообщения ("admin", "write action").

    Returns:
        True если пользователь аутентифицирован (выполнение продолжается).
    """
    from src.frontend.streamlit_app.shared.auth_state import is_authenticated

    if is_authenticated():
        return True

    st.warning(
        f"🔒 Требуется вход для доступа к разделу «{label}». "
        "Backend отвергнет запросы без валидного JWT."
    )
    if st.button("Войти", type="primary", key="require_auth_login"):
        st.switch_page("pages/00_Вход.py")
    st.stop()
    return False  # unreachable, but explicit for type-checkers


def setup_page(
    title: str | None = None,
    icon: str | None = None,
    *,
    layout: str = "wide",
    initial_sidebar_state: str = "expanded",
    auto_resolve: bool = True,
) -> None:
    """Standard page setup: replaces 5-line st.set_page_config boilerplate.

    S171 (S2 optimization): If title/icon not provided, auto-resolves from
    page_registry.PAGE_METADATA by inspecting caller filename.

    Replaces this pattern (used in 66+ pages):
        st.set_page_config(
            page_title="...",
            page_icon="...",
            layout="wide",
            initial_sidebar_state="expanded",
        )

    Args:
        title: Page title (shown in browser tab + Streamlit sidebar).
               If None and auto_resolve=True, looked up from registry.
        icon: Material icon / emoji / URL. If None and auto_resolve=True,
              looked up from registry.
        layout: "centered" or "wide" (default: "wide").
        initial_sidebar_state: "auto" | "expanded" | "collapsed".
        auto_resolve: If True, use page_registry to fill missing args.
    """
    if auto_resolve and (title is None or icon is None):
        import inspect
        caller_file = inspect.stack()[1].filename
        # Extract page filename without .py
        page_name = Path(caller_file).stem
        meta = get_page_metadata(page_name)
        if meta:
            if title is None:
                title = meta["title"]
            if icon is None:
                icon = meta["icon"]

    # Fallback defaults
    if title is None:
        title = "GD Integration Tools"
    if icon is None:
        icon = ":material/extension:"

    st.set_page_config(
        page_title=title,
        page_icon=icon,
        layout=layout,
        initial_sidebar_state=initial_sidebar_state,
    )


def metric_row(metrics: list[tuple[str, Any]]) -> None:
    """Render a row of st.metric widgets in equal-width columns.

    Replaces this pattern (used in 36+ pages):
        col1, col2, col3 = st.columns(3)
        with col1: st.metric("Label 1", value1)
        with col2: st.metric("Label 2", value2)
        with col3: st.metric("Label 3", value3)

    Args:
        metrics: List of (label, value) tuples. Also accepts 2-tuples
            with optional delta as 3rd element.
    """
    if not metrics:
        return
    cols = st.columns(len(metrics))
    for col, item in zip(cols, metrics, strict=True):
        label = item[0]
        value = item[1]
        delta = item[2] if len(item) > 2 else None
        with col:
            if delta is not None:
                st.metric(label, value, delta=delta)
            else:
                st.metric(label, value)


def dataframe_view(df: pd.DataFrame, **kwargs: Any) -> None:
    """Render a DataFrame with consistent styling (width='stretch').

    Replaces this pattern (used in 30+ pages):
        st.dataframe(df, width='stretch')

    Args:
        df: pandas DataFrame to display.
        **kwargs: Forwarded to st.dataframe.
    """
    kwargs.setdefault("width", "stretch")
    st.dataframe(df, **kwargs)
