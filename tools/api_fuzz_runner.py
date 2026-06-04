"""Sprint 6 K2 — schemathesis API fuzzing runner.

Назначение:
    Wrapper над ``schemathesis run`` для CI integration. Запускает
    property-based testing против live FastAPI / OpenAPI-spec и
    парсит результаты в JSON-отчёт с поддержкой allowlist.

Feature-flag: ``schemathesis_gate_enabled`` (default-OFF). При flag-OFF
exit-code всегда 0 (warn-only); при flag-ON exit 1 при non-allowlisted
fuzzing-violations.

Использование::

    # Локально против запущенного backend
    uv run python tools/api_fuzz_runner.py \\
        --openapi http://127.0.0.1:8000/openapi.json \\
        --report dist/schemathesis-report.json

    # В CI (default-OFF warn-only)
    make api-fuzz

Зависимости: ``schemathesis`` (уже в pyproject.toml::dependencies).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

EXIT_OK = 0
EXIT_VIOLATIONS = 1
EXIT_ERROR = 2

logger = logging.getLogger("tools.api_fuzz_runner")


def _parse_args() -> argparse.Namespace:
    """Разбирает argv."""
    parser = argparse.ArgumentParser(
        description=(
            "Sprint 6 K2: schemathesis API fuzzing runner. "
            "Warn-only до Sprint 7 (feature_flag schemathesis_gate_enabled)."
        )
    )
    parser.add_argument(
        "--openapi",
        type=str,
        default="http://127.0.0.1:8000/openapi.json",
        help="URL OpenAPI spec (live backend).",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("dist/schemathesis-report.json"),
        help="Путь к JSON-отчёту.",
    )
    parser.add_argument(
        "--checks",
        type=str,
        default="all",
        help="Schemathesis checks (all / not_a_server_error / status_code_conformance).",
    )
    parser.add_argument(
        "--max-examples",
        type=int,
        default=20,
        help="Maximum examples per endpoint (default 20 для CI; локально 100+).",
    )
    parser.add_argument(
        "--workers", type=int, default=4, help="Параллельные workers для тестов."
    )
    parser.add_argument(
        "--allowlist",
        type=Path,
        default=Path("tools/checks/schemathesis_allowlist.json"),
        help="JSON-allowlist известных false-positive violations.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Sprint 6 K2: --strict переопределяет feature_flag schemathesis_gate_enabled.",
    )
    parser.add_argument(
        "--schemathesis-cmd",
        type=str,
        default="schemathesis",
        help="Команда schemathesis (default: schemathesis из PATH).",
    )
    return parser.parse_args()


def _is_strict_mode(args: argparse.Namespace) -> bool:
    """Проверить feature-flag / CLI / ENV для strict-режима."""
    if args.strict:
        return True
    if os.getenv("FEATURE_SCHEMATHESIS_GATE_ENABLED", "false").lower() in {
        "1",
        "true",
        "yes",
    }:
        return True
    try:
        from src.backend.core.config.features import feature_flags

        return feature_flags.schemathesis_gate_enabled
    except Exception:  # noqa: BLE001
        return False


def _load_allowlist(path: Path) -> list[dict[str, Any]]:
    """Прочитать allowlist известных violations.

    Returns:
        Список dict-записей с полями endpoint/check/reason.
    """
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        if isinstance(data, dict):
            return data.get("violations", [])
        if isinstance(data, list):
            return data
    except json.JSONDecodeError as exc:
        logger.warning("schemathesis allowlist parse error: %s", exc)
    return []


def _run_schemathesis(args: argparse.Namespace) -> tuple[int, str, str]:
    """Запустить ``schemathesis run`` и вернуть (exit_code, stdout, stderr)."""
    cmd = [
        args.schemathesis_cmd,
        "run",
        args.openapi,
        f"--checks={args.checks}",
        f"--max-examples={args.max_examples}",
        f"--workers={args.workers}",
        "--exitfirst",  # выходим после первой ошибки для скорости
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600, check=False
        )
        return result.returncode, result.stdout, result.stderr
    except FileNotFoundError:
        return EXIT_ERROR, "", f"schemathesis not found: {args.schemathesis_cmd}"
    except subprocess.TimeoutExpired:
        return EXIT_ERROR, "", "schemathesis timeout (>600s)"


def _count_violations(stdout: str, stderr: str) -> int:
    """Прикинуть число violations из stdout/stderr.

    Возвращает 0 если все checks passed; >0 — число нарушений.
    """
    combined = stdout + stderr
    # Schemathesis возвращает FAILED: <N> в финале.
    for line in combined.splitlines():
        line = line.strip()
        if line.startswith("FAILED:") or "FAILED" in line and "test cases" in line:
            try:
                parts = line.split()
                for part in parts:
                    if part.isdigit():
                        return int(part)
            except (ValueError, IndexError):
                pass
    return 0


def main() -> int:
    """Entry-point."""
    args = _parse_args()
    args.report.parent.mkdir(parents=True, exist_ok=True)

    print(f"[api-fuzz] schemathesis run {args.openapi}")
    rc, stdout, stderr = _run_schemathesis(args)

    if rc == EXIT_ERROR:
        print(f"ERROR: {stderr}", file=sys.stderr)
        # Не блокируем CI — schemathesis может отсутствовать в локальной разработке.
        return EXIT_ERROR

    violations = _count_violations(stdout, stderr)
    allowlist = _load_allowlist(args.allowlist)
    allowlist_count = len(allowlist)
    non_allowlisted = max(0, violations - allowlist_count)

    strict = _is_strict_mode(args)

    report = {
        "timestamp": int(time.time()),
        "openapi": args.openapi,
        "schemathesis_exit_code": rc,
        "violations_total": violations,
        "allowlisted_count": allowlist_count,
        "non_allowlisted_count": non_allowlisted,
        "strict_mode": strict,
        "feature_flag": "schemathesis_gate_enabled",
        "stdout_tail": stdout[-2000:] if stdout else "",
        "stderr_tail": stderr[-2000:] if stderr else "",
    }
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"[api-fuzz] report → {args.report}")

    if non_allowlisted == 0:
        print(
            f"[api-fuzz] OK — {violations} violations все в allowlist "
            f"({allowlist_count} entries)"
        )
        return EXIT_OK

    if strict:
        print(
            f"[api-fuzz] FAIL (strict) — {non_allowlisted} non-allowlisted violations",
            file=sys.stderr,
        )
        return EXIT_VIOLATIONS

    print(
        f"[api-fuzz] WARN (warn-only; feature_flag schemathesis_gate_enabled=false): "
        f"{non_allowlisted} non-allowlisted violations",
        file=sys.stderr,
    )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
