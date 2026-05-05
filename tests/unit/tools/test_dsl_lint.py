# ruff: noqa: S101
"""Тесты `tools/dsl_lint.py` (R2.6)."""

from __future__ import annotations

import sys
from pathlib import Path
from textwrap import dedent

import pytest

_TOOLS = Path(__file__).resolve().parents[3] / "tools"
sys.path.insert(0, str(_TOOLS))

from dsl_lint import lint_file, lint_yaml, main  # noqa: E402


def _write(tmp: Path, name: str, body: str) -> Path:
    path = tmp / name
    path.write_text(dedent(body).lstrip(), encoding="utf-8")
    return path


class TestLintYAML:
    def test_valid_minimal_pipeline(self) -> None:
        findings = lint_yaml(
            dedent(
                """
                route_id: ok
                source: timer:1s
                processors:
                  - log: {level: info}
                """
            ).lstrip()
        )
        assert findings == []

    def test_missing_route_id(self) -> None:
        findings = lint_yaml(
            dedent(
                """
                source: timer:1s
                processors: []
                """
            ).lstrip()
        )
        rules = {f.rule for f in findings}
        assert "missing-field" in rules

    def test_missing_source(self) -> None:
        findings = lint_yaml(
            dedent(
                """
                route_id: ok
                processors: []
                """
            ).lstrip()
        )
        assert any(f.rule == "missing-field" for f in findings)

    def test_unknown_processor(self) -> None:
        findings = lint_yaml(
            dedent(
                """
                route_id: ok
                source: timer:1s
                processors:
                  - bogus_proc: {}
                """
            ).lstrip()
        )
        assert any(
            f.rule == "unknown-processor" and f.processor == "bogus_proc"
            for f in findings
        )

    def test_unknown_param_for_known_processor(self) -> None:
        findings = lint_yaml(
            dedent(
                """
                route_id: ok
                source: timer:1s
                processors:
                  - log: {level: info, bogus_kwarg: 1}
                """
            ).lstrip()
        )
        assert any(
            f.rule == "unknown-param" and "bogus_kwarg" in f.message for f in findings
        )

    def test_processors_not_list(self) -> None:
        findings = lint_yaml(
            dedent(
                """
                route_id: ok
                source: timer:1s
                processors:
                  log: info
                """
            ).lstrip()
        )
        assert any(f.rule == "invalid-processors" for f in findings)

    def test_yaml_syntax_error(self) -> None:
        findings = lint_yaml("route_id: [unclosed\n")
        assert any(f.rule == "yaml-syntax" for f in findings)

    def test_invalid_processor_spec_multikey(self) -> None:
        findings = lint_yaml(
            dedent(
                """
                route_id: ok
                source: timer:1s
                processors:
                  - {log: {}, normalize: {}}
                """
            ).lstrip()
        )
        assert any(f.rule == "invalid-processor-spec" for f in findings)

    def test_string_processor_form(self) -> None:
        # Без params — short string form, должна работать.
        findings = lint_yaml(
            dedent(
                """
                route_id: ok
                source: timer:1s
                processors:
                  - log
                """
            ).lstrip()
        )
        # Может быть finding по unknown-param если log() требует level,
        # но short form без params не должна давать unknown-processor.
        assert not any(f.rule == "unknown-processor" for f in findings)

    def test_invalid_root_not_mapping(self) -> None:
        findings = lint_yaml("- not a mapping\n")
        assert any(f.rule == "invalid-root" for f in findings)


class TestRouteTomlCapabilityCheck:
    def test_missing_capability_for_http_call(self, tmp_path: Path) -> None:
        # route.toml без net.outbound — http_call должен дать missing-capability.
        toml = tmp_path / "route.toml"
        toml.write_text(
            dedent(
                """
                name = "demo"
                version = "1.0.0"
                requires_core = ">=0.2,<0.3"
                tenant_aware = false

                [[capabilities]]
                name = "secrets.read"
                scope = "demo.*"
                """
            ).lstrip(),
            encoding="utf-8",
        )
        yaml_path = _write(
            tmp_path,
            "main.dsl.yaml",
            """
            route_id: demo
            source: timer:1s
            processors:
              - http_call: {url: 'https://example.com', method: GET}
            """,
        )
        findings = lint_file(yaml_path)
        assert any(
            f.rule == "missing-capability" and "net.outbound" in f.message
            for f in findings
        )

    def test_capability_present_no_finding(self, tmp_path: Path) -> None:
        toml = tmp_path / "route.toml"
        toml.write_text(
            dedent(
                """
                name = "demo"
                version = "1.0.0"
                requires_core = ">=0.2,<0.3"
                tenant_aware = false

                [[capabilities]]
                name = "net.outbound"
                scope = "*"
                """
            ).lstrip(),
            encoding="utf-8",
        )
        yaml_path = _write(
            tmp_path,
            "main.dsl.yaml",
            """
            route_id: demo
            source: timer:1s
            processors:
              - http_call: {url: 'https://example.com', method: GET}
            """,
        )
        findings = lint_file(yaml_path)
        assert not any(f.rule == "missing-capability" for f in findings)

    def test_no_route_toml_skips_capability_check(self, tmp_path: Path) -> None:
        # Без route.toml — capability-check выключен (lint только синтаксис/имена).
        yaml_path = _write(
            tmp_path,
            "main.dsl.yaml",
            """
            route_id: demo
            source: timer:1s
            processors:
              - http_call: {url: 'https://example.com', method: GET}
            """,
        )
        findings = lint_file(yaml_path)
        assert not any(f.rule == "missing-capability" for f in findings)


class TestMainCli:
    def test_strict_returns_1_on_findings(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = _write(
            tmp_path,
            "bad.yaml",
            """
            route_id: bad
            source: timer:1s
            processors:
              - bogus_proc: {}
            """,
        )
        rc = main([str(path), "--strict"])
        assert rc == 1
        captured = capsys.readouterr()
        assert "unknown-processor" in captured.out

    def test_no_findings_returns_0(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = _write(
            tmp_path,
            "ok.yaml",
            """
            route_id: ok
            source: timer:1s
            processors: []
            """,
        )
        rc = main([str(path), "--strict"])
        assert rc == 0

    def test_json_output(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        import json as _json

        path = _write(
            tmp_path,
            "bad.yaml",
            """
            route_id: bad
            source: timer:1s
            processors:
              - bogus_proc: {}
            """,
        )
        rc = main([str(path), "--json"])
        assert rc == 0
        report = _json.loads(capsys.readouterr().out)
        assert report["summary"]["findings"] >= 1
        assert "unknown-processor" in report["summary"]["by_rule"]
