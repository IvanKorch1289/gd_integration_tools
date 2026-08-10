"""D-AUDIT-11-2 fix (cycle 1): SBOM генерируется через pip-audit в .venv.

Корневая причина бага: ``make/security.mk:sbom`` вызывал ``cyclonedx-py environment``
через ``$(UV_RUN)``, но ``cyclonedx-py`` резолвился в
``/home/user/.local/bin/cyclonedx-py`` (system binary, shebang
``#!/usr/bin/python3.12``). Результат: SBOM содержал stale deps
(cryptography 41.0.7, starlette 1.0.0, urllib3 2.0.7) из system Python 3.12,
а не из ``.venv`` (Python 3.14 + uv.lock: cryptography 49.0.0,
starlette 1.3.1, urllib3 2.7.0).

После фикса SBOM пишется через ``pip-audit --format cyclonedx-json``,
который установлен в ``.venv`` (verified: ``pip-audit==2.10.1``),
генерирует валидный CycloneDX 1.4 JSON (cosign подписывает opaque blob,
формат не критичен), и собирает deps из ``dist/audit-requirements.txt``
(генерируется через ``uv pip freeze --exclude-editable``, single source of truth).

CVE-handling отделено: ``|| true`` подавляет exit != 0 при CVE,
гейт работает через ``tools/pip_audit_gate.py`` — backward-compat с
``audit-deps`` target.
"""


from __future__ import annotations

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]


class TestSBOMViaVenv:
    """D-AUDIT-11-2 fix: ``make sbom`` использует pip-audit из .venv, не system cyclonedx-py."""

    def test_sbom_uses_pip_audit_cyclonedx_json(self) -> None:
        """sbom target вызывает ``pip-audit --format cyclonedx-json``, а НЕ ``cyclonedx-py``.

        Раньше ``$(UV_RUN) cyclonedx-py environment ...`` резолвился в
        ``/home/user/.local/bin/cyclonedx-py`` (system Python 3.12) — мимо .venv.
        """
        security_mk = (_ROOT / "make" / "security.mk").read_text(encoding="utf-8")
        assert "pip-audit --format cyclonedx-json" in security_mk, (
            "make/security.mk:sbom target должен использовать "
            "'pip-audit --format cyclonedx-json' (D-AUDIT-11-2 fix)"
        )
        assert "cyclonedx-py environment" not in security_mk, (
            "Legacy 'cyclonedx-py environment' НЕ должен оставаться в make/security.mk — "
            "резолвится в system Python 3.12, минуя .venv"
        )

    def test_sbom_uses_venv_requirements(self) -> None:
        """sbom target использует ``dist/audit-requirements.txt`` (генерится из .venv).

        ``dist/audit-requirements.txt`` создаётся через
        ``uv pip freeze --exclude-editable`` — это срез реального .venv,
        не system Python. Single source of truth для supply-chain анализа.
        """
        security_mk = (_ROOT / "make" / "security.mk").read_text(encoding="utf-8")
        sbom_block = security_mk.split("sbom:", 1)[1].split("audit-deps:", 1)[0]
        assert "dist/audit-requirements.txt" in sbom_block, (
            "make/security.mk:sbom target должен использовать "
            "dist/audit-requirements.txt (из uv pip freeze --exclude-editable)"
        )

    def test_sbom_canonical_path_preserved(self) -> None:
        """Canonical путь ``dist/sbom/sbom.cdx.json`` сохранён (D-AUDIT-11-5 backward-compat)."""
        security_mk = (_ROOT / "make" / "security.mk").read_text(encoding="utf-8")
        sbom_block = security_mk.split("sbom:", 1)[1].split("audit-deps:", 1)[0]
        assert "dist/sbom/sbom.cdx.json" in sbom_block, (
            "Canonical path dist/sbom/sbom.cdx.json должен остаться в sbom target "
            "(D-AUDIT-11-5 fix не должен быть откачен)"
        )

    def test_sbom_respects_pip_audit_allowlist(self) -> None:
        """sbom target применяет ALLOW из ``.security/pip-audit-allowlist.txt``.

        Совпадает с паттерном ``audit-deps`` (lines 45-57) — single source of truth
        для allowlist-логики между SBOM и pip-audit gate.
        """
        security_mk = (_ROOT / "make" / "security.mk").read_text(encoding="utf-8")
        sbom_block = security_mk.split("sbom:", 1)[1].split("audit-deps:", 1)[0]
        assert ".security/pip-audit-allowlist.txt" in sbom_block, (
            "make/security.mk:sbom target должен читать "
            ".security/pip-audit-allowlist.txt (единый паттерн с audit-deps)"
        )
        assert "--ignore-vuln" in sbom_block, (
            "make/security.mk:sbom target должен прокидывать --ignore-vuln в pip-audit"
        )

    def test_sbom_swallow_cve_exit_code(self) -> None:
        """sbom target подавляет exit != 0 через ``|| true`` — CVE не ломают SBOM-регенерацию.

        CVE-handling — отдельный concern: ``tools/pip_audit_gate.py``
        делает exit 1 на CVE в CI, а SBOM-генерация должна всегда успешно
        записать dist/sbom/sbom.cdx.json.
        """
        security_mk = (_ROOT / "make" / "security.mk").read_text(encoding="utf-8")
        sbom_block = security_mk.split("sbom:", 1)[1].split("audit-deps:", 1)[0]
        pip_audit_line = [
            line for line in sbom_block.splitlines() if "pip-audit" in line
        ]
        assert pip_audit_line, "sbom target должен содержать вызов pip-audit"
        assert any("|| true" in line for line in pip_audit_line), (
            "make/security.mk:sbom target: pip-audit должен вызываться с '|| true', "
            "иначе CVE-ы ломают SBOM-регенерацию"
        )

    def test_pip_audit_installed_in_venv(self) -> None:
        """``pip-audit`` физически установлен в .venv (run-time pre-condition)."""
        import subprocess

        venv_pip_audit = _ROOT / ".venv" / "bin" / "pip-audit"
        assert venv_pip_audit.exists(), (
            f"pip-audit не найден в {venv_pip_audit}. "
            "Запустите 'uv sync --extra dev' для восстановления .venv."
        )
        # Verify runnable + version output (не делает network-вызовов)
        result = subprocess.run(
            [str(venv_pip_audit), "--version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert "pip-audit" in result.stdout.lower(), (
            f"pip-audit --version вернул неожиданный output: {result.stdout!r}"
        )


@pytest.mark.parametrize(
    "legacy_pattern",
    [
        "cyclonedx-py environment",
        "cyclonedx-py requirements",
        "-o dist/sbom.cdx.json",
    ],
)
def test_sbom_no_legacy_patterns(legacy_pattern: str) -> None:
    """Regression guard: ни один legacy SBOM-паттерн не должен вернуться в make/security.mk."""
    security_mk = (_ROOT / "make" / "security.mk").read_text(encoding="utf-8")
    sbom_block = security_mk.split("sbom:", 1)[1].split("audit-deps:", 1)[0]
    assert legacy_pattern not in sbom_block, (
        f"Legacy SBOM-паттерн '{legacy_pattern}' не должен быть в sbom target"
    )
