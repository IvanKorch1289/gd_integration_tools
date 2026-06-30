"""GD Integration Tools — Streamlit entry point с structured navigation (S173).

Заменяет flat auto-discovery из ``pages/`` на явную ``st.navigation()``
(Streamlit ≥1.30). 9 секций по доменам вместо плоского списка из 70 ссылок.

Backwards-compat URL: Streamlit выводит URL из filename через regex
``r"([0-9]*)[_ -]*(.*)\\.py"`` (отбрасывает numeric prefix), поэтому
старые закладки ``/Вход``, ``/Воркфлоу``, ``/Replay_DLQ`` продолжают работать.

Запуск: ``python manage.py run-frontend`` (manage.py указывает на app.py).
Запасной legacy entry: ``Главная.py`` (deprecated, оставлен для rollback).

S172 → S173 миграция:
* S172: entry-point был ``Главная.py`` (filename-stem label).
* S173: entry-point ``app.py`` + ``st.navigation()`` с sections + явные titles/icons.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from src.frontend.streamlit_app.api_clients import (
    cached_get_health,
    cached_get_metrics,
    clear_api_cache,
)
from src.frontend.streamlit_app.shared.auth_state import is_authenticated
from src.frontend.streamlit_app.shared.page_registry import PAGE_METADATA

_project_root = Path(__file__).resolve().parents[3]


# ─────────────────────── Sidebar helpers (used by dashboard) ────────────────


def _render_sidebar_search() -> None:
    """Live-фильтр по всем страницам (Enter = поиск)."""
    st.markdown("### 🔍 Поиск по разделам")
    search = st.text_input(
        "Поиск",
        placeholder="Введите название...",
        label_visibility="collapsed",
        key="sidebar_search",
    )
    if search:
        q = search.lower()
        matches = [
            (name, meta) for name, meta in PAGE_METADATA.items()
            if q in meta["title"].lower() or q in name.lower()
        ]
        if matches:
            shown = matches[:8]
            extra = len(matches) - len(shown)
            st.markdown(f"**Найдено:** {len(matches)}")
            for name, meta in shown:
                st.page_link(f"pages/{name}.py", label=meta["title"], icon=meta["icon"])
            if extra > 0:
                st.caption(f"…ещё {extra}")
        else:
            st.caption(f"Ничего не найдено по запросу «{search}»")


def _emit_page_render_event(
    *, page_key: str, render_start: float
) -> None:
    """S173 M8.1: emit ``frontend.page.rendered`` audit-event.

    Lightweight observability — non-blocking. Lazy-import
    ``emit_audit_safe`` (dev-environments без full DI stack не
    сломаются). Graceful fallback (return immediately) если facade
    недоступен.
    """
    import time as _time

    try:
        from src.backend.core.audit.facade import emit_audit_safe

        emit_audit_safe(
            event_type="frontend.page.rendered",
            payload={
                "page_key": page_key,
                "render_ms": int(
                    (_time.monotonic() - render_start) * 1000
                ),
                "session_id": (
                    st.runtime.scriptrunner.get_script_run_ctx().session_id
                    if hasattr(st, "runtime") else None
                ),
            },
            severity="info",
        )
    except Exception as _exc:  # pragma: no cover — never fail caller
        import logging as _logging
        _logging.getLogger("frontend.app").debug(
            "frontend.page.rendered: audit-event emit failed: %s", _exc
        )


def _render_dashboard_sidebar() -> None:
    """Live-фильтр в sidebar главной страницы.

    Quick Access удалён — Streamlit st.navigation() теперь даёт
    structured sidebar (9 sections) вместо flat list. Дублировать
    навигацию не нужно.
    """
    with st.sidebar:
        _render_sidebar_search()
        st.divider()
        st.caption(f"📚 Всего {len(PAGE_METADATA)} страниц →")


# ──────────────────────────── Dashboard page ────────────────────────────────


def render_dashboard() -> None:
    """Главная: KPI + Health + login CTA + onboarding tips.

    Вызывается как ``st.Page`` callback (см. ``_build_navigation``).
    Streamlit передаёт сюда rerun-state автоматически.

    S173 M8.1: render-telemetry — structured audit-event при page render.
    Emits ``frontend.page.rendered`` event with metrics snapshot для
    observability. Lazy-import (dev-environments без full DI stack
    не сломаются).
    """
    import time as _time

    render_start = _time.monotonic()
    _render_dashboard_sidebar()

    # S173 M8.1: page-render audit-event.
    _emit_page_render_event(
        page_key="00_Главная",
        render_start=render_start,
    )

    # Header с логотипом
    col_title, col_logo = st.columns([8, 1])
    with col_title:
        st.title("GD Integration Tools")
        st.caption("Корпоративная интеграционная шина — Панель управления")
    with col_logo:
        logo_path = (
            _project_root / "src" / "static" / "images" / "kuban_credit_logo.svg"
        )
        if logo_path.exists():
            st.image(str(logo_path), width=120)

    # Login CTA
    if not is_authenticated():
        st.info(
            "Вы не авторизованы. Для доступа к разделам (Маршруты, Логи, Воркфлоу "
            "и др.) необходимо войти."
        )
        if st.button("Войти", type="primary", key="home_login_btn"):
            st.switch_page("pages/00_Вход.py")
        st.divider()

    # KPI Метрики
    try:
        metrics = cached_get_metrics()
    except Exception:
        metrics = {}

    if metrics:
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("DSL маршруты", metrics.get("routes_total", 0))
        c2.metric("Действия", metrics.get("actions_count", 0))
        c3.metric("Включено", metrics.get("routes_enabled", 0))
        c4.metric("Отключено (FF)", metrics.get("routes_disabled", 0))
        c5.metric("Сервисы", len(metrics.get("services", [])))
        c6.metric("Фича флаги", len(metrics.get("feature_flags_disabled", [])))
    else:
        st.warning("Не удалось загрузить метрики. Проверьте подключение к backend.")

    # Health
    st.subheader("Здоровье компонентов")
    try:
        health = cached_get_health()
    except Exception:
        health = {}
    if health:
        cols = st.columns(min(len(health), 4))
        for i, (name, status) in enumerate(health.items()):
            with cols[i % len(cols)]:
                if status:
                    st.success(f"✓ {name}")
                else:
                    st.error(f"✗ {name}")
    else:
        st.info("Здоровье компонентов: данные недоступны.")

    # Refresh
    st.divider()
    col_refresh, col_interval = st.columns([1, 3])
    with col_refresh:
        if st.button("Обновить", key="home_refresh"):
            clear_api_cache()
            st.rerun()
    with col_interval:
        st.caption(
            "Данные обновляются при нажатии «Обновить» или перезагрузке страницы."
        )

    # Onboarding tips
    st.divider()
    st.header("Что внутри")
    st.markdown(
        """
