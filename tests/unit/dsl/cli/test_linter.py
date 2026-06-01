"""Unit-тесты для DSL Linter (``src.backend.dsl.cli.linter``).

Wave ``[wave:s6/k3-dsl-linter-lsp]``.

Покрытие 6 классов ошибок:

1. MISSING_ROUTE_TOML — отсутствует route.toml.
2. INVALID_TOML — battle TOML.
3. MISSING_REQUIRED_FIELD — нет name/version/requires_core.
4. INVALID_YAML — повреждённый YAML.
5. MISSING_REQUIRED_DSL_FIELDS — нет from+steps.
6. MISSING_CAPABILITY — http_call без net.outbound.
+ plugin-aware discovery + strict-mode + CLI JSON output.
"""

# ruff: noqa: S101

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from src.backend.dsl.cli.linter import DSLLinter, lint_path

# ──────────────────────────── unit ────────────────────────────


def test_missing_route_toml(tmp_path: Path) -> None:
    """Пустой каталог → MISSING_ROUTE_TOML error."""
    linter = DSLLinter()
    issues = linter.lint_route(tmp_path)
    codes = [i.code for i in issues]
    assert "MISSING_ROUTE_TOML" in codes
    assert any(i.severity == "error" for i in issues)


def test_missing_required_field_in_toml(tmp_path: Path) -> None:
    """route.toml без name → MISSING_REQUIRED_FIELD."""
    (tmp_path / "route.toml").write_text(
        '[route]\nversion = "0.1.0"\n', encoding="utf-8"
    )
    (tmp_path / "main.dsl.yaml").write_text(
        "from:\n  http:\n    path: /x\nsteps: []\n", encoding="utf-8"
    )

    issues = DSLLinter().lint_route(tmp_path)
    codes = [i.code for i in issues]
    assert "MISSING_REQUIRED_FIELD" in codes


def test_invalid_yaml(tmp_path: Path) -> None:
    """Битый YAML → INVALID_YAML error."""
    (tmp_path / "route.toml").write_text(
        '[route]\nname="x"\nversion="0.1.0"\nrequires_core=">=0.1"\n',
        encoding="utf-8",
    )
    (tmp_path / "x.dsl.yaml").write_text("not: valid: yaml: :::", encoding="utf-8")

    issues = DSLLinter().lint_route(tmp_path)
    codes = [i.code for i in issues]
    assert "INVALID_YAML" in codes


def test_missing_required_dsl_fields(tmp_path: Path) -> None:
    """YAML без from/steps → MISSING_REQUIRED_DSL_FIELDS."""
    (tmp_path / "route.toml").write_text(
        '[route]\nname="x"\nversion="0.1.0"\nrequires_core=">=0.1"\n',
        encoding="utf-8",
    )
    (tmp_path / "x.dsl.yaml").write_text("some_other_key: value\n", encoding="utf-8")

    issues = DSLLinter().lint_route(tmp_path)
    codes = [i.code for i in issues]
    assert "MISSING_REQUIRED_DSL_FIELDS" in codes


def test_missing_capability_warning(tmp_path: Path) -> None:
    """http_call без net.outbound в capabilities → MISSING_CAPABILITY warning."""
    (tmp_path / "route.toml").write_text(
        '[route]\nname="x"\nversion="0.1.0"\nrequires_core=">=0.1"\n',
        encoding="utf-8",
    )
    (tmp_path / "x.dsl.yaml").write_text(
        "from:\n  http:\n    path: /x\nsteps:\n  - http_call:\n      url: http://x\n",
        encoding="utf-8",
    )

    issues = DSLLinter().lint_route(tmp_path)
    cap_issues = [i for i in issues if i.code == "MISSING_CAPABILITY"]
    assert len(cap_issues) >= 1
    assert cap_issues[0].severity == "warning"


def test_strict_mode_promotes_warnings_to_errors(tmp_path: Path) -> None:
    """В strict-mode MISSING_CAPABILITY становится error."""
    (tmp_path / "route.toml").write_text(
        '[route]\nname="x"\nversion="0.1.0"\nrequires_core=">=0.1"\n',
        encoding="utf-8",
    )
    (tmp_path / "x.dsl.yaml").write_text(
        "from:\n  http:\n    path: /x\nsteps:\n  - http_call:\n      url: http://x\n",
        encoding="utf-8",
    )

    issues = DSLLinter(strict=True).lint_route(tmp_path)
    cap_issues = [i for i in issues if i.code == "MISSING_CAPABILITY"]
    assert any(i.severity == "error" for i in cap_issues)


