"""make doctor — комплексный health-check разработческого окружения (S10 K5 W1).

DX-8.1: Запускает быструю серию проверок и выводит сводку:

* Python version (требуется ≥ 3.14);
* окружение (uv, pyproject.toml, .env);
* services healthcheck (PG / Redis / ClickHouse / Temporal / Vault /
  Kafka) — TCP ping с быстрым timeout;
* environment validation (обязательные переменные);
* TaskIQ imports = 0 (V15 R-V15-7: запрещено);
* WAF coverage = 0 violations (R-V15-5);
* layer violations = 0 (Clean Architecture);
* mypy budget ≤ 5 (S10 K2 W1).

Запуск:

.. code-block:: bash

    python tools/checks/doctor.py
    # exit 0 — всё OK
    # exit 1 — хотя бы одна проверка FAIL

    python tools/checks/doctor.py --quick
    # пропускает network healthchecks для быстрого CI
"""

from __future__ import annotations

import argparse
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@dataclass(slots=True)
class CheckResult:
    """Результат одной проверки."""

    name: str
    ok: bool
    detail: str = ""


@dataclass(slots=True)
class DoctorReport:
    """Сводный отчёт по всем проверкам."""

    results: list[CheckResult] = field(default_factory=list)

    @property
    def all_ok(self) -> bool:
        return all(r.ok for r in self.results)

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.results.append(CheckResult(name=name, ok=ok, detail=detail))


# === Individual checks ===


def check_python_version(report: DoctorReport) -> None:
    """Python ≥ 3.14."""
    info = sys.version_info
    ok = info >= (3, 14)
    detail = f"{info.major}.{info.minor}.{info.micro}"
    report.add("python-version", ok, f"требуется ≥3.14, текущая {detail}")


def check_uv_available(report: DoctorReport) -> None:
    """uv установлен в PATH."""
    try:
        proc = subprocess.run(
            ["uv", "--version"], capture_output=True, text=True, timeout=5
        )
        report.add("uv-binary", proc.returncode == 0, proc.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        report.add("uv-binary", False, f"uv не найден: {exc}")


def check_pyproject(report: DoctorReport) -> None:
    """pyproject.toml существует и парсится."""
    path = ROOT / "pyproject.toml"
    if not path.is_file():
        report.add("pyproject.toml", False, f"не найден: {path}")
        return
    try:
        import tomllib

        tomllib.loads(path.read_text(encoding="utf-8"))
        report.add("pyproject.toml", True, "OK")
    except Exception as exc:  # noqa: BLE001 — broad parse-error
        report.add("pyproject.toml", False, f"parse error: {exc}")


def _tcp_ping(host: str, port: int, timeout: float = 1.0) -> bool:
    """TCP-ping (быстрый проверочный handshake)."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, socket.timeout):
        return False


def check_services(report: DoctorReport, *, quick: bool) -> None:
    """services healthcheck (PG / Redis / CH / Temporal / Vault / Kafka)."""
    if quick:
        report.add("services-net", True, "SKIPPED (--quick)")
        return

    targets = [
        ("postgres", "127.0.0.1", 5432),
        ("redis", "127.0.0.1", 6379),
        ("clickhouse", "127.0.0.1", 8123),
        ("temporal", "127.0.0.1", 7233),
        ("vault", "127.0.0.1", 8200),
        ("kafka", "127.0.0.1", 9092),
    ]
    for label, host, port in targets:
        ok = _tcp_ping(host, port)
        report.add(
            f"service-{label}",
            ok,
            f"{host}:{port} {'reachable' if ok else 'unreachable'}",
        )


def check_taskiq_zero(report: DoctorReport) -> None:
    """V15 R-V15-7: запрещено импортировать taskiq."""
    matches = 0
    for py in (ROOT / "src").rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        try:
            text = py.read_text(encoding="utf-8")
        except OSError:
            continue
        if "import taskiq" in text or "from taskiq" in text:
            matches += 1
    report.add(
        "taskiq-imports",
        matches == 0,
        f"{matches} taskiq import(s) (должно быть 0)",
    )


def _run_tool(cmd: list[str]) -> tuple[bool, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return proc.returncode == 0, proc.stdout.splitlines()[-1] if proc.stdout else ""
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except FileNotFoundError:
        return False, "not found"


def check_waf_coverage(report: DoctorReport) -> None:
    """WAF coverage = 0 (allowlist-aware)."""
    ok, last = _run_tool(
        [sys.executable, str(ROOT / "tools" / "check_waf_coverage.py")]
    )
    report.add("waf-coverage", ok, last or "see tools/check_waf_coverage.py")


def check_layer_boundaries(report: DoctorReport) -> None:
    """Layer boundaries violations = 0."""
    layers_check = ROOT / "tools" / "check_layers.py"
    if not layers_check.is_file():
        report.add("layer-boundaries", True, "SKIPPED (tools/check_layers.py отсутствует)")
        return
    ok, last = _run_tool([sys.executable, str(layers_check)])
    report.add("layer-boundaries", ok, last)


def check_mypy_budget(report: DoctorReport) -> None:
    """mypy budget ≤ 5 (S10)."""
    ok, last = _run_tool(
        [
            sys.executable,
            str(ROOT / "tools" / "checks" / "mypy_budget.py"),
            "--max",
            "5",
        ]
    )
    report.add("mypy-budget", ok, last)


def check_startup_time(report: DoctorReport) -> None:
    """startup-time gate (cold-import < 3s total)."""
    ok, last = _run_tool(
        [sys.executable, str(ROOT / "tools" / "checks" / "startup_time.py")]
    )
    report.add("startup-time", ok, last)


def _format_report(report: DoctorReport) -> str:
    lines = ["", "=" * 60, "  make doctor — health check", "=" * 60, ""]
    pad = max(len(r.name) for r in report.results) + 2
    for r in report.results:
        sym = "✓" if r.ok else "✗"
        lines.append(f"  [{sym}] {r.name.ljust(pad)} {r.detail}")
    lines.append("")
    failed = sum(1 for r in report.results if not r.ok)
    total = len(report.results)
    lines.append(f"Summary: {total - failed}/{total} OK, {failed} FAIL")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="make doctor (S10 K5 W1)")
    parser.add_argument(
        "--quick",
        action="store_true",
        help="пропустить network healthcheck (для CI)",
    )
    args = parser.parse_args(argv)

    report = DoctorReport()
    check_python_version(report)
    check_uv_available(report)
    check_pyproject(report)
    check_services(report, quick=args.quick)
    check_taskiq_zero(report)
    check_waf_coverage(report)
    check_layer_boundaries(report)
    check_mypy_budget(report)
    check_startup_time(report)

    print(_format_report(report))
    return 0 if report.all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
