# ruff: noqa: S101
"""Integration-тесты для _editor/ helper-модулей (streamlit-зависимые).

S78 W3. Покрывают push_history / undo / redo / sync_yaml через
``_MockSessionState`` — кастомный mock, поддерживающий и dict-style
(``st.session_state["k"] = v``), и attribute-style (``st.session_state.k = v``)
доступ. Реальный streamlit install НЕ требуется.

Pattern: monkeypatch инжектит mock ``streamlit`` модуль в ``sys.modules``
→ lazy ``import streamlit as st`` внутри функций возвращает mock.

Wave: ``[wave:s78/w3-integration-tests-streamlit-helpers]``.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest


class _MockSessionState(dict):
    """Mock streamlit session_state: dict + attribute access.

    Real streamlit's SessionState supports both styles:
    * dict: ``state["key"] = value``, ``state.get("key", default)``
    * attribute: ``state.key = value``, ``state.key += 1``

    We mimic that by subclassing ``dict`` and intercepting __setattr__/__getattr__.
    """

    def __setattr__(self, key: str, value: Any) -> None:  # type: ignore[misc]
        self[key] = value

    def __getattr__(self, key: str) -> Any:
        try:
            return self[key]
        except KeyError as exc:
            raise AttributeError(key) from exc

    def __delattr__(self, key: str) -> None:  # type: ignore[misc]
        try:
            del self[key]
        except KeyError as exc:
            raise AttributeError(key) from exc


def _install_streamlit_mock(
    monkeypatch: pytest.MonkeyPatch, initial_state: dict[str, Any] | None = None
) -> _MockSessionState:
    """Инжектит mock ``streamlit`` модуль в ``sys.modules``.

    Returns session_state (для assertions). ``st.rerun()`` — MagicMock.
    """
    state = _MockSessionState(initial_state or {})
    mock_st = types.ModuleType("streamlit")
    mock_st.session_state = state  # type: ignore[attr-defined]
    # rerun — track via list (MagicMock creates attribute on access).
    mock_st.rerun_calls: list[None] = []  # type: ignore[attr-defined, misc]

    def _rerun() -> None:
        mock_st.rerun_calls.append(None)  # type: ignore[attr-defined]

    mock_st.rerun = _rerun  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "streamlit", mock_st)
    return state


def _rerun_call_count() -> int:
    """Returns number of times ``st.rerun()`` was called since mock install."""
    return len(sys.modules["streamlit"].rerun_calls)  # type: ignore[attr-defined]


# ──────────────────────────── history.py ────────────────────────────


def test_init_history_creates_initial_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """init_history() → yaml_history=[current_yaml], yaml_history_index=0."""
    state = _install_streamlit_mock(
        monkeypatch, {"yaml": "route_id: x\nprocessors: []\n"}
    )

    from src.frontend.streamlit_app.pages._editor.history import init_history

    init_history()

    assert state["yaml_history"] == ["route_id: x\nprocessors: []\n"]
    assert state["yaml_history_index"] == 0


def test_init_history_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Повторный init_history() — no-op, не перезаписывает history."""
    state = _install_streamlit_mock(
        monkeypatch,
        {"yaml": "v1", "yaml_history": ["preexisting"], "yaml_history_index": 0},
    )

    from src.frontend.streamlit_app.pages._editor.history import init_history

    init_history()

    # State не изменился.
    assert state["yaml_history"] == ["preexisting"]
    assert state["yaml_history_index"] == 0


def test_push_history_appends_current_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """push_history() добавляет текущий yaml в стек + обновляет cursor."""
    state = _install_streamlit_mock(
        monkeypatch, {"yaml": "v2", "yaml_history": ["v1"], "yaml_history_index": 0}
    )

    from src.frontend.streamlit_app.pages._editor.history import push_history

    push_history()

    assert state["yaml_history"] == ["v1", "v2"]
    assert state["yaml_history_index"] == 1


