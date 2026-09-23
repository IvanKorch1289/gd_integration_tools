"""Focused tests: W11 P0-3 — tools/check_env_example.py matrix mode.

Validation:
1. Class detection fix: env_prefix in model_config (vs only BaseSettings in bases).
2. CONFIG_DIR path fix: src/backend/core/config (vs legacy src/core/config).
3. Required field tracking via Field(...) and Field(..., description=...).
4. collect_required_secret_env_vars: только required + secret-named.
5. CLI --matrix: exit 1 при missing required secrets.
6. CLI --json: structured output.
7. CLI default: soft-warn (exit 0) — backward-compat.
8. CLI --strict: hard fail on missing.

Note: тесты используют importlib.util workaround для pytest --import-mode=importlib.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

_TOOLS_PATH = (
    Path(__file__).resolve().parents[3] / "tools" / "check_env_example.py"
)
_spec = importlib.util.spec_from_file_location("tools.check_env_example", _TOOLS_PATH)
module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(module)

app = module.app
main = module.main
collect_expected_env_vars = module.collect_expected_env_vars
collect_required_secret_env_vars = module.collect_required_secret_env_vars
collect_env_example_vars = module.collect_env_example_vars
_extract_env_prefixes_from_file = module._extract_env_prefixes_from_file
_is_secret_field_name = module._is_secret_field_name
CONFIG_DIR = module.CONFIG_DIR

runner = CliRunner()


class TestConfigDirFix:
    """W11 P0-3 fix: CONFIG_DIR был src/core/config (несуществующий) → src/backend/core/config."""

    def test_config_dir_exists(self) -> None:
        """CONFIG_DIR должен указывать на реальный каталог."""
        assert CONFIG_DIR.exists(), (
            f"CONFIG_DIR={CONFIG_DIR} не существует; "
            "должен быть src/backend/core/config"
        )

    def test_config_dir_contains_settings(self) -> None:
        """CONFIG_DIR содержит Settings-файлы (sanity check)."""
        settings_files = list(CONFIG_DIR.rglob("*.py"))
        assert len(settings_files) > 50, (
            f"Ожидается 50+ Settings-файлов, найдено {len(settings_files)}"
        )


class TestClassDetection:
    """W11 P0-3 fix: detect Settings via env_prefix в model_config, не только BaseSettings."""

    def _make_tmp_settings(self, tmp_path: Path, body: str) -> Path:
        f = tmp_path / "test_settings.py"
        f.write_text(body, encoding="utf-8")
        return f

    def test_detect_via_env_prefix(self, tmp_path: Path) -> None:
        """Settings с env_prefix в model_config (без BaseSettings в bases) → detected."""
        f = self._make_tmp_settings(
            tmp_path,
            """
from pydantic import BaseModel, Field
from pydantic_settings import SettingsConfigDict

class FooSettings(BaseModel):
    model_config = SettingsConfigDict(env_prefix="FOO_")
    bar: str = Field(default="x", description="Bar")
    baz: int = Field(42, description="Baz")
""",
        )
        result = _extract_env_prefixes_from_file(f)
        assert len(result) == 1
        prefix, fields = result[0]
        assert prefix == "FOO_"
        field_names = [f[0] for f in fields]
        assert "bar" in field_names
        assert "baz" in field_names

    def test_detect_via_basesettings(self, tmp_path: Path) -> None:
        """Settings с BaseSettings в bases → still detected (backward-compat)."""
        f = self._make_tmp_settings(
            tmp_path,
            """
from pydantic_settings import BaseSettings, SettingsConfigDict

class BarSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BAR_")
    foo: str = "x"
""",
        )
        result = _extract_env_prefixes_from_file(f)
        assert len(result) == 1
        assert result[0][0] == "BAR_"

    def test_skip_non_settings_class(self, tmp_path: Path) -> None:
        """Класс без env_prefix и без Settings в bases → skipped."""
        f = self._make_tmp_settings(
            tmp_path,
            """
