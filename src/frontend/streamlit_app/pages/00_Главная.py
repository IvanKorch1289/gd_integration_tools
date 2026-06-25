"""Главная страница GD Integration Tools (merged APP + Home, S171).

Combines:
- Dashboard: KPI метрики + Component Health (from app.py)
- Navigation: группы страниц + redirects (from _groups/home/)
- Login button: для неаутентифицированных пользователей

Единая точка входа для русскоязычных пользователей.
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
from src.frontend.streamlit_app.shared.components import setup_page
from src.frontend.streamlit_app.shared.page_registry import PAGE_METADATA

_project_root = Path(__file__).resolve().parents[3]

setup_page()

# ──────────── S1: Quick Access в sidebar (вверху) ────────────

_QUICK_PAGES = [
    "00_Вход",
    "16_Воркфлоу",
    "20_AI_Чат",
    "10_Заказы",
    "11_Маршруты",
    "12_Логи",
    "51_Проверка_здоровья",
    "73_Просмотр_конфига",
    "50_Фича_флаги",
    "96_Монитор_зависших_сообщений",
]

with st.sidebar:
    st.markdown("### 🔍 Поиск по разделам")
    with st.form("sidebar_search", clear_on_submit=False):
        search = st.text_input(
            "Поиск",
            placeholder="Введите название...",
            label_visibility="collapsed",
        )
        submitted = st.form_submit_button("Искать")
    if submitted and search:
        matches = [
            (name, meta) for name, meta in PAGE_METADATA.items()
            if search.lower() in meta["title"].lower()
            and name in _QUICK_PAGES
        ]
        if matches:
            st.markdown("**Найдено:**")
            for name, meta in matches[:5]:
                st.page_link(f"pages/{name}.py", label=meta["title"], icon=meta["icon"])
        else:
            st.caption("Ничего не найдено")

    st.markdown("### ⚡ Быстрый доступ")
    for name in _QUICK_PAGES:
        if name in PAGE_METADATA:
            meta = PAGE_METADATA[name]
            st.page_link(f"pages/{name}.py", label=meta["title"], icon=meta["icon"])

    st.divider()
    st.caption(f"📚 Всего {len(PAGE_METADATA)} страниц в sidebar →")

# ──────────── Header с логотипом ────────────

col_title, col_logo = st.columns([8, 1])
with col_title:
    st.title("GD Integration Tools")
    st.caption("Корпоративная интеграционная шина — Панель управления")
with col_logo:
    logo_path = _project_root / "src" / "static" / "images" / "kuban_credit_logo.svg"
    if logo_path.exists():
        st.image(str(logo_path), width=120)

# ──────────── Если не залогинен — кнопка входа ────────────

if not is_authenticated():
    st.info(
        "Вы не авторизованы. Для доступа к разделам (Заказы, Маршруты, Логи и др.) "
        "необходимо войти."
    )
    if st.button("Войти", type="primary", key="home_login_btn"):
        st.switch_page("pages/00_Вход.py")
    st.divider()

# ──────────── KPI Метрики ────────────

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
    c6.metric("Фича-флаги", len(metrics.get("feature_flags_disabled", [])))
else:
    st.warning("Не удалось загрузить метрики. Проверьте подключение к backend.")

# ──────────── Component Health ────────────

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

# ──────────── Auto-refresh ────────────

st.divider()
col_refresh, col_interval = st.columns([1, 3])
with col_refresh:
    if st.button("Обновить", key="home_refresh"):
        clear_api_cache()
        st.rerun()
with col_interval:
    st.caption("Данные обновляются при нажатии «Обновить» или перезагрузке страницы.")

# ──────────── Навигация ────────────

st.divider()
st.header("Навигация по разделам")

st.markdown(
    """
Все разделы сгруппированы по префиксам:

- `00_*` — **Вход и обучение**: Вход, Главная, Обучение.
- `04_*` — **Онбординг**: Обучение.
- `10_*` — **Операции**: Заказы, Маршруты, Логи, Конструктор Cron, Панель Cron,
  Оценка стоимости Workflow, Workflows, Replay Workflow, Версионирование Workflow,
  Saga-компенсации.
- `20_*` — **AI**: AI Чат, AI Обратная связь, RAG Консоль, AI Учёт затрат.
- `30_*` — **DSL**: Площадка, Визуальный редактор, Конструктор, Шаблоны, Отладчик,
  Пробный прогон, Покрытие EIP, Аудит использования.