def test_push_history_truncates_forward_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Если cursor не на вершине — forward history truncated при push."""
    state = _install_streamlit_mock(
        monkeypatch,
        {
            "yaml": "v3",
            "yaml_history": ["v1", "v2", "v3", "v4"],
            "yaml_history_index": 1,  # cursor на v2
        },
    )

    from src.frontend.streamlit_app.pages._editor.history import push_history

    push_history()

    # Forward history (v3, v4) truncated → stack = [v1, v2, current(v3)]
    assert state["yaml_history"] == ["v1", "v2", "v3"]
    assert state["yaml_history_index"] == 2


def test_push_history_trims_to_max_50(monkeypatch: pytest.MonkeyPatch) -> None:
    """При >50 states oldest удаляется (FIFO)."""
    state = _install_streamlit_mock(
        monkeypatch,
        {
            "yaml": "v51",
            "yaml_history": [f"v{i}" for i in range(50)],
            "yaml_history_index": 49,  # cursor на вершине
        },
    )

    from src.frontend.streamlit_app.pages._editor.history import push_history

    push_history()

    # Stack trimmed: oldest (v0) dropped, 50 items remain.
    assert len(state["yaml_history"]) == 50
    assert state["yaml_history"][0] == "v1"  # v0 dropped
    assert state["yaml_history"][-1] == "v51"  # newest at end
    assert state["yaml_history_index"] == 49


def test_can_undo_redo_initial_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fresh state (no history) → can_undo=False, can_redo=False."""
    _install_streamlit_mock(monkeypatch, {"yaml": "v1"})

    from src.frontend.streamlit_app.pages._editor.history import can_redo, can_undo

    assert can_undo() is False
    assert can_redo() is False


def test_undo_redo_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    """3 pushes → 2 undos → 1 redo: cursor + rerun() корректны."""
    state = _install_streamlit_mock(
        monkeypatch,
        {"yaml": "v3", "yaml_history": ["v1", "v2", "v3"], "yaml_history_index": 2},
    )

    from src.frontend.streamlit_app.pages._editor.history import (  # noqa: E402
        can_redo,
        can_undo,
        redo,
        undo,
    )

    # На вершине: undo possible, redo нет.
    assert can_undo() is True
    assert can_redo() is False
    assert _rerun_call_count() == 0

    # Undo #1: cursor на v2.
    undo()
    assert state["yaml_history_index"] == 1
    assert state["yaml"] == "v2"
    assert _rerun_call_count() == 1

    # Undo #2: cursor на v1.
    undo()
    assert state["yaml_history_index"] == 0
    assert state["yaml"] == "v1"
    assert _rerun_call_count() == 2

    # Undo #3: nothing to undo, no rerun.
    undo()
    assert state["yaml_history_index"] == 0
    assert _rerun_call_count() == 2

    # Redo #1: cursor на v2.
    assert can_redo() is True
    redo()
    assert state["yaml_history_index"] == 1
    assert state["yaml"] == "v2"
    assert _rerun_call_count() == 3


# ──────────────────────────── yaml_sync.py ────────────────────────────


def test_sync_yaml_serializes_canvas_to_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """sync_yaml() → yaml_output = build_yaml_from_steps(canvas_steps, meta)."""
    state = _install_streamlit_mock(
        monkeypatch,
        {
            "canvas_steps": [{"type": "log", "params": {"level": "info"}}],
            "meta_route": {"route_id": "test.route", "source": "internal:test"},
        },
    )

    from src.frontend.streamlit_app.pages._editor.yaml_sync import sync_yaml

    sync_yaml()

    assert "route_id: test.route" in state["yaml_output"]
    assert "source: internal:test" in state["yaml_output"]
    assert "log:" in state["yaml_output"]
    assert "level: info" in state["yaml_output"]


def test_sync_yaml_uses_build_yaml_from_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    """sync_yaml() output === build_yaml_from_steps(meta, steps) (no transformation)."""
    meta = {"route_id": "x", "source": "y"}
    steps = [{"type": "validate", "params": {}}]
    state = _install_streamlit_mock(
        monkeypatch, {"canvas_steps": steps, "meta_route": meta}
    )

    from src.frontend.streamlit_app.pages._editor.yaml_sync import (  # noqa: E402
        build_yaml_from_steps,
        sync_yaml,
    )

    sync_yaml()
    expected = build_yaml_from_steps(meta, steps)
    assert state["yaml_output"] == expected
