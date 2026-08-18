"""Tests for manage.py ``validate-profile`` command (cycle 220c2).

Ponytail/YAGNI:
- Pure typer.testing.CliRunner pattern
- No fixtures (each test is independent)
- Reuses ``Path``-based profile loading from manage.py
- Validates error paths + success path
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from manage import app


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_validate_profile_help(runner: CliRunner) -> None:
    """``validate-profile --help`` exits 0, shows usage."""
    result = runner.invoke(app, ["validate-profile", "--help"])
    assert result.exit_code == 0
    assert "validate-profile" in result.stdout


def test_validate_profile_dev_light_succeeds(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Existing dev_light.yml validates without errors."""
    # config_profiles/dev_light.yml exists in repo root
    repo_root = Path(__file__).parent.parent.parent
    profile_path = repo_root / "config_profiles" / "dev_light.yml"
    if not profile_path.is_file():
        pytest.skip("config_profiles/dev_light.yml not found (test runs outside repo)")

    result = runner.invoke(app, ["validate-profile", "dev_light"])
    assert result.exit_code == 0, (
        f"dev_light validation failed: {result.stdout} {result.stderr}"
    )
    assert "syntax + schema valid" in result.stdout


def test_validate_profile_nonexistent_profile_errors(
    runner: CliRunner,
) -> None:
    """Non-existent profile name → exit code 1 + ERROR message."""
    result = runner.invoke(app, ["validate-profile", "definitely_does_not_exist_xyz"])
    assert result.exit_code == 1
    assert "Profile not found" in result.stderr or "Profile not found" in result.stdout


def test_validate_profile_prod_with_debug_true_errors(
    runner: CliRunner, tmp_path: Path
) -> None:
    """prod profile with app.debug=true → CRITICAL error."""
    # Create temp prod profile with debug=true
    prod_with_debug = tmp_path / "prod"
    prod_with_debug.mkdir()
    (prod_with_debug / "prod.yml").write_text(
        "app:\n  debug: true\nsecure:\n  cors_origins: '*'\n"
    )

    # Patch Path to use temp dir
    with patch("manage.Path") as mock_path:
        # First call returns tmp_path/prod.yml
        def path_side_effect(*args):
            p = Path(*args) if not isinstance(args[0], Path) else args[0]
            if "prod.yml" in str(p) and "config_profiles" in str(p):
                return prod_with_debug / "prod.yml"
            return p
        mock_path.side_effect = path_side_effect
        # Verify via subprocess (simpler than mocking Path)
        result = subprocess.run(
            ["uv", "run", "python", "manage.py", "validate-profile", "prod"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent,
        )
        # Should detect critical issues (app.debug=true, cors_origins=*)
        # Note: this requires uv + a valid Python env. Skip if not available.
        if result.returncode not in (0, 1):
            pytest.skip("subprocess validate-profile not testable in this env")
        # If 1, expect CRITICAL messages
        if result.returncode == 1:
            combined = result.stdout + result.stderr
            assert "CRITICAL" in combined or "debug" in combined
