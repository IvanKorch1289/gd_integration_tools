"""Smoke-тесты для supply-chain CI gate scaffold.

K1 Sprint-3 Wave 3: подтверждает базовую работоспособность трёх скриптов
(generate_sbom, run_pip_audit, cosign_sign) и наличие Makefile targets.

Тесты не запускают реальный cyclonedx/pip-audit/cosign — только
проверяют синтаксическую корректность модулей и наличие targets в Makefile.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Корень проекта — два уровня вверх от tests/unit/tools/.
_ROOT = Path(__file__).parent.parent.parent.parent

_GENERATE_SBOM = _ROOT / "tools" / "checks" / "generate_sbom.py"
_RUN_PIP_AUDIT = _ROOT / "tools" / "checks" / "run_pip_audit.py"
_COSIGN_SIGN = _ROOT / "tools" / "checks" / "cosign_sign.py"
_MAKEFILE_SECURITY = _ROOT / "Makefile.security"


def test_generate_sbom_module_importable() -> None:
    """tools/checks/generate_sbom.py синтаксически корректен и компилируется без ошибок."""
    assert _GENERATE_SBOM.exists(), f"generate_sbom.py не найден: {_GENERATE_SBOM}"

    result = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "py_compile", str(_GENERATE_SBOM)],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, (
        f"py_compile завершился с кодом {result.returncode}.\n"
        f"stderr: {result.stderr[:500]}"
    )


def test_run_pip_audit_module_importable() -> None:
    """tools/checks/run_pip_audit.py синтаксически корректен и компилируется без ошибок."""
    assert _RUN_PIP_AUDIT.exists(), f"run_pip_audit.py не найден: {_RUN_PIP_AUDIT}"

    result = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "py_compile", str(_RUN_PIP_AUDIT)],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, (
        f"py_compile завершился с кодом {result.returncode}.\n"
        f"stderr: {result.stderr[:500]}"
    )


def test_cosign_sign_module_importable() -> None:
    """tools/checks/cosign_sign.py синтаксически корректен и компилируется без ошибок."""
    assert _COSIGN_SIGN.exists(), f"cosign_sign.py не найден: {_COSIGN_SIGN}"

    result = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "py_compile", str(_COSIGN_SIGN)],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, (
        f"py_compile завершился с кодом {result.returncode}.\n"
        f"stderr: {result.stderr[:500]}"
    )


def test_makefile_targets_present() -> None:
    """Makefile.security содержит все три обязательных supply-chain targets."""
    assert _MAKEFILE_SECURITY.exists(), (
        f"Makefile.security не найден: {_MAKEFILE_SECURITY}"
    )

    content = _MAKEFILE_SECURITY.read_text(encoding="utf-8")

    required_targets = ("sbom", "audit-deps", "cosign-sign")
    for target in required_targets:
        assert f"{target}:" in content, (
            f"Target '{target}:' не найден в Makefile.security"
        )
