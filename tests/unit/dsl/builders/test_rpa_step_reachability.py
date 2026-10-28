"""C4 (ADR-0369) — достижимость RPA-шагов из YAML через ``RouteBuilder``.

Канон ADR-0369: **имя YAML-шага = имя публичного метода ``RouteBuilder``**.
Реестр ``@processor`` — метаданные, а не способ обращения к шагу.

Покрывает:
- решение D6: 8 RPA-шагов, недостижимых из YAML;
- ``browser_launch`` / ``wait_for_selector``: kwargs не совпадали с
  сигнатурами процессоров (всегда ``TypeError``);
- парольные параметры FTP/IMAP — только dev (в prod — Vault).
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml

from src.backend.dsl.builder import RouteBuilder
from src.backend.dsl.yaml_loader import load_pipeline_from_yaml

#: D6 — шаги, которые существуют как процессоры, но не были достижимы из YAML.
D6_STEP_PARAMS: dict[str, dict[str, Any]] = {
    "csv_read": {"src": "/tmp/report.csv"},
    "csv_write": {"dst": "/tmp/out.csv", "rows": [{"a": "1"}]},
    "file_delete": {"path": "/tmp/report.csv"},
    "file_list": {"pattern": "/tmp/*.csv"},
    "ftp_upload": {
        "host": "ftp.example.com",
        "local_path": "/tmp/report.csv",
        "remote_path": "/report.csv",
    },
    "http_request": {"url": "https://api.example.com/data"},
    "email_read": {"host": "imap.example.com"},
    "terminal_exec": {"command": "echo hello"},
}


@pytest.fixture
def builder() -> RouteBuilder:
    """Минимальный builder через фабрику ``from_``."""
    return RouteBuilder.from_("c4_rpa_reachability", source="test:source")


class TestD6StepsReachableFromYaml:
    """Каждый D6-шаг собирается из YAML (имя шага = имя метода builder'а)."""

    @pytest.mark.parametrize(
        ("step_name", "params"), sorted(D6_STEP_PARAMS.items())
    )
    def test_step_is_public_builder_method(
        self, builder: RouteBuilder, step_name: str, params: dict[str, Any]
    ) -> None:
        method = getattr(builder, step_name, None)
        assert callable(method), f"RouteBuilder.{step_name} отсутствует"

    @pytest.mark.parametrize(
        ("step_name", "params"), sorted(D6_STEP_PARAMS.items())
    )
    def test_step_loads_from_yaml(self, step_name: str, params: dict[str, Any]) -> None:
        spec = {
            "route_id": f"c4_{step_name}",
            "steps": [{step_name: params}],
        }
        pipeline = load_pipeline_from_yaml(yaml.safe_dump(spec))
        assert len(pipeline.processors) == 1

    def test_all_d6_steps_covered(self) -> None:
        """Список не должен молча сокращаться."""
        assert set(D6_STEP_PARAMS) == {
            "csv_read",
            "csv_write",
            "file_delete",
            "file_list",
            "ftp_upload",
            "http_request",
            "email_read",
            "terminal_exec",
        }


class TestBrowserBuilderMethods:
    """``browser_launch`` / ``wait_for_selector`` / ``print_pdf`` — рабочие kwargs."""

    def test_browser_launch_accepts_url(self, builder: RouteBuilder) -> None:
        result = builder.browser_launch(url="https://example.com")
        assert result is builder

    def test_wait_for_selector_accepts_timeout(self, builder: RouteBuilder) -> None:
        result = builder.wait_for_selector(selector="button.submit", timeout=5.0)
        assert result is builder

    def test_wait_for_selector_accepts_state(self, builder: RouteBuilder) -> None:
        result = builder.wait_for_selector(state="networkidle", timeout=1.0)
        assert result is builder

    def test_print_pdf_exists(self, builder: RouteBuilder) -> None:
        result = builder.print_pdf(format="A4")
        assert result is builder


class TestPasswordParamsAreDevOnly:
    """Пароли — только dev; в prod источник секрета — Vault."""

    def test_ftp_upload_rejects_password_in_production(
        self, builder: RouteBuilder, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("APP_ENV", "production")
        with pytest.raises(ValueError, match="Vault"):
            builder.ftp_upload(
                host="ftp.example.com",
                password="s3cret",
                local_path="/tmp/report.csv",
                remote_path="/report.csv",
            )

    def test_email_read_rejects_password_in_production(
        self, builder: RouteBuilder, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("APP_ENV", "production")
        with pytest.raises(ValueError, match="Vault"):
            builder.email_read(host="imap.example.com", password="s3cret")

    def test_ftp_upload_allows_password_in_dev(
        self, builder: RouteBuilder, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("APP_ENV", "dev")
        result = builder.ftp_upload(
            host="ftp.example.com",
            password="s3cret",
            local_path="/tmp/report.csv",
            remote_path="/report.csv",
        )
        assert result is builder

    @pytest.mark.parametrize("method_name", ["ftp_upload", "email_read"])
    def test_docstring_mentions_vault_for_prod(self, method_name: str) -> None:
        from src.backend.dsl.builders.ai_rpa.rpa import RPAMixin

        doc = getattr(RPAMixin, method_name).__doc__ or ""
        assert "Vault" in doc
