"""Bandit с TLS-specific rules — поиск небезопасных TLS/SSL паттернов.

Назначение:
    Дополняет общий ``bandit -lll`` строгой проверкой TLS-rules:
    B501 (request_with_no_cert_validation), B502 (ssl_with_bad_version),
    B503 (ssl_with_bad_defaults), B504 (ssl_with_no_version),
    B505 (weak_cryptographic_key), B506 (yaml_load), B507 (ssh_no_host_key_verification).

    Соответствует V15 R-V15-5 / V1 (security constraint): запрещено
    ``ssl.CERT_NONE`` / ``check_hostname=False``.

Использование:
    python tools/checks/check_bandit_tls.py
    python tools/checks/check_bandit_tls.py --target src/backend

Возвращает exit 0 если 0 high-severity TLS violations, иначе exit 1.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

_TLS_RULES = ("B501", "B502", "B503", "B504", "B505", "B506", "B507")


def _check_bandit_available() -> None:
    """Проверяет наличие ``bandit`` в окружении (via python -m)."""
    result = subprocess.run(
        [sys.executable, "-m", "bandit", "--version"], capture_output=True, check=False
    )
    if result.returncode != 0:
        print(
            "[ERROR] 'bandit' не найден в окружении.\n"
            "  Установите: pip install bandit\n"
            "  Или используйте extras: pip install '.[security]'",
            file=sys.stderr,
        )
        sys.exit(1)


def run_bandit_tls(target: Path) -> int:
    """Запускает bandit с TLS-rules и возвращает количество high-severity findings.

    Args:
        target: путь к директории для анализа.

    Returns:
        количество high-severity TLS-нарушений (0 если чисто).
    """
    cmd = [
        sys.executable,
        "-m",
        "bandit",
        "-r",
        str(target),
        "-lll",
        "-q",
        "-f",
        "json",
        "--tests",
        ",".join(_TLS_RULES),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
    if result.returncode not in (0, 1):
        print(f"[ERROR] bandit exit code {result.returncode}", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        return -1

    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(
            f"[ERROR] bandit JSON parse failed:\n{result.stdout[:500]}", file=sys.stderr
        )
        return -1

    high_severity = [
        r for r in report.get("results", []) if r.get("issue_severity") == "HIGH"
    ]
    if high_severity:
        print(f"[FAIL] bandit-TLS: {len(high_severity)} HIGH-severity violations:")
        for finding in high_severity[:10]:
            print(
                f"  {finding.get('filename')}:{finding.get('line_number')} "
                f"[{finding.get('test_id')}] {finding.get('issue_text')[:120]}"
            )
        if len(high_severity) > 10:
            print(f"  ... и ещё {len(high_severity) - 10} нарушений")
    else:
        print("[OK] bandit-TLS: 0 HIGH-severity TLS violations")

    return len(high_severity)


def main() -> int:
    """CLI entry point.

    Returns:
        0 если чисто, 1 если есть нарушения, -1 при ошибке bandit.
    """
    parser = argparse.ArgumentParser(description="bandit с TLS-specific rules")
    parser.add_argument(
        "--target",
        type=Path,
        default=Path("src/backend"),
        help="Путь к коду для анализа",
    )
    args = parser.parse_args()
    _check_bandit_available()

    if not args.target.exists():
        print(f"[ERROR] target '{args.target}' не существует", file=sys.stderr)
        return 1

    violations = run_bandit_tls(args.target)
    return 0 if violations == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
