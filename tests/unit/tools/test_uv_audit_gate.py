"""A6 (ADR-0385): gate аудита всего lock-файла (``uv audit --frozen``).

Дефект
------
CI-скан уязвимостей (``pip-audit``) проверял только default-venv
(``uv sync``) — 41 из 117 уязвимостей в extras не попадали в проверку.

Ожидание
--------
* ``tools/uv_audit_gate.py`` парсит текстовый отчёт ``uv audit``;
* advisory-ID из canonical allowlist — долг, гейт проходит;
* НОВЫЙ advisory-ID (нет в allowlist) — гейт падает (exit 1);
* пустой/битый отчёт — fail-closed (exit 1), а не «зелёный» молча.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_GATE_PATH = Path(__file__).resolve().parents[3] / "tools" / "uv_audit_gate.py"
_spec = importlib.util.spec_from_file_location("tools.uv_audit_gate", _GATE_PATH)
module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(module)

REPORT_SAMPLE = """\
Found 2 known vulnerabilities and no adverse project statuses in 711 packages

Vulnerabilities:

pillow 13.0.0 has 1 known vulnerabilities:

- GHSA-65qm-jvmh-6pqg: Pillow: GIF seek keeps rejected size after DecompressionBombError

  Fixed in: 13.1.0

chromadb 1.5.9 has 1 known vulnerabilities:

- PYSEC-2026-311: ChromaDB Python project has a pre-authentication code injection vulnerability

  No fix versions available
"""


def _write_allowlist(tmp_path: Path, ids: list[str]) -> Path:
    path = tmp_path / "allowlist.txt"
    path.write_text("\n".join(ids) + "\n", encoding="utf-8")
    return path


class TestParsing:
    """Парсинг отчёта ``uv audit``."""

    def test_extracts_advisory_ids(self) -> None:
        """ID вида GHSA-*/PYSEC-* извлекаются из отчёта."""
        ids = module.extract_advisory_ids(REPORT_SAMPLE)
        assert ids == {"GHSA-65qm-jvmh-6pqg", "PYSEC-2026-311"}

    def test_ignores_cve_links_in_details(self) -> None:
        """Ссылки вида ``CVE-2026-45830`` в деталях не считаются advisory-ID."""
        report = REPORT_SAMPLE + (
            "\n  Advisory information: "
            "https://nvd.nist.gov/vuln/detail/CVE-2026-45830\n"
        )
        ids = module.extract_advisory_ids(report)
        assert "CVE-2026-45830" not in ids

    def test_empty_report_yields_no_ids(self) -> None:
        """Пустой отчёт не даёт advisory-ID."""
        assert module.extract_advisory_ids("") == set()


class TestGate:
    """Поведение гейта."""

    def test_known_ids_pass(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Известный долг (allowlist) — гейт зелёный."""
        allowlist = _write_allowlist(tmp_path, ["GHSA-65qm-jvmh-6pqg", "PYSEC-2026-311"])
        report = tmp_path / "report.txt"
        report.write_text(REPORT_SAMPLE, encoding="utf-8")
        code = module.run_gate(report, allowlist)
        assert code == 0

    def test_new_id_fails(self, tmp_path: Path) -> None:
        """Новый advisory-ID (нет в allowlist) — гейт падает."""
        allowlist = _write_allowlist(tmp_path, ["PYSEC-2026-311"])
        report = tmp_path / "report.txt"
        report.write_text(REPORT_SAMPLE, encoding="utf-8")
        code = module.run_gate(report, allowlist)
        assert code == 1

    def test_missing_report_fails_closed(self, tmp_path: Path) -> None:
        """Отсутствующий отчёт — fail-closed (не «зелёный молча»)."""
        allowlist = _write_allowlist(tmp_path, [])
        code = module.run_gate(tmp_path / "nope.txt", allowlist)
        assert code == 1

    def test_empty_report_fails_closed(self, tmp_path: Path) -> None:
        """Отчёт без единой advisory-строки — fail-closed."""
        allowlist = _write_allowlist(tmp_path, [])
        report = tmp_path / "report.txt"
        report.write_text("no vulnerabilities found\n", encoding="utf-8")
        code = module.run_gate(report, allowlist)
        assert code == 1

    def test_allowlist_missing_fails_closed(self, tmp_path: Path) -> None:
        """Нет allowlist-файла — fail-closed."""
        report = tmp_path / "report.txt"
        report.write_text(REPORT_SAMPLE, encoding="utf-8")
        code = module.run_gate(report, tmp_path / "missing-allowlist.txt")
        assert code == 1


class TestCli:
    """CLI-точка входа."""

    def test_cli_exit_code(self, tmp_path: Path) -> None:
        """CLI возвращает exit code гейта."""
        allowlist = _write_allowlist(tmp_path, ["GHSA-65qm-jvmh-6pqg", "PYSEC-2026-311"])
        report = tmp_path / "report.txt"
        report.write_text(REPORT_SAMPLE, encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable,
                str(_GATE_PATH),
                "--report",
                str(report),
                "--allowlist",
                str(allowlist),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
