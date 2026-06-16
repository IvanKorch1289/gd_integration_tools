"""S111 W3 — тесты для ``tools/check_audit_deprecation.py`` (TD-004 allowlist).

Покрывают:
1. ``LEGITIMATE_MIXIN_FILES`` существует и содержит 8 файлов.
2. ``--show-allowlist`` CLI flag выводит список.
3. ``AuditDeprecationChecker.scan()`` пропускает allowlisted файлы.
4. ``--strict`` exit 0 (нет legacy callsites после allowlist).
5. ``report_json()`` содержит ``allowlisted_files`` field.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# Module loader
# ─────────────────────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_TOOL_PATH = _REPO_ROOT / "tools" / "check_audit_deprecation.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "_check_audit_deprecation_w3", _TOOL_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_legitimate_mixin_files_constant_exists() -> None:
    """``LEGITIMATE_MIXIN_FILES`` — constant с 8 mixin-файлами (S111 W3)."""
    mod = _load_module()
    assert hasattr(mod, "LEGITIMATE_MIXIN_FILES")
    assert isinstance(mod.LEGITIMATE_MIXIN_FILES, tuple)
    assert len(mod.LEGITIMATE_MIXIN_FILES) == 8

    # Все файлы — внутри ``src/backend/core/security/`` или ``core/net/``.
    for path in mod.LEGITIMATE_MIXIN_FILES:
        assert path.startswith("src/backend/core/"), (
            f"Unexpected allowlist path: {path}"
        )
        assert path.endswith(".py"), f"Expected .py, got: {path}"


def test_legitimate_mixin_files_contain_expected_dual_emit_files() -> None:
    """Allowlist содержит известные dual-emit файлы (TD-004 audit)."""
    mod = _load_module()
    expected = {
        "src/backend/core/net/outbound_http.py",
        "src/backend/core/security/activity_capability_guard.py",
        "src/backend/core/security/authorization_gateway/__init__.py",
        "src/backend/core/security/authorization_gateway/audit_mixin.py",
        "src/backend/core/security/capabilities/gate/__init__.py",
        "src/backend/core/security/capabilities/gate/audit_mixin.py",
        "src/backend/core/security/capabilities/gate/check_mixin.py",
        "src/backend/core/security/capabilities/gate/declaration_mixin.py",
    }
    actual = set(mod.LEGITIMATE_MIXIN_FILES)
    assert actual == expected


def test_audit_deprecation_checker_exits_zero_in_strict() -> None:
    """``--strict`` exit 0: 29 mixin-internal callsites allowlisted, 0 NEW."""
    result = subprocess.run(
        [".venv/bin/python", str(_TOOL_PATH), "--strict"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"Expected exit 0, got {result.returncode}.\n"
        f"STDOUT: {result.stdout}\n"
        f"STDERR: {result.stderr}"
    )
    # В human-режиме должно быть упомянуто allowlist.
    assert "Allowlisted" in result.stdout or "allowlisted_files" in result.stdout


def test_audit_deprecation_checker_json_includes_allowlist_count() -> None:
    """``--json`` вывод содержит ``allowlisted_files`` field = 8."""
    result = subprocess.run(
        [".venv/bin/python", str(_TOOL_PATH), "--json"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert "allowlisted_files" in data
    assert data["allowlisted_files"] == 8
    # После allowlist: 0 files with legacy, 0 callsites.
    assert data["total_callsites"] == 0
    assert data["files_with_legacy"] == 0


def test_audit_deprecation_checker_show_allowlist_flag() -> None:
    """``--show-allowlist`` печатает LEGITIMATE_MIXIN_FILES и выходит 0."""
    result = subprocess.run(
        [".venv/bin/python", str(_TOOL_PATH), "--show-allowlist"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0
    assert "LEGITIMATE_MIXIN_FILES (8 files)" in result.stdout
    # Все 8 файлов перечислены.
    for path in (
        "src/backend/core/net/outbound_http.py",
        "src/backend/core/security/activity_capability_guard.py",
        "src/backend/core/security/authorization_gateway/audit_mixin.py",
        "src/backend/core/security/capabilities/gate/check_mixin.py",
    ):
        assert path in result.stdout


def test_audit_deprecation_checker_excludes_allowlisted_files() -> None:
    """``AuditDeprecationChecker._should_exclude`` возвращает True для mixin-файлов."""
    mod = _load_module()
    checker = mod.AuditDeprecationChecker(root=_REPO_ROOT)
    for allowlisted_path in mod.LEGITIMATE_MIXIN_FILES:
        abs_path = _REPO_ROOT / allowlisted_path
        assert abs_path.exists(), f"File must exist: {abs_path}"
        assert checker._should_exclude(abs_path), (
            f"Allowlisted file should be excluded: {allowlisted_path}"
        )


def test_audit_deprecation_checker_scan_returns_zero_results() -> None:
    """``scan()`` после S111 W3 allowlist даёт 0 files / 0 callsites."""
    mod = _load_module()
    checker = mod.AuditDeprecationChecker(root=_REPO_ROOT)
    results = checker.scan()
    assert results == {}, f"Expected no legacy callsites, got: {list(results.keys())}"
    assert checker.total_callsites == 0
    assert checker.total_files == 0
