"""Streamlit-страница Resilience Dashboard (S7 K5).

Назначение
----------
Live-матрица состояний resilience-блоков ядра:

* Circuit Breaker (purgatory / aiobreaker) — статус CLOSED/OPEN/HALF_OPEN;
* RateLimiter — текущий tokens / capacity;
* Bulkhead — high/low watermark + queue depth;
* Degradation — активные fallback-chains.

Источник данных
----------------
REST endpoint ``/api/v1/admin/resilience/snapshot`` через ``APIClient``.
Эндпоинт может ещё отсутствовать (S5 К1 будет owner) — UI gracefully
деградирует на mock-snapshot для UX-демонстрации.

Активация
---------
feature_flag ``resilience_dashboard_enabled``.

Auto-refresh: ``@st.fragment(run_every=5)`` — обновление матрицы каждые 5 сек.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Поднимаем корень проекта в sys.path для корректного импорта в Streamlit-режиме.
_project_root = Path(__file__).resolve().parents[4]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import streamlit as st  # noqa: E402

st.set_page_config(
    page_title="Resilience Dashboard",
    page_icon=":shield:",
    layout="wide",
)
st.header("Resilience Dashboard")

# ---------------------------------------------------------------------------
# Feature-flag guard
# ---------------------------------------------------------------------------
try:
    from src.backend.core.config.features import feature_flags as _ff  # noqa: PLC0415

    _flag_enabled: bool = bool(getattr(_ff, "resilience_dashboard_enabled", False))
except Exception:  # noqa: BLE001
    _flag_enabled = False

with st.sidebar:
    st.subheader("Настройки")
    st.toggle(
        "Resilience Dashboard",
        value=_flag_enabled,
        help="feature_flags.resilience_dashboard_enabled (FEATURE_RESILIENCE_DASHBOARD_ENABLED)",
        disabled=True,
    )
    st.caption(
        "Для включения установите `FEATURE_RESILIENCE_DASHBOARD_ENABLED=true` "
        "или обновите `features.yaml`."
    )

if not _flag_enabled:
    st.warning(
        "Resilience Dashboard отключён "
        "(feature_flag: `resilience_dashboard_enabled = false`). "
        "Установите `FEATURE_RESILIENCE_DASHBOARD_ENABLED=true` для активации."
    )
    st.stop()


# ---------------------------------------------------------------------------
# Источник данных: REST endpoint /api/v1/admin/resilience/snapshot
# с graceful fallback на mock-данные.
# ---------------------------------------------------------------------------
def _mock_snapshot() -> dict[str, Any]:
    """Mock-данные resilience snapshot для UX-демонстрации.

    Структура совместима с будущим контрактом
    ``GET /api/v1/admin/resilience/snapshot`` (S5 К1).

    Returns:
        Снапшот по 4 категориям resilience-блоков.
    """
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "circuit_breakers": [
            {"name": "skb_api", "state": "CLOSED", "failures": 0, "last_failure": None},
            {
                "name": "credit_score",
                "state": "HALF_OPEN",
                "failures": 3,
                "last_failure": "2026-05-15T10:21:13Z",
            },
            {
                "name": "audit_clickhouse",
                "state": "OPEN",
                "failures": 17,
                "last_failure": "2026-05-15T10:34:51Z",
            },
        ],
        "rate_limiters": [
            {"name": "public_api", "tokens": 78, "capacity": 100, "rps": 12.4},
            {"name": "rag_search", "tokens": 5, "capacity": 20, "rps": 1.2},
        ],
        "bulkheads": [
            {
                "name": "outbound_http",
                "active": 12,
                "queued": 0,
                "high_watermark": 50,
                "low_watermark": 10,
            },
            {
                "name": "ai_workspace",
                "active": 3,
                "queued": 1,
                "high_watermark": 10,
                "low_watermark": 2,
            },
        ],
        "degradation_chains": [
            {"chain": "credit_score_primary", "active_fallback": None, "tier": 0},
            {
                "chain": "rag_retrieval",
                "active_fallback": "cache_l2",
                "tier": 2,
            },
        ],
    }


def _fetch_snapshot() -> tuple[dict[str, Any], bool]:
    """Получить snapshot resilience через APIClient.

    Returns:
        (snapshot, is_live). is_live=False означает fallback на mock.
    """
    try:
        from src.frontend.streamlit_app.api_client import (  # noqa: PLC0415
            get_api_client,
        )

        _client = get_api_client()
        _data = _client._request(  # noqa: SLF001 — generic REST proxy
            "GET", "/api/v1/admin/resilience/snapshot"
        )
        if isinstance(_data, dict) and _data:
            return _data, True
    except Exception:  # noqa: BLE001, S110 — graceful fallback, endpoint может ещё не существовать
        return _mock_snapshot(), False
    return _mock_snapshot(), False


# ---------------------------------------------------------------------------
# Рендеринг матрицы (через @st.fragment с auto-refresh каждые 5 сек)
# ---------------------------------------------------------------------------
_CB_STATE_COLORS: dict[str, str] = {
    "CLOSED": ":green[CLOSED]",
    "HALF_OPEN": ":orange[HALF_OPEN]",
    "OPEN": ":red[OPEN]",
}


def _render_circuit_breakers(items: list[dict[str, Any]]) -> None:
    """Рендер матрицы Circuit Breaker.

    Args:
        items: список словарей CB-снапшота.
    """
    st.subheader("Circuit Breakers")
    if not items:
        st.caption("Нет зарегистрированных CB.")
        return
    _rows = [
        {
            "name": it.get("name", ""),
            "state": _CB_STATE_COLORS.get(
                str(it.get("state", "")), str(it.get("state", ""))
            ),
            "failures": it.get("failures", 0),
            "last_failure": it.get("last_failure") or "—",
        }
        for it in items
    ]
    st.dataframe(_rows, use_container_width=True, hide_index=True)


def _render_rate_limiters(items: list[dict[str, Any]]) -> None:
    """Рендер RateLimiter-секции.

    Args:
        items: список словарей RL-снапшота.
    """
    st.subheader("Rate Limiters")
    if not items:
        st.caption("Нет активных rate-limiter'ов.")
        return
    _cols = st.columns(max(1, len(items)))
    for _col, _rl in zip(_cols, items, strict=False):
        _tokens = int(_rl.get("tokens", 0))
        _cap = int(_rl.get("capacity", 1)) or 1
        with _col:
            st.metric(
                label=_rl.get("name", ""),
                value=f"{_tokens}/{_cap}",
                delta=f"{_rl.get('rps', 0)} rps",
            )
            st.progress(min(1.0, _tokens / _cap))


def _render_bulkheads(items: list[dict[str, Any]]) -> None:
    """Рендер Bulkhead-секции.

    Args:
        items: список словарей Bulkhead-снапшота.
    """
    st.subheader("Bulkheads")
    if not items:
        st.caption("Нет зарегистрированных bulkhead'ов.")
        return
    _rows = [
        {
            "name": it.get("name", ""),
            "active": it.get("active", 0),
            "queued": it.get("queued", 0),
            "high_watermark": it.get("high_watermark", 0),
            "low_watermark": it.get("low_watermark", 0),
        }
        for it in items
    ]
    st.dataframe(_rows, use_container_width=True, hide_index=True)


def _render_degradation(items: list[dict[str, Any]]) -> None:
    """Рендер degradation chains.

    Args:
        items: список chain-снапшотов.
    """
    st.subheader("Degradation chains")
    if not items:
        st.caption("Нет активных fallback-chains.")
        return
    _rows = [
        {
            "chain": it.get("chain", ""),
            "active_fallback": it.get("active_fallback") or "—",
            "tier": it.get("tier", 0),
        }
        for it in items
    ]
    st.dataframe(_rows, use_container_width=True, hide_index=True)


@st.fragment(run_every=5)  # type: ignore[misc]
def _render_dashboard() -> None:
    """Главный fragment с auto-refresh каждые 5 секунд."""
    _snapshot, _is_live = _fetch_snapshot()

    _col_ts, _col_src = st.columns([3, 1])
    with _col_ts:
        st.caption(f"timestamp: `{_snapshot.get('timestamp', '—')}`")
    with _col_src:
        if _is_live:
            st.success("live")
        else:
            st.info("mock — endpoint не доступен")

    _render_circuit_breakers(list(_snapshot.get("circuit_breakers", [])))
    _render_rate_limiters(list(_snapshot.get("rate_limiters", [])))
    _render_bulkheads(list(_snapshot.get("bulkheads", [])))
    _render_degradation(list(_snapshot.get("degradation_chains", [])))


_render_dashboard()

with st.expander("О странице"):
    st.write(
        "Дашборд использует REST endpoint "
        "`/api/v1/admin/resilience/snapshot` (S5 К1). "
        "При отсутствии endpoint UI показывает mock-данные для UX-демонстрации."
    )
    st.write("Авто-обновление через `@st.fragment(run_every=5)` каждые 5 секунд.")