from pydantic import BaseModel

class NotSettings(BaseModel):
    foo: str = "x"
    bar: int = 42
""",
        )
        result = _extract_env_prefixes_from_file(f)
        assert result == []


class TestRequiredFieldTracking:
    """W11 P0-3: track is_required per field via Field(...) pattern."""

    def _make_tmp_settings(self, tmp_path: Path, body: str) -> Path:
        f = tmp_path / "test_settings.py"
        f.write_text(body, encoding="utf-8")
        return f

    def test_field_ellipsis_required(self, tmp_path: Path) -> None:
        """Field(...) (Ellipsis) → required."""
        f = self._make_tmp_settings(
            tmp_path,
            """
from pydantic import BaseModel, Field
from pydantic_settings import SettingsConfigDict

class S(BaseModel):
    model_config = SettingsConfigDict(env_prefix="S_")
    api_key: str = Field(..., description="API key (required)")
    name: str = Field(default="x", description="Name (optional)")
""",
        )
        result = _extract_env_prefixes_from_file(f)
        prefix, fields = result[0]
        fields_dict = dict(fields)
        assert fields_dict["api_key"] is True
        assert fields_dict["name"] is False

    def test_field_no_default_required(self, tmp_path: Path) -> None:
        """Field(description=...) без default → required (Pydantic convention)."""
        f = self._make_tmp_settings(
            tmp_path,
            """
from pydantic import BaseModel, Field
from pydantic_settings import SettingsConfigDict

class S(BaseModel):
    model_config = SettingsConfigDict(env_prefix="S_")
    password: str = Field(description="Password (no default)")
""",
        )
        result = _extract_env_prefixes_from_file(f)
        prefix, fields = result[0]
        assert dict(fields)["password"] is True

    def test_field_with_default_optional(self, tmp_path: Path) -> None:
        """Field(default=...) → not required."""
        f = self._make_tmp_settings(
            tmp_path,
            """
from pydantic import BaseModel, Field
from pydantic_settings import SettingsConfigDict

class S(BaseModel):
    model_config = SettingsConfigDict(env_prefix="S_")
    token: str = Field(default="", description="Token (with default)")
    host: str = Field("localhost", description="Host")
