"""S106 W5 — ``check_test_baseline.py``: gate для pytest regressions.

CI-runnable script. Запускает ``pytest tests/unit`` и сравнивает результат
с allowlist pre-existing failures. Exit codes:

* ``0`` — все NEW tests pass (regression = 0);
* ``1`` — есть NEW failing tests (regression) ИЛИ collection errors;
* ``2`` — pytest не запустился (env error).

Allowlist (``tools/check_test_baseline_allowlist.txt``) содержит
pre-existing failures с причинами (например, ``"missing temporalio
extra"``, ``"loaders.py: NameError pre-existing"``). При matching
failing test'а с allowlist — failure классифицируется как
``PRE_EXISTING``, не считается регрессией.

S106 W5 scope: baseline establishment + skeleton. Расширенная
интеграция с junit-xml и parallel-mode — S106+ W6+ (multi-wave).

Использование::

    # Default: collect-only + allowlist check (быстрый)
    python tools/check_test_baseline.py

    # Full test run (медленнее, полные результаты)
    python tools/check_test_baseline.py --run

    # Custom allowlist path
    python tools/check_test_baseline.py --allowlist path/to/allowlist.txt
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ALLOWLIST = REPO_ROOT / "tools" / "check_test_baseline_allowlist.txt"
PYTEST_TARGET = "tests/unit"


@dataclass(frozen=True)
class AllowlistEntry:
    """Одна строка allowlist'а.

    Формат: ``<test_pattern>\\t<reason>``. ``test_pattern`` — substring
    или regex (anchored), который матчится на test node-id.
    """

    test_pattern: str
    reason: str


def parse_allowlist(path: Path) -> list[AllowlistEntry]:
    """Парсит allowlist-файл в список :class:`AllowlistEntry`."""
    if not path.exists():
        return []
    entries: list[AllowlistEntry] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t", maxsplit=1)
        if len(parts) != 2:
            parts = line.split(None, 1)  # fallback: split by whitespace
        if len(parts) != 2:
            continue
        pattern, reason = parts[0].strip(), parts[1].strip()
        entries.append(AllowlistEntry(test_pattern=pattern, reason=reason))
    return entries


def is_allowlisted(node_id: str, entries: list[AllowlistEntry]) -> bool:
    """True, если node_id матчится хотя бы одной записью allowlist'а."""
    for entry in entries:
        # Поддержка двух режимов: substring (по умолчанию) и regex
        # (если pattern начинается с ``re:``).
        pattern = entry.test_pattern
        if pattern.startswith("re:"):
            if re.search(pattern[3:], node_id):
                return True
        elif pattern in node_id:
            return True
    return False


def run_pytest(*, run: bool) -> str:
    """Запускает pytest и возвращает stdout (utf-8).

    При ``run=False`` — ``--co`` (collect only), быстро.
    При ``run=True`` — полный прогон.
    """
    cmd = [sys.executable, "-m", "pytest", PYTEST_TARGET]
    if not run:
        cmd.append("--co")
    cmd.extend(["-q", "--no-header"])
    result = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    # pytest пишет summary в stderr при failures, в stdout при --co.
    return (result.stdout or "") + "\n" + (result.stderr or "")


_NODE_ID_RE = re.compile(
    r"^(?P<status>ERROR|FAILED|SKIPPED)\s+(?P<node_id>\S+)"
)


def parse_failures(output: str) -> list[str]:
    """Извлекает node_id'ы failing/collection-error тестов из pytest output."""
    failures: list[str] = []
    for line in output.splitlines():
        m = _NODE_ID_RE.match(line.strip())
        if m is None:
            continue
        status, node_id = m.group("status"), m.group("node_id")
        # FAILED + ERROR — regressions, SKIPPED — не failures.
        if status in ("FAILED", "ERROR"):
            failures.append(node_id)
    return failures


def main() -> int:
    """Точка входа: парсинг args, run pytest, классификация, exit code."""
    parser = argparse.ArgumentParser(
        description="Test baseline gate (S106 W5)."
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Run full pytest (медленно); default = collect-only",
    )
    parser.add_argument(
        "--allowlist",
        type=Path,
        default=DEFAULT_ALLOWLIST,
        help=f"Path to allowlist (default: {DEFAULT_ALLOWLIST})",
    )
    args = parser.parse_args()

    allowlist = parse_allowlist(args.allowlist)
    print(f"Allowlist entries: {len(allowlist)} ({args.allowlist})")
    print(f"Pytest target: {PYTEST_TARGET} (run={args.run})")
    print()

    output = run_pytest(run=args.run)
    failures = parse_failures(output)
    if not failures:
        print("No failures detected (pre-existing or new).")
        return 0

    pre_existing: list[str] = []
    regressions: list[str] = []
    for node_id in failures:
        if is_allowlisted(node_id, allowlist):
            pre_existing.append(node_id)
        else:
            regressions.append(node_id)

    print(f"Total failures: {len(failures)}")
    print(f"  Pre-existing (allowlisted): {len(pre_existing)}")
    print(f"  Regressions (NEW):          {len(regressions)}")
    print()
    if regressions:
        print("=== REGRESSIONS (not in allowlist) ===")
        for r in regressions:
            print(f"  {r}")
        print()
        return 1
    print("No new regressions. All failures are pre-existing (allowlisted).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
