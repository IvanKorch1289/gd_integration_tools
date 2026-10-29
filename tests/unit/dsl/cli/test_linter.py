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

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from src.backend.dsl.cli.linter import DSLLinter, lint_path, processor_capability_map

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
        '[route]\nname="x"\nversion="0.1.0"\nrequires_core=">=0.1"\n'
        'pipelines = ["x.dsl.yaml"]\n',
        encoding="utf-8",
    )
    (tmp_path / "x.dsl.yaml").write_text("not: valid: yaml: :::", encoding="utf-8")

    issues = DSLLinter().lint_route(tmp_path)
    codes = [i.code for i in issues]
    assert "INVALID_YAML" in codes


def test_missing_required_dsl_fields(tmp_path: Path) -> None:
    """YAML без from/steps → MISSING_REQUIRED_DSL_FIELDS."""
    (tmp_path / "route.toml").write_text(
        '[route]\nname="x"\nversion="0.1.0"\nrequires_core=">=0.1"\n'
        'pipelines = ["x.dsl.yaml"]\n',
        encoding="utf-8",
    )
    (tmp_path / "x.dsl.yaml").write_text("some_other_key: value\n", encoding="utf-8")

    issues = DSLLinter().lint_route(tmp_path)
    codes = [i.code for i in issues]
    assert "MISSING_REQUIRED_DSL_FIELDS" in codes