**Быстрый старт**

- 👋 Если вы здесь впервые — откройте **🎓 Обучение** в боковой панели
  (7-шаговый онбординг).
- 🔍 Не знаете, куда идти? Воспользуйтесь **поиском по разделам** выше.
- 📚 Полный список страниц — в боковой панели (sidebar).

**Поддержка**

- Документация по админ-страницам: см. `docs/frontend/`.
- Баги и идеи: внутренний трекер.
"""
    )


# ─────────────────────── st.navigation() registration ───────────────────────


# Доменные секции навигации. Каждый page-key обязан существовать в PAGE_METADATA
# (иначе — пропускается с предупреждением при boot).
NAV_SECTIONS: dict[str, list[str]] = {
    "🎓 Обучение": ["00_Вход", "04_Обучение"],
    "🔌 Интеграция": ["11_Маршруты", "37_API_Вызовы", "62_Админ_схем"],
    "⚙️ Воркфлоу": [
        "16_Воркфлоу", "17_Replay_Воркфлоу", "18_Версионирование_Воркфлоу",
        "19_Saga_Компенсации", "15_Оценка_стоимости_Workflow", "66_Логи_Воркфлоу",
    ],
    "📦 Операции": [
        "10_Заказы", "12_Логи", "13_Конструктор_Cron", "14_Панель_Cron",
        "43_Логи_в_реальном_времени",
    ],
    "🤖 ИИ": [
        "20_AI_Чат", "21_AI_Обратная_связь", "22_RAG_Консоль", "23_AI_Учёт_затрат",
        "47_AI_Безопасность", "48_Лаборатория_промптов", "49_Реестр_моделей",
        "81_Адаптивная_RAG_панель",
        "75_Мастер_загрузки_RAG",
        "85_Массовая_загрузка_RAG",
    ],
    "🛠 DSL": [
        "30_DSL_Площадка", "31_DSL_Визуальный_редактор", "32_DSL_Конструктор",
        "33_DSL_Шаблоны", "34_DSL_Отладчик", "35_Мастер_генерации_кода",
        "36_Экспресс_боты", "38_Галерея_блюпринтов", "39_Консоль_вызовов",
        "46_DSL_Пробный_прогон",
    ],
    "🛡 Устойчивость": [
        "52_Устойчивость", "54_Replay_DLQ", "78_Плавная_деградация",
        "79_Редактор_профиля_устойчивости", "80_Параллелизм_конвейера",
    ],
    "🔍 Мониторинг": [
        "41_Поиск", "51_Проверка_здоровья", "53_Монитор_очереди",
        "55_Монитор_пула", "56_Процессы", "57_Файлы_S3", "58_Шина_действий",
        "59_Отладчик_маршрутов", "60_Админ_кеша", "61_Журнал_аудита",
        "96_Монитор_зависших_сообщений",
    ],
    "🏢 Админ": [
        "45_Админ", "50_Фича_флаги", "68_Маркетплейс_плагинов",
        "70_Тенанты", "71_Матрица_возможностей", "72_HITL_Панель",
        "73_Просмотр_конфига", "76_Подключение_плагинов", "77_Каталог_процессоров",
        "88_Тенантные_фича_флаги", "83_Инспекция_тенанта", "64_SQL_Админ",
        "65_Сервисы", "67_Задачи", "86_Аудит_использования_DSL",
        "95_Покрытие_EIP", "63_Вики",
    ],
}


def _build_navigation() -> st.navigation:
    """Собрать sections dict и вернуть ``st.navigation``.

    Missing page-keys логируются в stderr (НЕ крашат boot — fallback to flat).
    S172 M7.2: structured audit-event emit вместо bare print — observability
    через ClickHouse / Redis stream (через ``emit_audit_safe`` facade,
    lazy-import для dev-environments).
    """
    import time

    bootstrap_start = time.monotonic()
    pages_by_section: dict[str, list[st.Page]] = {}

    # Dashboard — default
    pages_by_section["🏠 Главная"] = [
        st.Page(
            render_dashboard, title="Главная", icon=":material/home:", default=True
        ),
    ]

    missing: list[str] = []
    for section_name, page_keys in NAV_SECTIONS.items():
        section_pages: list[st.Page] = []
        for key in page_keys:
            meta = PAGE_METADATA.get(key)
            if meta is None:
                missing.append(key)
                continue
            section_pages.append(
                st.Page(
                    f"pages/{key}.py",
                    title=meta["title"],
                    icon=meta["icon"],
                )
            )
        if section_pages:
            pages_by_section[section_name] = section_pages

    bootstrap_ms = int((time.monotonic() - bootstrap_start) * 1000)

    if missing:
        import sys

        # S172 M7.2: structured audit-event вместо bare print. Lazy-import
        # для dev-environments без full DI stack.
        warning_payload = {
            "missing_count": len(missing),
            "missing_keys": missing,
            "bootstrap_ms": bootstrap_ms,
        }
        try:
            from src.backend.core.audit.facade import emit_audit_safe

            emit_audit_safe(
                event_type="frontend.nav.missing_pages",
                payload=warning_payload,
                severity="warning",
            )
        except Exception as exc:  # never fail caller
            # Fallback to stderr (backward-compat pre-Sept-2026 deployments).
            print(
                f"[app.py] WARN: {warning_payload['missing_count']} "
                f"page-key(s) missing from PAGE_METADATA: {missing} "
                f"(audit-event emit failed: {exc})",
                file=sys.stderr,
            )

    return st.navigation(pages_by_section)


# Bootstrap
pg = _build_navigation()
pg.run()
