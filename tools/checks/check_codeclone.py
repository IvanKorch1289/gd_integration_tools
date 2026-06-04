"""Codeclone CI gate — обнаружение дубликатов кода через jscpd или ASTcomp.

Назначение:
    Sprint 6 К1 wave [s6/k1-codeclone-strict]. Проверяет, нет ли новых
    клонов кода относительно baseline в ``tools/checks/codeclone_baseline.json``.

    Если ``--fail-on-new-clones`` и есть **новые** дубликаты сверх
    baseline — exit 1. Без флага — warn-only.

    Использует ``jscpd`` (preferred) или ``pylint --disable=all --enable=R0801``
    (duplicate-code check) как fallback.

Использование:
    python tools/checks/check_codeclone.py
    python tools/checks/check_codeclone.py --fail-on-new-clones

feature_flag: codeclone_fail_on_new (default-OFF до фиксации baseline).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

_DEFAULT_TARGET = Path("src/backend")
_DEFAULT_BASELINE = Path("tools/checks/codeclone_baseline.json")


def _check_tool_available() -> str | None:
    """Возвращает имя доступного tool: 'jscpd' / 'pylint' / None."""
    if shutil.which("jscpd") is not None:
        return "jscpd"
    if shutil.which("pylint") is not None:
        return "pylint"
    return None


def _load_baseline(path: Path) -> int:
    """Загружает baseline-счётчик клонов.

    Args:
        path: путь к JSON-baseline.

    Returns:
        количество клонов в baseline (или 0 если файл отсутствует).
    """
    if not path.exists():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return 0
    return int(data.get("clone_count", 0))


def run_jscpd(target: Path) -> int:
    """Запускает jscpd на target и возвращает количество клонов.

    Args:
        target: путь к коду для анализа.

    Returns:
        количество найденных клонов.
    """
    cmd = [
        "jscpd",
        "--reporters",
        "json",
        "--silent",
        "--format",
        "python",
        str(target),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
    out_dir = Path("report")
    json_report = out_dir / "jscpd-report.json"
    if json_report.exists():
        try:
            data = json.loads(json_report.read_text(encoding="utf-8"))
            return int(data.get("statistics", {}).get("total", {}).get("clones", 0))
        except (json.JSONDecodeError, KeyError):
            pass
    # fallback парсинг stdout
    for line in result.stdout.splitlines():
        if "Clones found:" in line:
            try:
                return int(line.split(":")[-1].strip())
            except ValueError:
                pass
    return 0


def run_pylint_duplicate(target: Path) -> int:
    """Fallback: pylint duplicate-code check.

    Args:
        target: путь к коду.

    Returns:
        количество найденных дубликатов (по R0801 messages).
    """
    cmd = [
        "pylint",
        "--disable=all",
        "--enable=R0801",
        "--output-format=text",
        str(target),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
    count = 0
    for line in result.stdout.splitlines():
        if "R0801" in line:
            count += 1
    return count


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="codeclone CI gate")
    parser.add_argument("--target", type=Path, default=_DEFAULT_TARGET)
    parser.add_argument("--baseline", type=Path, default=_DEFAULT_BASELINE)
    parser.add_argument(
        "--fail-on-new-clones",
        action="store_true",
        help="exit 1 если клонов больше чем в baseline",
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Перезаписать baseline текущим counter (после ручной проверки)",
    )
    args = parser.parse_args()

    tool = _check_tool_available()
    if tool is None:
        print("[SKIP] jscpd/pylint не установлены — codeclone check пропущен")
        return 0
    if not args.target.exists():
        print(f"[ERROR] target '{args.target}' не существует", file=sys.stderr)
        return 1

    print(f"[INFO] Running {tool} на {args.target}")
    if tool == "jscpd":
        current = run_jscpd(args.target)
    else:
        current = run_pylint_duplicate(args.target)
    baseline = _load_baseline(args.baseline)
    print(f"[INFO] Codeclones: current={current}, baseline={baseline}")

    if args.update_baseline:
        args.baseline.parent.mkdir(parents=True, exist_ok=True)
        args.baseline.write_text(
            json.dumps({"clone_count": current, "tool": tool}, indent=2),
            encoding="utf-8",
        )
        print(f"[OK] baseline updated в {args.baseline}: {current} clones")
        return 0

    new_clones = max(0, current - baseline)
    if args.fail_on_new_clones and new_clones > 0:
        print(f"[FAIL] {new_clones} новых клонов сверх baseline")
        return 1
    print(f"[OK] codeclone gate passed (current={current}, baseline={baseline})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
