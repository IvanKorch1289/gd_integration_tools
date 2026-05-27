"""Per-tenant Feature Flag overrides (Sprint 17 K5 W1 / D9).

UI для multi-replica runtime управления feature-flag overrides:

* Просмотр текущих global + per-tenant overrides;
* Установка boolean / string / int override для конкретного tenant_id;
* Очистка override (возврат к static-default);
* Snapshot обновляется после каждого действия (Redis pub/sub
  гарантирует propagation между репликами <100ms — DoD #11).

Зависит от:
* REST endpoints ``GET/PUT/DELETE /api/v1/admin/feature-flags``.
* Feature-flag ``tenant_feature_flag_ui`` (default-OFF в backbone S17 для
  Redis broadcaster; UI работает в single-replica режиме всегда).
"""

from __future__ import annotations

import sys
from typing import Any

import streamlit as st


from src.frontend.streamlit_app.api_client import get_api_client

st.set_page_config(
    page_title="Tenant Feature Flags",
    page_icon=":busts_in_silhouette:",
    layout="wide",
)
st.header("Tenant Feature Flags (per-tenant overrides)")
st.caption(
    "Runtime overrides поверх статического реестра feature-flag. "
    "Per-tenant override побеждает global override; global побеждает default. "
    "Изменения распространяются между репликами через Redis pub/sub "
    "(``tenant_feature_flag_ui=True``) с латентностью &lt;100ms."
)

client = get_api_client()


def _render_snapshot(snapshot: dict[str, Any]) -> None:
    """Двухколоночный snapshot: global + per_tenant."""
    col_global, col_tenant = st.columns(2)
    with col_global:
        st.subheader("Global overrides")
        global_overrides = snapshot.get("global", {})
        if not global_overrides:
            st.info("Нет global runtime-overrides — все flag'и берутся из default.")
        else:
            st.json(global_overrides, expanded=True)

    with col_tenant:
        st.subheader("Per-tenant overrides")
        per_tenant = snapshot.get("per_tenant", {})
        if not per_tenant:
            st.info("Нет per-tenant overrides.")
        else:
            for tid, flags in per_tenant.items():
                with st.expander(f"tenant_id={tid!r} ({len(flags)} flag(s))"):
                    st.json(flags, expanded=True)


def _coerce_value(raw: str, kind: str) -> Any:
    """Преобразовать строку из формы в нужный тип Python."""
    raw = raw.strip()
    if kind == "boolean":
        return raw.lower() in ("true", "1", "yes", "on")
    if kind == "integer":
        try:
            return int(raw)
        except ValueError:
            st.warning(f"Не удалось преобразовать {raw!r} в integer — взят 0.")
            return 0
    if kind == "json":
        import orjson

        try:
            return orjson.loads(raw)
        except orjson.JSONDecodeError as exc:
            st.error(f"Невалидный JSON: {exc}")
            return None
    return raw


# ─── Snapshot ────────────────────────────────────────────────────────
snapshot = client.list_overrides()
_render_snapshot(snapshot)

st.divider()

# ─── Set override ────────────────────────────────────────────────────
st.subheader("Установить override")
with st.form("set_override_form", clear_on_submit=False):
    flag_name = st.text_input("flag", value="", placeholder="например, metrics_registry_strict")
    tenant_input = st.text_input(
        "tenant_id (пусто = global override)", value=""
    )
    kind = st.selectbox(
        "Тип значения", options=["boolean", "string", "integer", "json"]
    )
    value_raw = st.text_input("value", value="true")
    actor = st.text_input("actor (для audit)", value="ui")
    submitted = st.form_submit_button("Установить")

    if submitted:
        if not flag_name.strip():
            st.error("flag не может быть пустым.")
        else:
            tid = tenant_input.strip() or None
            value = _coerce_value(value_raw, kind)
            if value is None and kind == "json":
                pass  # already shown error
            else:
                result = client.set_override(
                    flag_name.strip(), value, tenant_id=tid, actor=actor.strip() or "ui"
                )
                if result is not None:
                    st.success(
                        f"Override установлен: flag={result.get('flag')} "
                        f"tenant_id={result.get('tenant_id')} "
                        f"old={result.get('old_value')!r} → "
                        f"new={result.get('new_value')!r}"
                    )
                    st.rerun()
                else:
                    st.error("Не удалось установить override — backend недоступен.")

st.divider()

# ─── Clear override ──────────────────────────────────────────────────
st.subheader("Снять override")
with st.form("clear_override_form", clear_on_submit=False):
    clear_flag = st.text_input("flag", value="", key="clear_flag")
    clear_tenant = st.text_input(
        "tenant_id (пусто = global)", value="", key="clear_tenant"
    )
    clear_actor = st.text_input("actor", value="ui", key="clear_actor")
    clear_submitted = st.form_submit_button("Снять")

    if clear_submitted:
        if not clear_flag.strip():
            st.error("flag не может быть пустым.")
        else:
            tid = clear_tenant.strip() or None
            result = client.clear_override(
                clear_flag.strip(), tenant_id=tid, actor=clear_actor.strip() or "ui"
            )
            if result is not None:
                st.success(
                    f"Override снят: flag={result.get('flag')} "
                    f"tenant_id={result.get('tenant_id')} "
                    f"old={result.get('old_value')!r}"
                )
                st.rerun()
            else:
                st.warning(
                    "Override не найден (404) или backend недоступен."
                )