def test_missing_capability_warning(tmp_path: Path) -> None:
    """http_call без net.outbound в capabilities → MISSING_CAPABILITY warning."""
    (tmp_path / "route.toml").write_text(
        '[route]\nname="x"\nversion="0.1.0"\nrequires_core=">=0.1"\n'
        'pipelines = ["x.dsl.yaml"]\n',
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
        '[route]\nname="x"\nversion="0.1.0"\nrequires_core=">=0.1"\n'
        'pipelines = ["x.dsl.yaml"]\n',
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
        '[route]\nname="ok"\nversion="0.1.0"\nrequires_core=">=0.1"\n'
        'pipelines = ["ok.dsl.yaml"]\n',
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
    (tmp_path / "route.toml").write_text('[route]\nversion="0.1.0"\n', encoding="utf-8")
    (tmp_path / "x.dsl.yaml").write_text(
        "from:\n  http:\n    path: /x\nsteps: []\n", encoding="utf-8"
    )

    result = subprocess.run(
        [sys.executable, "-m", "src.backend.dsl.cli.linter", str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 1


def test_cli_json_output(tmp_path: Path) -> None:
    """CLI с --json возвращает валидный JSON."""
    (tmp_path / "route.toml").write_text(
        '[route]\nname="x"\nversion="0.1.0"\nrequires_core=">=0.1"\n'
        'pipelines = ["x.dsl.yaml"]\n',
        encoding="utf-8",
    )
    (tmp_path / "x.dsl.yaml").write_text(
        "from:\n  http:\n    path: /x\nsteps: []\n", encoding="utf-8"
    )

    result = subprocess.run(
        [sys.executable, "-m", "src.backend.dsl.cli.linter", str(tmp_path), "--json"],
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


# ─────────────────── ADR-0397: канонический формат + реальные ошибки ───────────

REPO_ROOT = Path(__file__).resolve().parents[4]


def _write_route(
    tmp_path: Path,
    *,
    toml_extra: str = "",
    yaml_body: str = "steps:\n  - log:\n      level: info\n      message: hi\n",
) -> Path:
    """Минимальный валидный routes/<name>/ в tmp_path."""
    route_dir = tmp_path / "routes" / "demo"
    route_dir.mkdir(parents=True)
    (route_dir / "route.toml").write_text(
        'name = "demo"\nversion = "0.1.0"\nrequires_core = ">=0.20,<0.21"\n'
        'pipelines = ["main.dsl.yaml"]\n' + toml_extra,
        encoding="utf-8",
    )
    (route_dir / "main.dsl.yaml").write_text(
        "route_id: demo\nsource:\n  http:\n    method: POST\n    path: /demo\n"
        + yaml_body,
        encoding="utf-8",
    )
    return route_dir


def test_canonical_v11_routes_have_no_false_errors() -> None:
    """Штатные V11-роуты линтуются чисто (регрессия дефекта 2)."""
    for name in ("hello_route", "test_route_w1"):
        issues = lint_path(REPO_ROOT / "routes" / name)
        assert issues == [], f"{name}: {[i.message for i in issues]}"


def test_canonical_route_id_plus_steps_is_accepted(tmp_path: Path) -> None:
    """Канонический формат ``route_id + steps`` — без ложных ошибок."""
    route_dir = _write_route(tmp_path)
    issues = DSLLinter().lint_route(route_dir)
    assert [i.code for i in issues] == []


def test_source_plus_steps_is_accepted(tmp_path: Path) -> None:
    """Формат ``source + steps`` (без route_id) — принимается."""
    route_dir = tmp_path / "routes" / "demo"
    route_dir.mkdir(parents=True)
    (route_dir / "route.toml").write_text(
        'name = "demo"\nversion = "0.1.0"\nrequires_core = ">=0.20,<0.21"\n'
        'pipelines = ["main.dsl.yaml"]\n',
        encoding="utf-8",
    )
    (route_dir / "main.dsl.yaml").write_text(
        "source:\n  http:\n    method: POST\n    path: /demo\n"
        "steps:\n  - log:\n      level: info\n      message: hi\n",
        encoding="utf-8",
    )
    issues = DSLLinter().lint_route(route_dir)
    assert [i.code for i in issues] == []


def test_unknown_step_is_reported(tmp_path: Path) -> None:
    """Неизвестный шаг → INVALID_PIPELINE (раньше линтер молчал)."""
    route_dir = _write_route(
        tmp_path,
        yaml_body="steps:\n  - validate_request:\n      schema:\n        type: object\n",
    )
    issues = DSLLinter().lint_route(route_dir)
    pipeline_issues = [i for i in issues if i.code == "INVALID_PIPELINE"]
    assert pipeline_issues
    assert "validate_request" in pipeline_issues[0].message


def test_wrong_kwarg_is_reported(tmp_path: Path) -> None:
    """Неверный kwarg шага → INVALID_PIPELINE."""
    route_dir = _write_route(
        tmp_path,
        yaml_body="steps:\n  - transform:\n      wrong_param: body\n",
    )
    issues = DSLLinter().lint_route(route_dir)
    pipeline_issues = [i for i in issues if i.code == "INVALID_PIPELINE"]
    assert pipeline_issues
    assert "transform" in pipeline_issues[0].message


def test_invalid_nested_list_is_reported(tmp_path: Path) -> None:
    """Невалидный вложенный список (dict вместо list) → INVALID_PIPELINE."""
    route_dir = _write_route(
        tmp_path,
        yaml_body=(
            "steps:\n  - for_each:\n"
            "      items_path: body.items\n"
            "      processors:\n"
            "        nested:\n"
            "          - log:\n"
            "              level: info\n"
        ),
    )
    issues = DSLLinter().lint_route(route_dir)
    assert [i.code for i in issues if i.code == "INVALID_PIPELINE"]


def test_db_step_requires_capability_with_scope(tmp_path: Path) -> None:
    """db_query_external требует db.read со scope = алиас профиля БД."""
    route_dir = _write_route(
        tmp_path,
        yaml_body=(
            "steps:\n  - db_query_external:\n"
            "      profile: credit_reports\n"
            "      sql: SELECT id FROM credit_reports\n"
        ),
    )
    issues = DSLLinter().lint_route(route_dir)
    cap_issues = [i for i in issues if i.code == "MISSING_CAPABILITY"]
    assert cap_issues
    issue = cap_issues[0]
    assert "db.read" in issue.message
    # Подсказка должна называть требуемый scope и место декларации.
    assert "credit_reports" in issue.suggestion
    assert "[[capabilities]]" in issue.suggestion
    assert "route.toml" in issue.suggestion


def test_db_step_with_matching_scope_has_no_issue(tmp_path: Path) -> None:
    """Объявленный scope = алиас профиля → замечаний нет."""
    route_dir = _write_route(
        tmp_path,
        toml_extra='capabilities = ["db.read:credit_reports"]\n',
        yaml_body=(
            "steps:\n  - db_query_external:\n"
            "      profile: credit_reports\n"
            "      sql: SELECT id FROM credit_reports\n"
        ),
    )
    issues = DSLLinter().lint_route(route_dir)
    assert [i.code for i in issues] == []


def test_db_step_with_wrong_scope_is_reported(tmp_path: Path) -> None:
    """Несовпадение scope (профиль ≠ объявленный алиас) → замечание."""
    route_dir = _write_route(
        tmp_path,
        toml_extra='capabilities = ["db.read:other_db"]\n',
        yaml_body=(
            "steps:\n  - db_query_external:\n"
            "      profile: credit_reports\n"
            "      sql: SELECT id FROM credit_reports\n"
        ),
    )
    issues = DSLLinter().lint_route(route_dir)
    assert [i.code for i in issues if i.code == "MISSING_CAPABILITY_SCOPE"]


def test_rpa_step_requires_capability(tmp_path: Path) -> None:
    """rpa_click требует rpa.browser.click (карта из required_capability)."""
    route_dir = _write_route(
        tmp_path,
        yaml_body=(
            "steps:\n  - rpa_click:\n      selector: '#submit'\n"
        ),
    )
    issues = DSLLinter().lint_route(route_dir)
    cap_issues = [i for i in issues if i.code == "MISSING_CAPABILITY"]
    assert cap_issues
    assert "rpa.browser.click" in cap_issues[0].message


def test_processor_capability_map_comes_from_processors() -> None:
    """Карта capability строится из required_capability процессоров.

    Регрессия дефекта 5: 9 из 11 старых ключей не соответствовали
    ни одному шагу RouteBuilder.
    """
    mapping = processor_capability_map()
    assert mapping["db_query_external"] == "db.read"
    assert mapping["rpa_click"] == "rpa.browser.click"
    assert mapping["agent_run"] == "ai.invoke"
    # Несуществующие как шаги ключи убраны.
    for stale in (
        "soap_call",
        "grpc_call",
        "ws_publish",
        "mq_publish",
        "db_persist",
        "secret_get",
        "file_read",
        "file_write",
        "call_com",
    ):
        assert stale not in mapping
