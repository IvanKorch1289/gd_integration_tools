"""Blueprint Gallery — каталог DSL blueprints (R2/R2.5).

Компактный UI: 3-column grid карточек blueprint из
``src/backend/dsl/blueprints/`` (YAML + Python templates), фильтры
по тегам/типу/сложности, поиск, preview YAML, copy, mock-deploy.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

from src.frontend.streamlit_app.shared.components import dataframe_view, setup_page

setup_page()
st.header(":art: Галерея blueprint'ов")
st.caption(
    "Каталог шаблонов маршрутов R2/R2.5 — 3-column grid, фильтры, preview, copy."
)

BLUEPRINTS_DIR = Path("src/backend/dsl/blueprints")

# Python template-blueprints metadata (R2.5) — дополняет YAML-каталог до 23.
PYTHON_BP: dict[str, dict[str, Any]] = {
    "api_normalize_persist_webhook": {
        "v": "2.5.0",
        "kind": "python",
        "cx": "low",
        "d": "REST ingestion → normalize → persist (action) → webhook notify.",
        "t": ["python", "api", "normalize", "webhook"],
        "p": ["route_id", "source_url", "persist_action", "webhook_url"],
    },
    "cdc_enrich_publish": {
        "v": "2.5.0",
        "kind": "python",
        "cx": "medium",
        "d": "CDC source → HTTP-enrichment → publish в MQ/Sink через action.",
        "t": ["python", "cdc", "enrich", "messaging"],
        "p": ["route_id", "cdc_source", "enrichment_url", "publish_action"],
    },
    "file_watch_parse_validate_action": {
        "v": "2.5.0",
        "kind": "python",
        "cx": "low",
        "d": "File watcher → normalize (Pydantic) → validate → dispatch action.",
        "t": ["python", "file", "validation", "rpa"],
        "p": ["route_id", "watch_path", "file_glob", "action"],
    },
    "request_response_with_compensation": {
        "v": "2.5.0",
        "kind": "python",
        "cx": "high",
        "d": "HTTP request с retry → Saga main/compensate для отката side-effects.",
        "t": ["python", "saga", "compensation", "http"],
        "p": ["route_id", "request_url", "compensate_url", "max_retries"],
    },
}

CX_ICON = {"low": "🟢", "medium": "🟡", "high": "🔴"}


def _estimate_cx(steps: int) -> str:
    return "low" if steps <= 3 else "medium" if steps <= 6 else "high"


@st.cache_data(ttl=60)
def _load_yaml() -> list[dict[str, Any]]:
    """Загрузить YAML blueprints напрямую из каталога."""
    try:
        import yaml
    except ImportError:
        st.error("PyYAML не установлен — невозможно загрузить blueprints.")
        return []

    if not BLUEPRINTS_DIR.is_dir():
        st.error(f"Каталог не найден: {BLUEPRINTS_DIR.absolute()}")
        return []

    items: list[dict[str, Any]] = []
    for path in sorted(BLUEPRINTS_DIR.glob("*.yaml")):
        try:
            with path.open(encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
        except Exception as exc:  # noqa: BLE001
            st.warning(f"Не удалось загрузить {path.name}: {exc}")
            continue
        if not raw.get("blueprint"):
            continue
        steps = raw.get("steps") or []
        items.append(
            {
                "name": raw["blueprint"],
                "version": str(raw.get("version", "1.0.0")),
                "description": str(raw.get("description", "")),
                "tags": list(raw.get("tags") or []),
                "params": [p.get("name", "") for p in raw.get("params") or []],
                "complexity": _estimate_cx(len(steps)),
                "kind": "yaml",
                "raw": {
                    "from": raw.get("from") or {},
                    "steps": steps,
                    "to": raw.get("to") or {},
                },
            }
        )
    return items


def _load_python() -> list[dict[str, Any]]:
    """Преобразовать PYTHON_BP metadata в формат карточек."""
    return [
        {
            "name": n,
            "version": m["v"],
            "description": m["d"],
            "tags": m["t"],
            "params": m["p"],
            "complexity": m["cx"],
            "kind": m["kind"],
            "raw": {},
        }
        for n, m in PYTHON_BP.items()
    ]


def _yaml_preview(bp: dict[str, Any]) -> str:
    """Полный YAML blueprint для preview/download."""
    try:
        import yaml

        return yaml.safe_dump(
            {
                "blueprint": bp["name"],
                "version": bp["version"],
                "description": bp["description"],
                "tags": bp["tags"],
                "params": [{"name": p} for p in bp["params"]],
                **bp.get("raw", {}),
            },
            allow_unicode=True,
            sort_keys=False,
        )
    except Exception:  # noqa: BLE001
        return f"# {bp['name']}\n# Preview недоступен (требуется PyYAML)"


def _card(bp: dict[str, Any]) -> None:
    """Отрисовать одну карточку blueprint."""
    icon = CX_ICON.get(bp["complexity"], "⚪")
    with st.container(border=True):
        st.markdown(f"{icon} **{bp['name']}** `v{bp['version']}`")
        st.caption(bp["description"] or "_нет описания_")
        if bp["tags"]:
            st.markdown(" ".join(f"`{t}`" for t in bp["tags"]))
        st.caption(
            f"`{bp['kind']}` · `{bp['complexity']}` · параметров: {len(bp['params'])}"
        )

        yaml_text = _yaml_preview(bp)
        c1, c2, c3 = st.columns(3)
        with c1:
            with st.popover("👁 Предпросмотр"):
                st.code(yaml_text, language="yaml")
        with c2:
            st.download_button(
                "📋 Скопировать",
                data=yaml_text,
                file_name=f"{bp['name']}.yaml",
                mime="text/yaml",
                key=f"cp_{bp['name']}",
                width='stretch',
            )
        with c3:
            if st.button("🚀 Задеплоить", key=f"dp_{bp['name']}", width='stretch'):
                st.toast(
                    f"Mock-деплой '{bp['name']}' v{bp['version']} — реальный деплой через backend WIP",
                    icon="🚀",
                )

        if bp["params"]:
            with st.expander(f"Параметры ({len(bp['params'])})"):
                st.code("\n".join(f"- {p}" for p in bp["params"]))


# ─────────── Data ───────────

yaml_bps = _load_yaml()
all_blueprints = yaml_bps + _load_python()

if not all_blueprints:
    st.info("Нет доступных blueprints.")
    st.stop()

st.caption(
    f"Всего: **{len(all_blueprints)}** (YAML: {len(yaml_bps)}, Python: {len(PYTHON_BP)})"
)

# ─────────── Filters ───────────

with st.sidebar:
    st.subheader("Фильтры")
    all_tags = sorted({t for bp in all_blueprints for t in bp["tags"]})
    sel_tags = st.multiselect("Теги", all_tags, key="bp_tags")
    sel_kind = st.multiselect(
        "Тип", ["yaml", "python"], default=["yaml", "python"], key="bp_kind"
    )
    sel_cx = st.multiselect("Сложность", ["low", "medium", "high"], key="bp_cx")

q = (
    st.text_input("🔍 Поиск", placeholder="Название или описание...", key="bp_q")
    .strip()
    .lower()
)

# ─────────── Apply filters ───────────

flt = all_blueprints
if q:
    flt = [b for b in flt if q in b["name"].lower() or q in b["description"].lower()]
if sel_tags:
    flt = [b for b in flt if any(t in b["tags"] for t in sel_tags)]
if sel_kind:
    flt = [b for b in flt if b["kind"] in sel_kind]
if sel_cx:
    flt = [b for b in flt if b["complexity"] in sel_cx]

st.caption(f"Показано **{len(flt)}** из **{len(all_blueprints)}**.")
if not flt:
    st.warning("Ничего не найдено — измените фильтры.")
    st.stop()

# ─────────── 3-column grid ───────────

for i in range(0, len(flt), 3):
    cols = st.columns(3, gap="small")
    for col, bp in zip(cols, flt[i : i + 3], strict=False):
        with col:
            _card(bp)

# ─────────── Summary table ───────────

st.divider()
st.subheader("📚 Все blueprint'ы")
rows = [
    {
        "Имя": b["name"],
        "Версия": b["version"],
        "Тип": b["kind"],
        "Сложность": CX_ICON.get(b["complexity"], "⚪") + " " + b["complexity"],
        "Теги": ", ".join(b["tags"]),
        "Параметров": len(b["params"]),
    }
    for b in all_blueprints
]
dataframe_view(rows, hide_index=True)
