"""Тесты E2BExecutionBackend (T3 ratchet: e2b_backend.py 32%→≥90%).

e2b_code_interpreter и nbformat инжектируются через sys.modules;
_execute_sync вызывается напрямую (минуя asyncio.to_thread) для
детерминизма. Покрытие: api_key, _inject_parameters, _convert_results,
execute_with_params (missing key/file), sandbox lifecycle + kill,
params-фаза, error-сбор + nbformat.write мок.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import nbformat
import pytest

from src.backend.services.jupyter.execution_service.e2b_backend import (
    E2BExecutionBackend,
    E2BExecutionError,
)

FAKE_CI = "e2b_code_interpreter"


@pytest.fixture
def no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("E2B_API_KEY", raising=False)


def test_api_key_configured_from_ctor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("E2B_API_KEY", raising=False)
    assert E2BExecutionBackend().api_key_configured is False
    assert E2BExecutionBackend(api_key="k1").api_key_configured is True


def test_inject_parameters_appends_repr_lines() -> None:
    backend = E2BExecutionBackend(api_key="k")
    result = backend._inject_parameters("x = 0", {"customer_id": 42, "name": "op"})
    assert result.startswith("x = 0")
    assert "customer_id = 42" in result
    assert "name = 'op'" in result
    assert "# S75 W1: injected parameters" in result


def test_inject_parameters_empty_params() -> None:
    backend = E2BExecutionBackend(api_key="k")
    assert "# S75 W1: injected parameters" in backend._inject_parameters("src", {})


def test_convert_results_text_wrapped() -> None:
    backend = E2BExecutionBackend(api_key="k")
    first = SimpleNamespace(text="42")
    assert backend._convert_results([first]) == [
        {
            "output_type": "execute_result",
            "execution_count": None,
            "data": {"text/plain": "42"},
            "metadata": {},
        }
    ]


def test_convert_results_empty_list() -> None:
    backend = E2BExecutionBackend(api_key="k")
    assert backend._convert_results([]) == []


@pytest.mark.asyncio
async def test_execute_missing_api_key_raises(no_api_key: None) -> None:
    with pytest.raises(E2BExecutionError, match="E2B_API_KEY not set"):
        await E2BExecutionBackend().execute_with_params("nb.ipynb", {})


@pytest.mark.asyncio
async def test_execute_missing_notebook_raises(no_api_key: None) -> None:
    backend = E2BExecutionBackend(api_key="k")
    with pytest.raises(FileNotFoundError, match="no_such.ipynb"):
        await backend.execute_with_params("/tmp/no_such.ipynb", {})


def _mock_sandbox_and_ci() -> tuple[MagicMock, MagicMock]:
    sb = MagicMock()
    sb.run_code = MagicMock(return_value=SimpleNamespace(error=None, results=[]))
    sb.get_info = MagicMock(return_value=SimpleNamespace(sandbox_id="sbx-123"))
    sb.kill = MagicMock()
    fake_ci = MagicMock()
    fake_ci.Sandbox.create = MagicMock(return_value=sb)
    return sb, fake_ci


def _write_notebook(path: str, *, params_tags: bool) -> None:
    nb = nbformat.v4.new_notebook()
    code_cell = nbformat.v4.new_code_cell(source="result = compute()")
    if params_tags:
        code_cell.metadata["tags"] = ["parameters"]
    nb.cells = [nbformat.v4.new_code_cell("import os"), code_cell]
    nbformat.write(nb, path)


@pytest.mark.asyncio
async def test_execute_sync_sandbox_lifecycle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
) -> None:
    """params-фаза -> code-фаза -> kill; sandbox_id и errors собираются."""
    ok_execution = SimpleNamespace(
        error=None, results=[], logs=SimpleNamespace(stdout=[])
    )
    sb = MagicMock()
    sb.run_code = MagicMock(return_value=ok_execution)
    sb.get_info = MagicMock(return_value=SimpleNamespace(sandbox_id="sbx-123"))
    sb.kill = MagicMock()
    fake_ci = MagicMock()
    fake_ci.Sandbox.create = MagicMock(return_value=sb)
    monkeypatch.setitem(sys.modules, FAKE_CI, fake_ci)

    nb_path = str(tmp_path / "nb.ipynb")
    _write_notebook(nb_path, params_tags=False)

    backend = E2BExecutionBackend(api_key="k")
    # nbformat.write валидирует notebook — dict-outputs от мока не проходят;
    # мокаем write, чтобы проверить контракт _execute_sync без nbformat-шума
    with patch.object(nbformat, "write"):
        result = await backend.execute_with_params(nb_path, {"date": "d1"})

    assert result["sandbox_id"] == "sbx-123"
    assert result["cells_executed"] == 2
    assert result["errors"] == []
    sb.run_code.assert_any_call("import os")
    sb.run_code.assert_any_call("result = compute()")
    sb.kill.assert_called_once()


@pytest.mark.asyncio
async def test_execute_sync_run_code_error_collected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
) -> None:
    """Ошибка run_code -> errors[], не исключение; kill всё равно вызван."""
    nb_path = str(tmp_path / "nb.ipynb")
    _write_notebook(nb_path, params_tags=False)

    error_execution = SimpleNamespace(
        error=SimpleNamespace(name="ZeroDivisionError", value="div"),
        results=[],
        logs=SimpleNamespace(stdout=[]),
    )
    sb = MagicMock()
    sb.run_code = MagicMock(return_value=error_execution)
    sb.kill = MagicMock()
    fake_ci = MagicMock()
    fake_ci.Sandbox.create = MagicMock(return_value=sb)
    monkeypatch.setitem(sys.modules, FAKE_CI, fake_ci)

    backend = E2BExecutionBackend(api_key="k")
    with patch.object(nbformat, "write"):
        result = await backend.execute_with_params(nb_path, {})

    assert result["cells_executed"] == 2
    assert len(result["errors"]) == 2
    assert all("ZeroDivisionError" in e for e in result["errors"])
    sb.kill.assert_called_once()


# ── Ratchet: error-ветки импортов, wrap, params-фаза, kill-failure ──


@pytest.mark.asyncio
async def test_execute_nbformat_missing_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
) -> None:
    """nbformat отсутствует -> E2BExecutionError 'nbformat required'."""
    nb_path = str(tmp_path / "nb.ipynb")
    _write_notebook(nb_path, params_tags=False)
    monkeypatch.setitem(sys.modules, "nbformat", None)

    backend = E2BExecutionBackend(api_key="k")
    with pytest.raises(E2BExecutionError, match="nbformat required"):
        await backend.execute_with_params(nb_path, {})


def test_execute_sync_e2b_dep_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """e2b_code_interpreter отсутствует -> E2BExecutionError (lazy-import)."""
    monkeypatch.setitem(sys.modules, FAKE_CI, None)
    backend = E2BExecutionBackend(api_key="k")
    with pytest.raises(E2BExecutionError, match="e2b_code_interpreter required"):
        backend._execute_sync(object(), [], [], {})


def test_execute_sync_sandbox_create_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sandbox.create падает -> E2BExecutionError 'sandbox creation failed'."""
    fake_ci = MagicMock()
    fake_ci.Sandbox.create = MagicMock(side_effect=RuntimeError("quota exceeded"))
    monkeypatch.setitem(sys.modules, FAKE_CI, fake_ci)

    backend = E2BExecutionBackend(api_key="k")
    with pytest.raises(E2BExecutionError, match="sandbox creation failed"):
        backend._execute_sync(object(), [], [], {})


