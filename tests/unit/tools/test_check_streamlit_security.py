"""S78 W4 — tests для tools/check_streamlit_security.py (P0-D closure)."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import tomllib

from tools.check_streamlit_security import (
    SecurityCheck,
    SecurityCheckResult,
    check_streamlit_config,
)


# Default config (project's) tests
# ============================================================================


def test_check_default_config_all_pass() -> None:
    """Project's default config.toml: all 4 security checks pass."""
    result = check_streamlit_config()
    assert result.all_passed, f"Failed checks: {[c.name for c in result.failed]}"


def test_check_default_config_xsrf() -> None:
    """Default: enableXsrfProtection=True."""
    result = check_streamlit_config()
    xsrf_check = next(c for c in result.checks if c.name == "enableXsrfProtection")
    assert xsrf_check.passed
    assert "enabled" in xsrf_check.detail.lower()


def test_check_default_config_cors() -> None:
    """Default: enableCORS=True with explicit allowlist."""
    result = check_streamlit_config()
    cors_check = next(c for c in result.checks if c.name == "corsAllowedOrigins")
    assert cors_check.passed


def test_check_default_config_gather_usage() -> None:
    """Default: gatherUsageStats=False."""
    result = check_streamlit_config()
    g_check = next(c for c in result.checks if c.name == "gatherUsageStats")
    assert g_check.passed


def test_check_default_config_headless() -> None:
    """Default: headless=True."""
    result = check_streamlit_config()
    h_check = next(c for c in result.checks if c.name == "headless")
    assert h_check.passed


# Failure case tests
# ============================================================================


def test_check_xsrf_disabled_fails() -> None:
    """xsrfProtection=False → fail."""
    with tempfile.NamedTemporaryFile(
        suffix=".toml", delete=False, mode="w"
    ) as f:
        f.write("""
[server]
port = 8501
headless = true
enableCORS = true
corsAllowedOrigins = ["https://example.com"]
enableXsrfProtection = false

[browser]
gatherUsageStats = false
""")
        path = Path(f.name)
    try:
        result = check_streamlit_config(path)
        xsrf_check = next(c for c in result.checks if c.name == "enableXsrfProtection")
        assert not xsrf_check.passed
        assert "False" in xsrf_check.detail or "false" in xsrf_check.detail.lower()
    finally:
        path.unlink()


def test_check_cors_disabled_warns() -> None:
    """enableCORS=False → fail (warns about cross-origin)."""
    with tempfile.NamedTemporaryFile(
        suffix=".toml", delete=False, mode="w"
    ) as f:
        f.write("""
[server]
port = 8501
headless = true
enableCORS = false
enableXsrfProtection = true

[browser]
gatherUsageStats = false
""")
        path = Path(f.name)
    try:
        result = check_streamlit_config(path)
        cors_check = next(c for c in result.checks if c.name == "enableCORS")
        assert not cors_check.passed
    finally:
        path.unlink()


def test_check_cors_wildcard_fails() -> None:
    """corsAllowedOrigins с wildcard → fail."""
    with tempfile.NamedTemporaryFile(
        suffix=".toml", delete=False, mode="w"
    ) as f:
        f.write("""
[server]
port = 8501
headless = true
enableCORS = true
corsAllowedOrigins = ["*"]
enableXsrfProtection = true

[browser]
gatherUsageStats = false
""")
        path = Path(f.name)
    try:
        result = check_streamlit_config(path)
        cors_check = next(c for c in result.checks if c.name == "corsAllowedOrigins")
        assert not cors_check.passed
        assert "Wildcard" in cors_check.detail
    finally:
        path.unlink()


def test_check_cors_empty_allowlist_fails() -> None:
    """enableCORS=True без allowlist → fail."""
    with tempfile.NamedTemporaryFile(
        suffix=".toml", delete=False, mode="w"
    ) as f:
        f.write("""
[server]
port = 8501
headless = true
enableCORS = true
enableXsrfProtection = true

[browser]
gatherUsageStats = false
""")
        path = Path(f.name)
    try:
        result = check_streamlit_config(path)
        cors_check = next(c for c in result.checks if c.name == "corsAllowedOrigins")
        assert not cors_check.passed
    finally:
        path.unlink()


