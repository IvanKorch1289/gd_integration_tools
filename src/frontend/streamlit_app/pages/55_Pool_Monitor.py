"""Streamlit-страница Pool Monitor (S7 K5).

Назначение
----------
Live-мониторинг worker pool (Granian) + connection pool (PG / Redis / HTTP /
Kafka / ClickHouse) через REST endpoint ``/api/v1/admin/pools/snapshot``.

Структура:

* **Worker pool (Granian)** — динамическая фабрика воркеров; in_use, available,
  max_workers, last_fork_at;
* **Connection pools** — на каждый backend: in_use / available / max +
  trend-линия (rolling 60 точек, 1 точка / sec).

Активация: feature_flag ``pool_monitor_enabled``.
Auto-refresh: ``@st.fragment(run_every=5)``.
"""

from __future__ import annotations

import sys
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Поднимаем корень проекта в sys.path для корректного импорта в Streamlit-режиме.
_project_root = Path(__file__).resolve().parents[4]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import streamlit as st  # noqa: E402

st.set_page_config(page_title="Pool Monitor", page_icon=":swimmer:", layout="wide")
st.header("Pool Monitor")

# ---------------------------------------------------------------------------
# Feature-flag guard
# ---------------------------------------------------------------------------
try:
    from src.backend.core.config.features import feature_flags as _ff  # noqa: PLC0415

    _flag_enabled: bool = bool(getattr(_ff, "pool_monitor_enabled", False))
except Exception:  # noqa: BLE001
    _flag_enabled = False

with st.sidebar:
    st.subheader("Настройки")
    st.toggle(
        "Pool Monitor",
        value=_flag_enabled,
        help="feature_flags.pool_monitor_enabled (FEATURE_POOL_MONITOR_ENABLED)",
        disabled=True,
    )
    st.caption(
        "Для включения установите `FEATURE_POOL_MONITOR_ENABLED=true` "
        "или обновите `features.yaml`."
    )

if not _flag_enabled:
    st.warning(
        "Pool Monitor отключён (feature_flag: `pool_monitor_enabled = false`). "
        "Установите `FEATURE_POOL_MONITOR_ENABLED=true` для активации."
    )
    st.stop()


# ---------------------------------------------------------------------------
# Источник данных
# ---------------------------------------------------------------------------
def _mock_pools_snapshot() -> dict[str, Any]:
    """Mock-снапшот pools для UX-демонстрации.

    Структура совместима с будущим контрактом
    ``GET /api/v1/admin/pools/snapshot`` (S5 К1 / K5 Ops).

    Returns:
        Снапшот worker + connection pools.
    """
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "worker_pool": {
            "name": "granian",
            "in_use": 6,
            "available": 2,
            "max_workers": 8,
            "last_fork_at": "2026-05-15T10:33:47Z",
        },
        "connection_pools": [
            {
                "name": "postgres_primary",
                "kind": "postgres",
                "in_use": 5,
                "available": 15,
                "max": 20,
            },
            {
                "name": "redis_cache",
                "kind": "redis",
                "in_use": 12,
                "available": 38,
                "max": 50,
            },
            {
                "name": "http_outbound",
                "kind": "httpx",
                "in_use": 4,
                "available": 96,
                "max": 100,
            },
            {
                "name": "kafka_producer",
                "kind": "kafka",
                "in_use": 1,
                "available": 9,
                "max": 10,
            },
            {
                "name": "clickhouse_audit",
                "kind": "clickhouse",
                "in_use": 2,
                "available": 8,
                "max": 10,
            },
        ],
    }


def _fetch_snapshot() -> tuple[dict[str, Any], bool]:
    """Fetch snapshot pools через APIClient.

    Returns:
        (snapshot, is_live). is_live=False — fallback на mock.
    """
    try:
        from src.frontend.streamlit_app.api_client import (  # noqa: PLC0415
            get_api_client,
        )

        _client = get_api_client()
        _data = _client._request(  # noqa: SLF001 — generic REST proxy
            "GET", "/api/v1/admin/pools/snapshot"
        )
        if isinstance(_data, dict) and _data:
            return _data, True
    except Exception:  # noqa: BLE001, S110 — endpoint может ещё не существовать
        return _mock_pools_snapshot(), False
    return _mock_pools_snapshot(), False


# ---------------------------------------------------------------------------
# Хранилище trend-линий (60 последних точек на каждый pool)
# ---------------------------------------------------------------------------
_TREND_WINDOW = 60


def _push_trend(pool_name: str, in_use: int) -> list[int]:
    """Добавить точку в trend-окно конкретного pool.

    Использует ``st.session_state`` для персистентности между rerun.

    Args:
        pool_name: имя pool (ключ для session_state).
        in_use: текущее значение in_use.

    Returns:
        Список последних N точек (где N = _TREND_WINDOW).
    """
    _key = f"pool_trend_{pool_name}"
    _trend = st.session_state.get(_key)
    if not isinstance(_trend, deque):
        _trend = deque(maxlen=_TREND_WINDOW)
        st.session_state[_key] = _trend
    _trend.append(int(in_use))
    return list(_trend)


# ---------------------------------------------------------------------------
# Рендеринг
# ---------------------------------------------------------------------------
def _render_worker_pool(wp: dict[str, Any]) -> None:
    """Рендер блока worker pool (Granian).

    Args:
        wp: словарь снапшота worker pool.
    """
    st.subheader("Worker pool (Granian)")
    _in_use = int(wp.get("in_use", 0))
    _available = int(wp.get("available", 0))
    _maximum = int(wp.get("max_workers", _in_use + _available)) or 1

    _c1, _c2, _c3 = st.columns(3)
    _c1.metric("in_use", _in_use)
    _c2.metric("available", _available)
    _c3.metric("max_workers", _maximum)

    st.progress(min(1.0, _in_use / _maximum))
    if _last := wp.get("last_fork_at"):
        st.caption(f"Последний fork: `{_last}`")


def _render_connection_pools(pools: list[dict[str, Any]]) -> None:
    """Рендер connection pools с trend-линиями.

    Args:
        pools: список словарей connection pool снапшотов.
    """
    st.subheader("Connection pools")
    if not pools:
        st.caption("Нет зарегистрированных connection pool'ов.")
        return

    for _pool in pools:
        _name = str(_pool.get("name", ""))
        _kind = str(_pool.get("kind", ""))
        _in_use = int(_pool.get("in_use", 0))
        _avail = int(_pool.get("available", 0))
        _maximum = int(_pool.get("max", _in_use + _avail)) or 1
        _trend = _push_trend(_name, _in_use)

        with st.container(border=True):
            _c_title, _c_in_use, _c_avail, _c_max = st.columns([2, 1, 1, 1])
            _c_title.markdown(f"**{_name}** `{_kind}`")
            _c_in_use.metric("in_use", _in_use)
            _c_avail.metric("available", _avail)
            _c_max.metric("max", _maximum)
            st.progress(min(1.0, _in_use / _maximum))
            if len(_trend) >= 2:
                st.line_chart(_trend, height=120)


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

    _wp = _snapshot.get("worker_pool") or {}
    if isinstance(_wp, dict) and _wp:
        _render_worker_pool(_wp)

    _render_connection_pools(list(_snapshot.get("connection_pools", [])))


_render_dashboard()

with st.expander("О странице"):
    st.write(
        "Pool Monitor читает REST endpoint `/api/v1/admin/pools/snapshot`. "
        "Trend-линии (60 точек, 1 точка / 5 сек) хранятся в `st.session_state` "
        "и сбрасываются между сессиями браузера."
    )
