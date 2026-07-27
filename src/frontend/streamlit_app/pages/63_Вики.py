"""Wiki — full-text поиск + Diátaxis-фильтры + live DSL examples.

Wave: ``[wave:s8/k5-wiki-whoosh-extend]``. Расширяет первоначальный
Wave 10.2 scaffold:
* Diátaxis-фильтр (5 квадрантов + DSL-примеры + другое).
* Live DSL examples из ``docs/dsl/*.yaml`` с подсветкой.
* Опц. кнопка "Проверить грамматику" (ru-proofreader, fail-soft).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Protocol, cast

import streamlit as st

from src.frontend.streamlit_app.shared.components import (
    related_pages_footer,
    setup_page,
)


class _WhooshHit(Protocol):
    """Search-hit fields rendered by this page."""

    title: str
    path: str
    score: float
    snippet: str


class _WhooshIndex(Protocol):
    """Structural API used from the optional Whoosh implementation."""

    def build(self, force: bool = False) -> int: ...
    def search(
        self, query: str, top: int = 20, *, category: str | None = None
    ) -> list[_WhooshHit]: ...
    def doc_count(self) -> int: ...


class _WhooshIndexFactory(Protocol):
    def __call__(self) -> _WhooshIndex: ...


setup_page()
st.title("Wiki — поиск по документации")

# Lazy-import чтобы set_page_config был первым st-вызовом.
# S6 fix: facade import через dsl_portal (R3.10d / S36).
from src.backend.core.frontend_facade import get_whoosh_index  # noqa: E402

# The facade deliberately returns ``Any`` to keep optional Whoosh imports lazy;
# narrow only the callable surface consumed by this page instead of ignoring mypy.
_whoosh_index_factory = cast(_WhooshIndexFactory, get_whoosh_index())

_REPO_ROOT = Path(__file__).resolve().parents[4]
_DSL_DIR = _REPO_ROOT / "docs" / "dsl"


@st.cache_resource(show_spinner=False)
def _get_index() -> _WhooshIndex:
    """Создаёт/открывает WhooshIndex; сборка на первом обращении."""
    idx = _whoosh_index_factory()
    idx.build(force=False)
    return idx


idx = _get_index()
total = idx.doc_count()
st.caption(f"Документов в индексе: {total}")

# ── Search bar + Diátaxis-фильтр ─────────────────────────────────────────

CATEGORIES = {
    "Все": None,
    "Tutorials": "tutorial",
    "How-to": "how-to",
    "Reference": "reference",
    "Explanation": "explanation",
    "Runbooks": "runbook",
    "DSL": "dsl",
}

cols = st.columns([3, 1, 1])
query = cols[0].text_input("Запрос", "")
category_label = cols[1].selectbox("Категория", list(CATEGORIES))
top = cols[2].slider("Top", 1, 50, 20)

if query:
    t0 = time.perf_counter()
    hits = idx.search(query, top=top, category=CATEGORIES[category_label])
    dt = (time.perf_counter() - t0) * 1000
    st.caption(f"Найдено: {len(hits)} · {dt:.0f} ms")

    for h in hits:
        st.markdown(f"**[{h.title}]({h.path})** · `{h.path}` · score={h.score:.2f}")
        if h.snippet:
            # Snippet из Whoosh-индекса (docs/ — controlled by team, low XSS risk).
            # Тем не менее, sanitize HTML перед render: strip <script>, on-*,
            # javascript: URLs. Markdown-разметка (**, ```) сохраняется.
            import html

            safe = html.escape(h.snippet, quote=False)
            # Restore escaped markdown markers (теряются при html.escape)
            for marker in ("**", "`", "\n- ", "\n# "):
                safe = safe.replace(html.escape(marker, quote=False), marker)
            st.markdown(safe)
        st.divider()

# ── Live DSL examples (S8) ───────────────────────────────────────────────

st.subheader("Живые примеры DSL")
st.caption(f"Источник: `{_DSL_DIR.relative_to(_REPO_ROOT)}/`")

if not _DSL_DIR.is_dir():
    st.info("Каталог `docs/dsl/` пуст — добавьте `*.yaml` с примерами.")
else:
    yaml_files = sorted(_DSL_DIR.glob("*.yaml"))
    if not yaml_files:
        st.info("Нет `*.yaml` примеров в `docs/dsl/`.")
    for example in yaml_files:
        with st.expander(f"📄 {example.name}"):
            content = example.read_text(encoding="utf-8")
            st.code(content, language="yaml")
            st.caption(
                f"Скопировать: выделить блок выше / `cat {example}` в терминале."
            )

# ── Reindex + ru-grammar (опц.) ──────────────────────────────────────────

ctrl_cols = st.columns(2)
if ctrl_cols[0].button("Перестроить индекс"):
    with st.spinner("Переиндексация…"):
        n = idx.build(force=True)
    st.success(f"Переиндексация завершена: {n} документов")

if ctrl_cols[1].button("Проверить грамматику docs/ (ru)"):
    with st.spinner("Запуск ru-proofreader..."):
        try:
            from tools.checks.ru_proofread import proofread_docs

            issues = proofread_docs(_REPO_ROOT / "docs", limit_files=20)
        except ImportError as exc:
            issues = []
            st.warning(
                f"ru-proofreader недоступен: {exc}. Установите через "
                "`uv sync --extra docs-ru`."
            )
        except Exception as exc:  # noqa: BLE001
            issues = []
            st.error(f"Ошибка proofreader: {exc}")
    if issues:
        with st.expander(f"Найдено замечаний: {len(issues)}"):
            for issue in issues[:200]:
                st.markdown(f"* `{issue}`")
    else:
        st.success("Замечаний по грамматике не найдено (или scope пуст).")

related_pages_footer("63_Вики")