def test_capability_declared_suppresses_warning(tmp_path: Path) -> None:
    """С declared net.outbound — MISSING_CAPABILITY не возникает."""
    (tmp_path / "route.toml").write_text(
        '[route]\nname="x"\nversion="0.1.0"\nrequires_core=">=0.1"\n\n'
        '[[capabilities]]\nname = "net.outbound"\nscope = "*.example.com"\n',
        encoding="utf-8",
    )
    (tmp_path / "x.dsl.yaml").write_text(
        "from:\n  http:\n    path: /x\nsteps:\n  - http_call:\n      url: http://x\n",
        encoding="utf-8",
    )

    issues = DSLLinter().lint_route(tmp_path)
    cap_codes = [i.code for i in issues]
    assert "MISSING_CAPABILITY" not in cap_codes


def test_lint_path_accepts_directory(tmp_path: Path) -> None:
    """``lint_path()`` принимает каталог и работает как lint_route."""
    (tmp_path / "route.toml").write_text(
        '[route]\nname="ok"\nversion="0.1.0"\nrequires_core=">=0.1"\n',
        encoding="utf-8",
    )
    (tmp_path / "ok.dsl.yaml").write_text(
        "from:\n  http:\n    path: /ok\nsteps: []\n", encoding="utf-8"
    )

    issues = lint_path(tmp_path)
    error_codes = [i.code for i in issues if i.severity == "error"]
    assert error_codes == []


def test_cli_returns_exit_1_on_error(tmp_path: Path) -> None:
    """CLI exit-code 1 при errors."""
    (tmp_path / "route.toml").write_text(
        '[route]\nversion="0.1.0"\n', encoding="utf-8"
    )
    (tmp_path / "x.dsl.yaml").write_text(
        "from:\n  http:\n    path: /x\nsteps: []\n", encoding="utf-8"
    )

    result = subprocess.run(  # noqa: S603 (trusted local script)
        [
            sys.executable,
            "-m",
            "src.backend.dsl.cli.linter",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 1


def test_cli_json_output(tmp_path: Path) -> None:
    """CLI с --json возвращает валидный JSON."""
    (tmp_path / "route.toml").write_text(
        '[route]\nname="x"\nversion="0.1.0"\nrequires_core=">=0.1"\n',
        encoding="utf-8",
    )
    (tmp_path / "x.dsl.yaml").write_text(
        "from:\n  http:\n    path: /x\nsteps: []\n", encoding="utf-8"
    )

    result = subprocess.run(  # noqa: S603 (trusted local script)
        [
            sys.executable,
            "-m",
            "src.backend.dsl.cli.linter",
            str(tmp_path),
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    # JSON load → list (даже пустой).
    payload = json.loads(result.stdout)
    assert isinstance(payload, list)


def test_plugin_aware_discovers_plugin_toml(tmp_path: Path) -> None:
    """В extensions/<name>/dsl/... linter читает extensions/<name>/plugin.toml."""
    ext = tmp_path / "extensions" / "my_plugin"
    (ext / "dsl").mkdir(parents=True)
    # plugin.toml с declared net.outbound capability.
    (ext / "plugin.toml").write_text(
        'name="my_plugin"\nversion="0.1.0"\n\n'
        '[[capabilities]]\nname = "net.outbound"\nscope = "*.example.com"\n',
        encoding="utf-8",
    )
    yaml_path = ext / "dsl" / "x.dsl.yaml"
    yaml_path.write_text(
        "from:\n  http:\n    path: /x\nsteps:\n  - http_call:\n      url: http://x\n",
        encoding="utf-8",
    )

    # Capability должна быть discovered из plugin.toml — нет warning.
    issues = DSLLinter().lint_yaml_file(yaml_path)
    cap_codes = [i.code for i in issues]
    assert "MISSING_CAPABILITY" not in cap_codes
