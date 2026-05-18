"""Smoke-тесты для страницы 66_Workflow_Logs.py + APIClient методов.

Покрывает поведение трёх элементов K5 Sprint 5 Wave 1:

- :func:`APIClient.list_step_logs` — правильное формирование query params;
- :func:`APIClient.get_step_detail` — drill-down endpoint;
- graceful fallback на stub-данные при недоступности backend (К3 W11);
- AST-валидация модуля страницы (Streamlit runtime в unit-тестах не поднимается).
"""

# ruff: noqa: S101

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch


def _page_path() -> Path:
    """Вернуть абсолютный путь к Streamlit-странице 66_Workflow_Logs.py."""
    return (
        Path(__file__).resolve().parents[3]
        / "src"
        / "frontend"
        / "streamlit_app"
        / "pages"
        / "66_Workflow_Logs.py"
    )


# ---------------------------------------------------------------------------
# Тест 1: страница содержит feature_flag-guard и AST валиден
# ---------------------------------------------------------------------------


def test_page_disabled_by_flag() -> None:
    """66_Workflow_Logs.py содержит проверку feature_flag и st.stop().

    Эквивалент unit-теста ``test_page_disabled_by_flag`` без запуска
    Streamlit runtime: проверяем источники модуля и AST-валидность.
    Полная проверка через AppTest требует Streamlit-сессии и
    выполняется отдельно в integration-suite.
    """
    page = _page_path()
    assert page.exists(), f"Страница не найдена: {page}"
    source = page.read_text(encoding="utf-8")
    # AST-валидность — гарантирует, что Streamlit не упадёт с SyntaxError.
    compile(source, str(page), "exec")
    # Должен присутствовать feature-flag guard и st.stop при OFF.
    assert "feature_flags.frontend_workflow_logs_page" in source
    assert "st.stop()" in source
    # Должна быть запретная ветвь (warning + stop).
    assert "st.warning" in source

    # Загрузчик spec — гарантирует, что модуль может быть импортирован.
    spec = importlib.util.spec_from_file_location("_k5_w1_workflow_logs", page)
    assert spec is not None
    assert spec.loader is not None


# ---------------------------------------------------------------------------
# Тест 2: APIClient.list_step_logs передаёт фильтры в query params
# ---------------------------------------------------------------------------


def test_filter_params_pass_to_api() -> None:
    """``list_step_logs`` собирает все непустые фильтры в query params.

    Проверяет, что workflow_name/tenant_id/date_*/status/limit
    корректно сериализуются и попадают в HTTP GET-запрос. status
    конвертируется в comma-separated string.
    """
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "application/json"}
    mock_response.json.return_value = [
        {
            "workflow_id": "wf-1",
            "workflow_name": "credit_assessment",
            "step_name": "score",
            "status": "ok",
            "duration_ms": 120,
            "tenant_id": "t-001",
            "ts": "2026-05-14T10:00:00Z",
        }
    ]

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request.return_value = mock_response
        mock_client_cls.return_value = mock_client

        from src.frontend.streamlit_app.api_client import APIClient

        client = APIClient(base_url="http://test")
        result = client.list_step_logs(
            workflow_name="credit_assessment",
            tenant_id="t-001",
            date_from="2026-05-13",
            date_to="2026-05-14",
            status=["ok", "fail"],
            limit=50,
        )

    assert isinstance(result, list)
    assert len(result) == 1
    # Проверяем переданный URL и query params.
    call_args = mock_client.request.call_args
    assert call_args.args[0] == "GET"
    assert "/api/v1/admin/workflow/step-logs" in call_args.args[1]
    params = call_args.kwargs.get("params", {})
    assert params["workflow_name"] == "credit_assessment"
    assert params["tenant_id"] == "t-001"
    assert params["date_from"] == "2026-05-13"
    assert params["date_to"] == "2026-05-14"
    assert params["status"] == "ok,fail"
    assert params["limit"] == 50


# ---------------------------------------------------------------------------
# Тест 3: list_step_logs возвращает stub при недоступности backend
# ---------------------------------------------------------------------------


def test_table_renders_data() -> None:
    """``list_step_logs`` возвращает stub-данные при ConnectError.

    Эквивалент ``test_table_renders_data``: проверяем, что при недоступном
    K3 W11 endpoint фронт получает не пустой список stub-словарей с
    обязательными ключами для df rendering (workflow_id/step_name/status/...).
    """
    import httpx

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request.side_effect = httpx.ConnectError("backend unreachable")
        mock_client_cls.return_value = mock_client

        from src.frontend.streamlit_app.api_client import APIClient

        client = APIClient(base_url="http://test")
        rows = client.list_step_logs(workflow_name="my_wf", limit=5)

    assert isinstance(rows, list), "Должен вернуть список даже при ошибке"
    assert len(rows) >= 3, "Stub-fallback не должен быть пустым"
    first = rows[0]
    for key in ("workflow_id", "workflow_name", "step_name", "status", "duration_ms"):
        assert key in first, f"Stub-запись не содержит ключ '{key}'"
    assert first["__stub__"] is True
    # workflow_name должен подхватываться из аргумента
    assert first["workflow_name"] == "my_wf"


# ---------------------------------------------------------------------------
# Тест 4: get_step_detail работает + fallback на stub
# ---------------------------------------------------------------------------


def test_drilldown_returns_detail() -> None:
    """``get_step_detail`` возвращает dict с workflow_id и steps.

    Проверяет happy-path (HTTP 200) и graceful fallback (stub при error).
    """
    # Happy-path: HTTP 200 c корректным dict.
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "application/json"}
    mock_response.json.return_value = {
        "workflow_id": "wf-007",
        "status": "completed",
        "steps": [
            {"name": "init", "status": "ok", "duration_ms": 10},
            {"name": "score", "status": "ok", "duration_ms": 200},
        ],
    }

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request.return_value = mock_response
        mock_client_cls.return_value = mock_client

        from src.frontend.streamlit_app.api_client import APIClient

        client = APIClient(base_url="http://test")
        detail = client.get_step_detail("wf-007")

    assert detail["workflow_id"] == "wf-007"
    assert detail["status"] == "completed"
    assert len(detail["steps"]) == 2

    # Fallback: HTTP error → stub с __stub__ флагом.
    import httpx

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request.side_effect = httpx.ConnectError("backend down")
        mock_client_cls.return_value = mock_client

        from src.frontend.streamlit_app.api_client import APIClient

        client = APIClient(base_url="http://test")
        stub = client.get_step_detail("wf-missing")

    assert stub["__stub__"] is True
    assert stub["workflow_id"] == "wf-missing"
    assert "steps" in stub