@pytest.mark.asyncio
async def test_execute_sandbox_create_failure_reraised(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
) -> None:
    """E2BExecutionError из _execute_sync пробрасывается как есть (line 187)."""
    nb_path = str(tmp_path / "nb.ipynb")
    _write_notebook(nb_path, params_tags=False)

    fake_ci = MagicMock()
    fake_ci.Sandbox.create = MagicMock(side_effect=RuntimeError("quota exceeded"))
    monkeypatch.setitem(sys.modules, FAKE_CI, fake_ci)

    backend = E2BExecutionBackend(api_key="k")
    with pytest.raises(E2BExecutionError, match="sandbox creation failed"):
        await backend.execute_with_params(nb_path, {})


@pytest.mark.asyncio
async def test_execute_wraps_unexpected_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
) -> None:
    """Не-E2B исключение из _execute_sync -> обёртка 'E2B execution failed'."""
    nb_path = str(tmp_path / "nb.ipynb")
    _write_notebook(nb_path, params_tags=False)

    backend = E2BExecutionBackend(api_key="k")
    with patch.object(backend, "_execute_sync", side_effect=ValueError("boom")):
        with pytest.raises(E2BExecutionError, match="E2B execution failed"):
            await backend.execute_with_params(nb_path, {})


@pytest.mark.asyncio
async def test_execute_params_phase_results_and_kill_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
) -> None:
    """params-ячейка с ошибкой, results-конверсия, logs=None, kill-failure."""
    nb = nbformat.v4.new_notebook()
    params_cell = nbformat.v4.new_code_cell(source="date = 'x'")
    params_cell.metadata["tags"] = ["parameters"]
    code_with_results = nbformat.v4.new_code_cell(source="compute()")
    code_silent = nbformat.v4.new_code_cell(source="silent()")
    nb.cells = [params_cell, code_with_results, code_silent]
    nb_path = str(tmp_path / "nb.ipynb")
    nbformat.write(nb, nb_path)

    err_exec = SimpleNamespace(
        error=SimpleNamespace(name="TypeError", value="bad"),
        results=[],
        logs=SimpleNamespace(stdout=[]),
    )
    ok_exec = SimpleNamespace(error=None, results=[], logs=SimpleNamespace(stdout=[]))
    results_exec = SimpleNamespace(
        error=None,
        results=[SimpleNamespace(text="42")],
        logs=SimpleNamespace(stdout=["42"]),
    )
    silent_exec = SimpleNamespace(error=None, results=[], logs=None)
    sb = MagicMock()
    # 2-я params-ячейка без ошибки (ветка 253->258) + code-ячейки
    second_params = nbformat.v4.new_code_cell(source="limit = 10")
    second_params.metadata["tags"] = ["parameters"]
    nb.cells.insert(1, second_params)
    sb.run_code = MagicMock(side_effect=[err_exec, ok_exec, results_exec, silent_exec])
    sb.get_info = MagicMock(return_value=SimpleNamespace(sandbox_id="sbx-9"))
    sb.kill = MagicMock(side_effect=RuntimeError("kill failed"))
    fake_ci = MagicMock()
    fake_ci.Sandbox.create = MagicMock(return_value=sb)
    monkeypatch.setitem(sys.modules, FAKE_CI, fake_ci)

    out_path = str(tmp_path / "custom_out.ipynb")
    backend = E2BExecutionBackend(api_key="k")
    # read мокаем на in-memory nb: мутации cell.outputs идут в наш объект,
    # а не в freshly-read копию с диска.
    with patch.object(nbformat, "read", return_value=nb):
        with patch.object(nbformat, "write"):
            result = await backend.execute_with_params(
                nb_path, {"date": "d1"}, output_path=out_path
            )

    assert result["sandbox_id"] == "sbx-9"
    assert result["cells_executed"] == 4
    assert result["errors"] == ["params cell 0: TypeError: bad"]
    assert result["output_path"] == out_path
    # params-ячейка: injected source содержит присваивание
    injected = sb.run_code.call_args_list[0][0][0]
    assert "date = 'd1'" in injected
    # code-ячейка с results: outputs записаны в nb
    assert code_with_results.outputs[0]["data"]["text/plain"] == "42"
    sb.kill.assert_called_once()


def test_convert_results_non_text_fallback() -> None:
    """first.text пуст -> [] (fallback-ветка _convert_results)."""
    backend = E2BExecutionBackend(api_key="k")
    assert backend._convert_results([SimpleNamespace(text="")]) == []
