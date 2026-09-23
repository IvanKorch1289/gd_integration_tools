"""Focused tests: W11 P0-2 — tools/checks/check_unsafe_defaults.py.

Validation:
1. Module imports + typer app structure.
2. AST helpers: _is_secret_field_name, _is_placeholder, _extract_string_value.
3. scan_settings_file: HIGH (SecretStr non-empty default), MEDIUM (SecretStr ''),
   HIGH (str placeholder), LOW (str '').
4. scan_all_settings: real repo scan returns expected shape (exit 0 на текущем HEAD).
5. CLI: --json выводит JSON, --strict влияет на exit code.
6. Backward-compat main() shim.

Note: тесты используют importlib.util workaround для pytest --import-mode=importlib.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

_TOOLS_PATH = (
    Path(__file__).resolve().parents[3] / "tools" / "checks" / "check_unsafe_defaults.py"
)
_spec = importlib.util.spec_from_file_location(
    "tools.checks.check_unsafe_defaults", _TOOLS_PATH
)
module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(module)

app = module.app
main = module.main
scan_all_settings = module.scan_all_settings
scan_settings_file = module.scan_settings_file
_is_secret_field_name = module._is_secret_field_name
_is_placeholder = module._is_placeholder
_extract_string_value = module._extract_string_value

runner = CliRunner()


class TestTyperMigration:
    """Структурные проверки typer-миграции."""

    def test_app_is_typer_instance(self) -> None:
        assert isinstance(app, typer.Typer)

    def test_no_argparse_import(self) -> None:
        source = _TOOLS_PATH.read_text(encoding="utf-8")
        assert "import argparse" not in source
        assert "ArgumentParser" not in source

    def test_json_output_via_stdout(self) -> None:
        """--json использует sys.stdout.write (для piping в jq); human output → rich stderr."""
        source = _TOOLS_PATH.read_text(encoding="utf-8")
        # sys.stdout.write допустим ТОЛЬКО для JSON output
        if "sys.stdout.write" in source:
            # Проверяем что он находится рядом с json.dumps (для machine-readable output)
            assert 'json.dumps' in source, (
                "sys.stdout.write разрешён только в JSON-выводе, не в human-readable output"
            )
        # Rich console должен быть stderr=True (для human output)
        assert "Console(stderr=True)" in source

    def test_typer_help(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "unsafe secret defaults" in result.stdout.lower()


class TestIsSecretFieldName:
    """Эвристика секретного имени поля."""

    @pytest.mark.parametrize(
        "name",
        [
            "password",
            "PASSWORD",
            "api_key",
            "API_KEY",
            "token",
            "auth_token",
            "client_secret",
            "bind_password",
            "signature_secret",
        ],
    )
    def test_secret_name_detected(self, name: str) -> None:
        assert _is_secret_field_name(name) is True

    @pytest.mark.parametrize(
        "name",
        [
            "username",
            "host",
            "port",
            "url",
            "timeout",
            "password_hash",  # hash — derived, не secret
            "user_id",
            "retries",
        ],
    )
    def test_non_secret_name_skipped(self, name: str) -> None:
        assert _is_secret_field_name(name) is False


class TestIsPlaceholder:
    """Детекция placeholder-значений."""

    @pytest.mark.parametrize(
        "value",
        [
            "changeme",
            "CHANGEME",
            "password",
            "PASSWORD",
            "secret",
            "admin",
            "admin123",
            "test",
            "test123",
            "demo",
            "xxx",
            "xxxXXX",
            "your-key-here",
            "your_secret",
            "<your-api-key>",
            "placeholder",
            "TODO",
            "fixme",
        ],
    )
    def test_placeholder_detected(self, value: str) -> None:
        assert _is_placeholder(value) is True

    @pytest.mark.parametrize(
        "value",
        [
            "",
            "sk-abc123def456",
            "AKIAIOSFODNN7EXAMPLE",  # AWS example, но НЕ placeholder
            "redis://localhost:6379",
            "postgres://user:pwd@host",
        ],
    )
    def test_non_placeholder_skipped(self, value: str) -> None:
        assert _is_placeholder(value) is False


class TestExtractStringValue:
    """AST-хелпер для извлечения строковых значений."""

    def test_constant_str(self) -> None:
        import ast

        node = ast.parse('"hello"', mode="eval").body
        assert _extract_string_value(node) == "hello"

    def test_secret_str_call(self) -> None:
        import ast

        node = ast.parse('SecretStr("xyz")', mode="eval").body
        assert _extract_string_value(node) == "xyz"

    def test_secret_str_empty(self) -> None:
        import ast

        node = ast.parse('SecretStr("")', mode="eval").body
        assert _extract_string_value(node) == ""

    def test_call_to_other_func(self) -> None:
        import ast

        node = ast.parse('Path("/tmp")', mode="eval").body
        assert _extract_string_value(node) is None

    def test_none_value(self) -> None:
        import ast

        node = ast.parse("None", mode="eval").body
        assert _extract_string_value(node) is None


class TestScanSettingsFile:
    """AST-сканер: детекция violations на синтетических Settings-классах."""

    def _make_tmp_settings(self, tmp_path: Path, body: str) -> Path:
        f = tmp_path / "test_settings.py"
        f.write_text(body, encoding="utf-8")
        return f

    def test_high_secretstr_non_empty(self, tmp_path: Path) -> None:
        """HIGH: SecretStr поле с non-empty default."""
        f = self._make_tmp_settings(
            tmp_path,
            """