- `40_*` — **Поиск и логи**: Аудит, Поиск, Логи в реальном времени.
- `50_*` — **Инструменты**: Мастер генерации кода, Экспресс-боты, API Вызовы,
  Галерея блюпринтов, Консоль вызовов, Файлы S3.
- `60_*` — **Админ**: Wiki, Админ кеша, Просмотр конфига, Фича-флаги, SQL Админ,
  Сервисы, Логи Workflow, Задачи, Маркетплейс плагинов.
- `70_*` — **Тенанты**: Тенанты, Возможности, HITL Панель.
- `75_*` — **RAG/Плагины**: Мастер загрузки RAG, Массовая загрузка RAG,
  Подключение плагинов, Каталог процессоров.
- `78_*` — **Устойчивость**: Плавная деградация, Редактор профиля устойчивости,
  Параллелизм конвейера.
- `81_*` — **Adaptive RAG**: Адаптивная RAG панель.
- `83_*` — **Тенант**: Инспекция тенанта, Тенантные фича-флаги.
- `85_*` — **AI Безопасность**: Мастер загрузки RAG, Лаборатория промптов,
  AI Безопасность.
- `95_*` — **Документация**: Покрытие EIP.
- `96_*` — **Мониторинг**: Монитор зависших сообщений Outbox, Replay DLQ.
"""
)

st.divider()

st.header("Старые → новые префиксы")

_REDIRECTS: list[tuple[str, str]] = [
    ("10_Tutorial → 04_Обучение", "Онбординг"),
    ("11_Glossary → 04_Глоссарий", "Онбординг"),
    ("1_Orders → 10_Заказы", "Операции"),
    ("2_Routes → 11_Маршруты", "Операции"),
    ("3_Logs → 12_Логи", "Операции"),
    ("22_Healthcheck_Dashboard → 51_Healthcheck", "Операции"),
    ("15_Queue_Monitor → 53_Queue_Monitor", "Операции"),
    ("16_Processes_Dashboard → 56_Processes", "Операции"),
    ("25_Workflows → 16_Workflows", "Операции"),
    ("4_AI_Chat → 20_AI_Чат", "AI"),
    ("27_AI_Feedback → 21_AI_Обратная_связь", "AI"),
    ("28_RAG_Console → 22_RAG_Консоль", "AI"),
    ("5_DSL_Playground → 30_DSL_Площадка", "DSL"),
    ("6_DSL_Visual_Editor → 31_DSL_Визуальный_редактор", "DSL"),
    ("7_DSL_Builder → 32_DSL_Конструктор", "DSL"),
    ("8_DSL_Templates → 33_DSL_Шаблоны", "DSL"),
    ("9_DSL_Debugger → 34_DSL_Отладчик", "DSL"),
    ("14_Realtime_Logs → 43_Логи_в_реальном_времени", "Поиск и логи"),
    ("17_Search → 41_Поиск", "Поиск и логи"),
    ("12_Codegen_Wizard → 35_Мастер_генерации_кода", "Инструменты"),
    ("18_Express_Bots → 36_Экспресс-боты", "Инструменты"),
    ("19_API_Caller → 37_API_Вызовы", "Инструменты"),
    ("20_Blueprint_Gallery → 38_Галерея_блюпринтов", "Инструменты"),
    ("21_Invocation_Console → 39_Консоль_вызовов", "Инструменты"),
    ("23_Files_S3 → 57_Файлы_S3", "Инструменты"),
    ("29_Wiki → 63_Вики", "Админ"),
    ("30_Cache_Admin → 60_Админ_кеша", "Админ"),
    ("31_Config_Viewer → 73_Просмотр_конфига", "Админ"),
    ("32_Feature_Flags → 50_Фича_флаги", "Админ"),
    ("33_SQL_Admin → 64_SQL_Админ", "Админ"),
    ("34_Services → 65_Сервисы", "Админ"),
    ("35_Audit_Log → 61_Журнал_аудита", "Поиск и логи"),
    ("26_Tenants → 70_Тенанты", "Тенанты"),
    ("36_HITL → 72_HITL_Панель", "Тенанты"),
    ("37_Capabilities → 71_Возможности", "Тенанты"),
    ("38_RAG_Ingest → 75_Мастер_загрузки_RAG", "RAG/Плагины"),
    ("39_RAG_Bulk → 85_Массовая_загрузка_RAG", "RAG/Плагины"),
]

st.dataframe(
    [{"redirect": old, "group": grp} for old, grp in _REDIRECTS],
    hide_index=True,
    width="stretch",
)