def test_check_gather_usage_default_fails() -> None:
    """gatherUsageStats=True (default) → fail."""
    with tempfile.NamedTemporaryFile(
        suffix=".toml", delete=False, mode="w"
    ) as f:
        f.write("""
[server]
port = 8501
headless = true
enableCORS = true
corsAllowedOrigins = ["https://example.com"]
enableXsrfProtection = true
""")
        path = Path(f.name)
    try:
        result = check_streamlit_config(path)
        g_check = next(c for c in result.checks if c.name == "gatherUsageStats")
        assert not g_check.passed
    finally:
        path.unlink()


def test_check_headless_false_fails() -> None:
    """headless=False → fail."""
    with tempfile.NamedTemporaryFile(
        suffix=".toml", delete=False, mode="w"
    ) as f:
        f.write("""
[server]
port = 8501
headless = false
enableCORS = true
corsAllowedOrigins = ["https://example.com"]
enableXsrfProtection = true

[browser]
gatherUsageStats = false
""")
        path = Path(f.name)
    try:
        result = check_streamlit_config(path)
        h_check = next(c for c in result.checks if c.name == "headless")
        assert not h_check.passed
    finally:
        path.unlink()


# Result dataclass tests
# ============================================================================


def test_security_check_dataclass_frozen() -> None:
    """SecurityCheck is frozen (immutable)."""
    from dataclasses import FrozenInstanceError

    check = SecurityCheck(
        name="test", passed=True, detail="test detail"
    )
    with pytest.raises(FrozenInstanceError):
        check.name = "modified"  # type: ignore[misc]


def test_security_check_result_all_passed_property() -> None:
    """SecurityCheckResult.all_passed returns True if all pass."""
    checks = [
        SecurityCheck(name="a", passed=True, detail="ok"),
        SecurityCheck(name="b", passed=True, detail="ok"),
    ]
    result = SecurityCheckResult(config_path=Path("/x.toml"), checks=checks)
    assert result.all_passed
    assert result.failed == []


def test_security_check_result_failed_property() -> None:
    """SecurityCheckResult.failed returns list of failed checks."""
    checks = [
        SecurityCheck(name="a", passed=True, detail="ok"),
        SecurityCheck(name="b", passed=False, detail="fail"),
        SecurityCheck(name="c", passed=False, detail="fail"),
    ]
    result = SecurityCheckResult(config_path=Path("/x.toml"), checks=checks)
    assert not result.all_passed
    failed = result.failed
    assert len(failed) == 2
    assert all(c.name in ("b", "c") for c in failed)


# Error case tests
# ============================================================================


def test_check_nonexistent_file_raises() -> None:
    """check_streamlit_config raises FileNotFoundError на missing file."""
    with pytest.raises(FileNotFoundError, match="config не найден"):
        check_streamlit_config(Path("/nonexistent/config.toml"))


# CLI test
# ============================================================================


def test_cli_main_default_config_returns_0(capsys: pytest.CaptureFixture[str]) -> None:
    """CLI: default config returns exit code 0."""
    from tools.check_streamlit_security import main

    exit_code = main()
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "All security checks passed" in captured.out


def test_cli_main_bad_config_returns_1(capsys: pytest.CaptureFixture[str]) -> None:
    """CLI: bad config returns exit code 1."""
    from tools.check_streamlit_security import main

    with tempfile.NamedTemporaryFile(
        suffix=".toml", delete=False, mode="w"
    ) as f:
        f.write("""
[server]
enableXsrfProtection = false
""")
        path = Path(f.name)
    try:
        # Monkey-patch the default path
        import tools.check_streamlit_security as mod

        original = mod.DEFAULT_CONFIG_PATH
        mod.DEFAULT_CONFIG_PATH = path
        try:
            exit_code = main()
            assert exit_code == 1
            captured = capsys.readouterr()
            assert "check(s) failed" in captured.out
        finally:
            mod.DEFAULT_CONFIG_PATH = original
    finally:
        path.unlink()