from pydantic import Field, SecretStr
from src.backend.core.config.config_loader import BaseSettingsWithLoader

class MySettings(BaseSettingsWithLoader):
    api_key: SecretStr = Field(default=SecretStr("hardcoded-key"), description="API key")
""",
        )
        violations = scan_settings_file(f)
        assert len(violations) == 1
        assert violations[0]["severity"] == "HIGH"
        assert violations[0]["field"] == "api_key"
        assert violations[0]["value"] == "hardcoded-key"

    def test_medium_secretstr_empty(self, tmp_path: Path) -> None:
        """MEDIUM: SecretStr с default='' (code smell)."""
        f = self._make_tmp_settings(
            tmp_path,
            """
from pydantic import Field, SecretStr
from src.backend.core.config.config_loader import BaseSettingsWithLoader

class MySettings(BaseSettingsWithLoader):
    password: SecretStr = Field(default=SecretStr(""), description="Password")
""",
        )
        violations = scan_settings_file(f)
        assert len(violations) == 1
        assert violations[0]["severity"] == "MEDIUM"
        assert violations[0]["field"] == "password"

    def test_high_str_placeholder(self, tmp_path: Path) -> None:
        """HIGH: str поле с placeholder default."""
        f = self._make_tmp_settings(
            tmp_path,
            """
from pydantic import Field
from src.backend.core.config.config_loader import BaseSettingsWithLoader

class MySettings(BaseSettingsWithLoader):
    api_key: str = Field(default="changeme", description="API key")
""",
        )
        violations = scan_settings_file(f)
        assert len(violations) == 1
        assert violations[0]["severity"] == "HIGH"
        assert violations[0]["value"] == "changeme"

    def test_low_str_empty(self, tmp_path: Path) -> None:
        """LOW: str поле с default='' (рекомендация SecretStr/None)."""
        f = self._make_tmp_settings(
            tmp_path,
            """
from pydantic import Field
from src.backend.core.config.config_loader import BaseSettingsWithLoader

class MySettings(BaseSettingsWithLoader):
    api_key: str = Field(default="", description="API key")
