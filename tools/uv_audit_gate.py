#!/usr/bin/env python3
"""Gate аудита всего lock-файла: ``uv audit --frozen`` (ADR-0385, A6).

Зачем
-----
Job ``pip-audit`` в CI сканировал только default-venv (``uv sync``) —
41 из 117 уязвимостей в extras не проверялись. ``uv audit --frozen``
разбирает весь ``uv.lock`` (все extras) без установки пакетов.

Как работает
------------
1. ``uv audit --frozen`` печатает текстовый отчёт (JSON-вывода у uv нет);
2. гейт извлекает advisory-ID (строки вида ``- GHSA-…:`` / ``- PYSEC-…:``);
3. ID, перечисленные в canonical allowlist
   (``.security/uv-audit-allowlist.txt``), считаются известным долгом;
4. ЛЮБОЙ новый ID (нет в allowlist) → exit 1 (блокирующий гейт).

Fail-closed: отсутствующий отчёт, пустой отчёт или отсутствующий
allowlist — exit 1 (молчаливый «зелёный» гейт опаснее отсутствия гейта).

Использование::

    uv audit --frozen > uv-audit.txt 2>&1 || true
    uv run python tools/uv_audit_gate.py --report uv-audit.txt
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

__all__ = ("extract_advisory_ids", "load_allowlist", "run_gate")

#: Advisory-ID в текстовом отчёте ``uv audit``: ``- GHSA-xxxx-yyyy-zzzz: …``.
_ADVISORY_RE = re.compile(r"^-\s+((?:GHSA|PYSEC|CVE)-[A-Za-z0-9-]+):", re.MULTILINE)

#: Canonical allowlist известного долга.
DEFAULT_ALLOWLIST = Path(".security") / "uv-audit-allowlist.txt"

#: Отчёт по умолчанию (создаётся шагом CI рядом с гейтом).
DEFAULT_REPORT = Path("uv-audit.txt")


def extract_advisory_ids(report: str) -> set[str]:
    """Извлечь advisory-ID из текстового отчёта ``uv audit``.

    Args:
        report: Текст отчёта.

    Returns:
        Множество advisory-ID (``GHSA-*``/``PYSEC-*``/``CVE-*``).

    """
    return set(_ADVISORY_RE.findall(report))


def load_allowlist(path: Path) -> set[str]:
    """Загрузить canonical allowlist (одна ID на строку).

    Args:
        path: Путь к allowlist-файлу.

    Returns:
        Множество известных advisory-ID. Пустое множество, если файла нет.

    """
    if not path.is_file():
        return set()
    ids: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.split("#", 1)[0].strip()
        if stripped:
            ids.add(stripped)
    return ids


def run_gate(report_path: Path, allowlist_path: Path) -> int:
    """Проверить отчёт ``uv audit`` против canonical allowlist.

    Args:
        report_path: Путь к текстовому отчёту ``uv audit``.
        allowlist_path: Путь к canonical allowlist.

    Returns:
        ``0`` — новых advisory нет; ``1`` — есть новые (или отчёт/allowlist
        недоступны — fail-closed).

    """
    if not report_path.is_file():
        print(
            f"ERROR: отчёт {report_path} не найден — гейт fail-closed "
            "(сначала выполните `uv audit --frozen`)",
            file=sys.stderr,
        )
        return 1

    report = report_path.read_text(encoding="utf-8", errors="replace")
    found = extract_advisory_ids(report)
    if not found:
        print(
            "ERROR: в отчёте нет ни одной advisory-строки — гейт fail-closed",
            file=sys.stderr,
        )
        return 1

    if not allowlist_path.is_file():
        print(
            f"ERROR: allowlist {allowlist_path} не найден — гейт fail-closed",
            file=sys.stderr,
        )
        return 1

    known = load_allowlist(allowlist_path)
    new_ids = sorted(found - known)
    print(
        f"uv audit: {len(found)} advisory, allowlist: {len(known)}, новых: {len(new_ids)}"
    )
    if new_ids:
        print("FAIL: новые advisory-ID (не в allowlist):", file=sys.stderr)
        for advisory_id in new_ids:
            print(f"  - {advisory_id}", file=sys.stderr)
        print(
            "Обновите зависимость до исправленной версии либо внесите ID в "
            f"{allowlist_path} с обоснованием.",
            file=sys.stderr,
        )
        return 1

    print("PASS: новых advisory-ID нет")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI.

    Args:
        argv: Аргументы командной строки (по умолчанию — ``sys.argv[1:]``).

    Returns:
        Exit code гейта.

    """
    parser = argparse.ArgumentParser(
        description="Gate аудита всего lock-файла (uv audit --frozen)."
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT,
        help=f"Текстовый отчёт uv audit (по умолчанию: {DEFAULT_REPORT}).",
    )
    parser.add_argument(
        "--allowlist",
        type=Path,
        default=DEFAULT_ALLOWLIST,
        help=f"Canonical allowlist (по умолчанию: {DEFAULT_ALLOWLIST}).",
    )
    args = parser.parse_args(argv)
    return run_gate(args.report, args.allowlist)


if __name__ == "__main__":
    raise SystemExit(main())
