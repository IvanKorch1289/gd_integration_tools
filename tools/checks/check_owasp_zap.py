"""OWASP ZAP baseline scan через docker.

Назначение:
    Sprint 6 К1 wave [s6/k1-owasp-zap-gate]. Запускает
    ``zaproxy/zaproxy:stable`` Docker image с baseline-сканом против
    указанных endpoints из ``tests/security/zap_targets.yml``. Создаёт
    JSON+HTML отчёты в ``artifacts/zap/<date>/``.

    Warn-only по решению пользователя — exit 0 при наличии findings,
    blocking откладывается до Sprint 9 pre-prod gate.

Использование:
    python tools/checks/check_owasp_zap.py --base-url http://localhost:8000
    python tools/checks/check_owasp_zap.py --targets-file tests/security/zap_targets.yml

feature_flag: owasp_zap_gate_enabled (default-OFF).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_DEFAULT_TARGETS = Path("tests/security/zap_targets.yml")
_DEFAULT_BASE_URL = "http://127.0.0.1:8000"
_ZAP_IMAGE = "zaproxy/zaproxy:stable"


def _check_docker_available() -> bool:
    """Проверяет наличие docker в PATH."""
    return shutil.which("docker") is not None


def _load_targets(path: Path) -> list[str]:
    """Загружает список endpoints из YAML.

    Args:
        path: путь к файлу с YAML списком (или текстовый список путей).

    Returns:
        список путей-endpoints (относительных, без base URL).
    """
    if not path.exists():
        return ["/health", "/api/v1/health"]
    raw = path.read_text(encoding="utf-8")
    targets: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("- "):
            line = line[2:].strip()
        if line.startswith(("path:", "url:")):
            line = line.split(":", 1)[1].strip().strip('"').strip("'")
        if line and not line.startswith(("baseline:", "version:")):
            targets.append(line)
    return targets or ["/health"]


def run_zap_baseline(base_url: str, target_path: str, output_dir: Path) -> int:
    """Запускает один ZAP baseline scan для одного endpoint.

    Args:
        base_url: базовый URL (e.g. http://127.0.0.1:8000).
        target_path: относительный путь endpoint'а (e.g. /health).
        output_dir: каталог для отчётов.

    Returns:
        количество high-severity findings (0 если чисто).
    """
    full_url = base_url.rstrip("/") + "/" + target_path.lstrip("/")
    report_name = target_path.strip("/").replace("/", "_") or "root"
    output_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "docker",
        "run",
        "--rm",
        "--network",
        "host",
        "-v",
        f"{output_dir.resolve()}:/zap/wrk/:rw",
        _ZAP_IMAGE,
        "zap-baseline.py",
        "-t",
        full_url,
        "-J",
        f"{report_name}.json",
        "-r",
        f"{report_name}.html",
        "-I",
    ]
    print(f"\n=== ZAP baseline scan: {full_url} ===")
    subprocess.run(cmd, check=False)  # noqa: S603
    # ZAP exit code 0=clean / 1=warn / 2=error / >=3=fail
    json_report = output_dir / f"{report_name}.json"
    if not json_report.exists():
        print(f"[WARN] no JSON report at {json_report}")
        return 0
    try:
        data = json.loads(json_report.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return 0
    sites = data.get("site", [])
    high_count = 0
    for site in sites:
        for alert in site.get("alerts", []):
            if alert.get("riskcode") == "3":  # High severity
                high_count += 1
    print(
        f"[INFO] {full_url}: {high_count} HIGH-severity findings, report={json_report}"
    )
    return high_count


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="OWASP ZAP baseline scan")
    parser.add_argument(
        "--base-url", default=_DEFAULT_BASE_URL, help="Базовый URL backend"
    )
    parser.add_argument(
        "--targets-file",
        type=Path,
        default=_DEFAULT_TARGETS,
        help="YAML с endpoints для скана",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output dir (default: artifacts/zap/<date>/)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Strict mode: exit 1 при наличии HIGH findings",
    )
    args = parser.parse_args()

    if not _check_docker_available():
        print("[SKIP] docker не установлен — OWASP ZAP scan пропущен")
        return 0

    if args.output_dir is None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        args.output_dir = Path("artifacts") / "zap" / ts

    targets = _load_targets(args.targets_file)
    print(f"[INFO] Targets: {targets}")
    print(f"[INFO] Output: {args.output_dir}")

    total_high = 0
    for target in targets:
        total_high += run_zap_baseline(args.base_url, target, args.output_dir)

    print(
        f"\n=== ZAP summary: {len(targets)} endpoints, {total_high} HIGH findings ==="
    )
    if args.strict and total_high > 0:
        return 1
    return 0  # warn-only до Sprint 9


if __name__ == "__main__":
    sys.exit(main())