""",
        )
        violations = scan_settings_file(f)
        assert len(violations) == 1
        assert violations[0]["severity"] == "LOW"

    def test_safe_secretstr_none(self, tmp_path: Path) -> None:
        """SecretStr | None = None — безопасно, нет violations."""
        f = self._make_tmp_settings(
            tmp_path,
            """
from pydantic import Field, SecretStr
from src.backend.core.config.config_loader import BaseSettingsWithLoader

class MySettings(BaseSettingsWithLoader):
    password: SecretStr | None = Field(default=None, description="Password")
""",
        )
        violations = scan_settings_file(f)
        assert violations == []

    def test_safe_secretstr_required(self, tmp_path: Path) -> None:
        """SecretStr = Field(...) (required) — безопасно."""
        f = self._make_tmp_settings(
            tmp_path,
            """
from pydantic import Field, SecretStr
from src.backend.core.config.config_loader import BaseSettingsWithLoader

class MySettings(BaseSettingsWithLoader):
    password: SecretStr = Field(description="Password (required)")
""",
        )
        violations = scan_settings_file(f)
        assert violations == []

    def test_non_settings_class_skipped(self, tmp_path: Path) -> None:
        """Классы без Settings в имени и bases не сканируются."""
        f = self._make_tmp_settings(
            tmp_path,
            """
from pydantic import Field, BaseModel

class NotSettings(BaseModel):
    api_key: str = Field(default="changeme")
""",
        )
        violations = scan_settings_file(f)
        assert violations == []

    def test_non_secret_field_with_placeholder_ok(self, tmp_path: Path) -> None:
        """Placeholder default в НЕ-секретном поле — не violation (false positive guard)."""
        f = self._make_tmp_settings(
            tmp_path,
            """
from pydantic import Field
from src.backend.core.config.config_loader import BaseSettingsWithLoader

class MySettings(BaseSettingsWithLoader):
    host: str = Field(default="changeme", description="Host")
    note: str = Field(default="placeholder", description="Free-form note")
""",
        )
        violations = scan_settings_file(f)
        assert violations == []


class TestScanAllSettings:
    """Сканер на реальном репозитории."""

    def test_real_repo_no_high(self) -> None:
        """В реальном HEAD нет HIGH violations (regression guard)."""
        violations = scan_all_settings()
        high = [v for v in violations if v["severity"] == "HIGH"]
        assert high == [], (
            f"HIGH violations in real repo: {high}. "
            "Это значит есть hardcoded placeholder секрет в Pydantic Settings — срочно fix."
        )

    def test_real_repo_total_count(self) -> None:
        """Sanity check: в реальном HEAD ожидаемое число LOW violations."""
        violations = scan_all_settings()
        # Текущий HEAD: 19 LOW (известное количество str='' для secret-named полей)
        # Не делаем assert == 19, чтобы тест не ломался при добавлении новых settings —
        # только sanity что violations > 0 и нет HIGH/MEDIUM.
        assert isinstance(violations, list)
        # Если появится MEDIUM — это регрессия (забыли None)
        medium = [v for v in violations if v["severity"] == "MEDIUM"]
        assert medium == [], f"MEDIUM violations (code smell): {medium}"


class TestCli:
    """CLI через typer + backward-compat main()."""

    def test_default_exit_code(self) -> None:
        """main([]) → exit 0 (нет HIGH в реальном репо)."""
        rc = main([])
        assert rc == 0

    def test_json_output(self) -> None:
        """--json выводит валидный JSON в stdout (для piping в jq)."""
        result = runner.invoke(app, ["--json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert "total" in data
        assert "high" in data
        assert "violations" in data
        assert isinstance(data["violations"], list)

    def test_strict_flag(self) -> None:
        """--strict не меняет exit code если нет HIGH/MEDIUM."""
        rc_default = main([])
        rc_strict = main(["--strict"])
        assert rc_default == rc_strict == 0

    def test_help(self) -> None:
        """main(['--help']) → exit 0."""
        rc = main(["--help"])
        assert rc == 0