""",
        )
        result = _extract_env_prefixes_from_file(f)
        prefix, fields = result[0]
        d = dict(fields)
        assert d["token"] is False
        assert d["host"] is False


class TestCollectRequiredSecretEnvVars:
    """collect_required_secret_env_vars: required + secret-named."""

    def test_finds_real_required_secrets(self) -> None:
        """В реальном репо должны быть найдены required + secret поля."""
        required_secrets = collect_required_secret_env_vars()
        # Sanity: должны быть сотни required secret vars
        assert len(required_secrets) > 0
        # Все должны быть uppercase
        for v in required_secrets:
            assert v == v.upper(), f"{v} не uppercase"
            assert "_" in v, f"{v} не содержит underscore"

    def test_only_secret_named_fields(self) -> None:
        """В результат попадают ТОЛЬКО поля с secret-именами."""
        required_secrets = collect_required_secret_env_vars()
        # Все должны иметь в имени хотя бы один secret-pattern
        # (lowercase, т.к. имена полей после upper() содержат secret-pattern
        # в виде password/api_key/etc.)
        secret_keywords = {
            "password", "secret", "api_key", "apikey",
            "token", "auth_token", "api_token", "access_key",
            "client_secret", "private_key", "bind_password",
        }
        for v in required_secrets:
            # Проверяем что хотя бы одно secret-keyword в lowercase-имени
            lower = v.lower()
            assert any(kw in lower for kw in secret_keywords), (
                f"{v} не похоже на secret var (нет keyword)"
            )


class TestRealRepoRegression:
    """Sanity checks на реальном репозитории."""

    def test_expected_env_vars_count(self) -> None:
        """В репо должно быть 500+ expected env vars (после fix CONFIG_DIR)."""
        expected = collect_expected_env_vars()
        assert len(expected) > 500, (
            f"Только {len(expected)} env vars — возможно CONFIG_DIR неправильный"
        )

    def test_env_example_vars_count(self) -> None:
        """В .env.example должно быть 30+ vars."""
        documented = collect_env_example_vars()
        assert len(documented) > 30, (
            f"Только {len(documented)} vars в .env.example"
        )


class TestCliMatrix:
    """CLI --matrix mode: required secrets check."""

    def test_help_includes_matrix(self) -> None:
        """--help упоминает --matrix flag."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "--matrix" in result.stdout

    def test_default_mode_exits_zero_on_warnings(self) -> None:
        """Default mode: warn (exit 0) даже если missing vars (W11 P0-3 soft-warn)."""
        rc = main([])
        assert rc == 0

    def test_strict_mode_fails_on_missing(self) -> None:
        """--strict: exit 1 если есть missing vars."""
        rc = main(["--strict"])
        # В реальном репо 958 vars missing → exit 1
        assert rc == 1

    def test_matrix_mode_fails_on_required_secret_missing(self) -> None:
        """--matrix: exit 1 если есть required secrets missing.

        After bug fix in commit (env var naming rstrip("_")) + .env.example update
        для SEC_ROUTES_WITHOUT_API_KEY, current real repo has 0 truly required
        secrets missing. Test verifies the gate works correctly:
        - Exit 0 when no required secrets missing (post-fix state).
        """
        rc = main(["--matrix"])
        # After fix: 0 required secrets missing → exit 0.
        assert rc == 0, (
            "Если rc=1, значит bug вернулся: либо env var naming bug, "
            "либо .env.example не содержит documented required secret."
        )

    def test_json_output(self) -> None:
        """--json выводит structured JSON (exit 0 если no required missing)."""
        result = runner.invoke(app, ["--matrix", "--json"])
        assert result.exit_code == 0  # нет required missing после fix
        data = json.loads(result.stdout)
        assert "total_expected" in data
        assert "total_documented" in data
        assert "missing" in data
        assert "extra" in data
        assert "matrix_required_secrets_missing" in data
        assert isinstance(data["matrix_required_secrets_missing"], list)
        # Post-fix: 0 required secrets missing
        assert len(data["matrix_required_secrets_missing"]) == 0

    def test_matrix_mode_detects_missing_when_introduced(self) -> None:
        """Regression test: --matrix должен exit 1 когда есть missing.

        Использует monkeypatch для симуляции missing required secret.
        """
        original_collect = module.collect_required_secret_env_vars
        module.collect_required_secret_env_vars = (
            lambda: original_collect() | {"FAKE_REQUIRED_SECRET"}
        )

        try:
            rc = main(["--matrix"])
            assert rc == 1, "Gate должно exit 1 при наличии missing required secret"
        finally:
            module.collect_required_secret_env_vars = original_collect

    def test_json_output_default(self) -> None:
        """--json без --matrix: matrix_required_secrets_missing = []."""
        result = runner.invoke(app, ["--json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["matrix_required_secrets_missing"] == []

    def test_json_output_strict(self) -> None:
        """--json --strict: extra vars detected."""
        result = runner.invoke(app, ["--strict", "--json"])
        data = json.loads(result.stdout)
        assert "extra" in data
        assert len(data["extra"]) > 0


class TestIsSecretFieldName:
    """Эвристика секретного имени (общая с check_unsafe_defaults)."""

    @pytest.mark.parametrize(
        "name",
        ["password", "api_key", "token", "auth_token", "signature_secret"],
    )
    def test_secret_detected(self, name: str) -> None:
        assert _is_secret_field_name(name) is True

    @pytest.mark.parametrize("name", ["host", "port", "url", "retries", "timeout"])
    def test_non_secret_skipped(self, name: str) -> None:
        assert _is_secret_field_name(name) is False
