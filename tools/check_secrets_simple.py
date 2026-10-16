"""Secret-leakage detector (S173 M8.4 — DX/security).

Lightweight pre-commit hook для pre-push security gate. Detects
common secret patterns в source code (PEM blocks, JWT, AWS, generic
API key).

Additive — не заменяет existing ``detect-secrets`` (который уже в
pre-commit chain per V22). M8.4 = **диагностический** gate: полезен
если ``detect-secrets`` отключён или пропускает новые patterns.

Usage::

    uv run python tools/check_secrets_simple.py
    uv run python tools/check_secrets_simple.py --strict

Exit codes:
    0 — no findings (или только info-level).
    1 — findings (high-confidence patterns).
    2 — invocation error.

Cumulative: a3bb7acc → ... → ab5f500c (M8.3) → M8.4.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import NamedTuple

_ROOT = Path(__file__).resolve().parents[1]

# S173 M8.4: directory allowlist (NE scan in venvs/build artifacts).
_SCAN_DIRS: tuple[str, ...] = ("src", "tests", "tools")

# 2026-10-16: allowlist опубликованных вендорами демо-значений.
# Содержит не «известные секреты», а заведомо не-секреты; каждая строка
# проверена вручную (см. обоснование в самом файле).
_ALLOWLIST_FILE = _ROOT / "tools" / "check_secrets_simple_allowlist.txt"

# S173 M8.4: high-confidence secret patterns.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    (
        "aws_secret_key",
        re.compile(
            r"(?i)aws[_\-]?secret[_\-]?(?:access[_\-]?)?key"
            r"[\s\"':=]+([A-Za-z0-9/+=]{40})"
        ),
    ),
    ("github_pat", re.compile(r"ghp_[A-Za-z0-9]{36}")),
    (
        "private_key_pem",
        # 2026-10-16: матчится строка-заголовок; требует наличия реального
        # base64-тела в файле (проверяется _pem_material_lines). Раньше ловилась
        # одна строка заголовка, из-за чего срабатывали пустые заглушки
        # ``b"-----BEGIN PRIVATE KEY-----\n"``, ``FAKE``/``FAKE_KEY`` и даже
        # ``assert b"-----BEGIN PRIVATE KEY-----" in chain.key_pem``.
        re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |)PRIVATE KEY-----"),
    ),
    ("jwt_token", re.compile(r"eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")),
    ("slack_token", re.compile(r"xox[abposr]-[A-Za-z0-9-]{10,48}")),
    ("stripe_key", re.compile(r"(?:sk|pk)_(?:live|test)_[0-9a-zA-Z]{24,}")),
)


# Полный PEM-блок с base64-материалом. Применяется к файлу целиком,
# потому что построчный scan (ниже) физически не может увидеть тело ключа,
# лежащее на следующих строках.
_PEM_BLOCK = re.compile(
    r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |)PRIVATE KEY-----[ \t]*\r?\n"
    r"(?:[A-Za-z0-9+/=]{32,}[ \t]*\r?\n)+"
    r"-----END (?:RSA |EC |DSA |OPENSSH |)PRIVATE KEY-----"
)


def _pem_material_lines(text: str) -> set[int]:
    """Номера строк (1-based), входящих в PEM-блоки с реальным материалом.

    Пустые заглушки (``...-----\\n-----END``) и ``FAKE``/``FAKE_KEY``
    сюда не попадают — у них нет base64-тела длиной 32+ символа.
    """
    lines: set[int] = set()
    for match in _PEM_BLOCK.finditer(text):
        start_line = text.count("\n", 0, match.start())
        end_line = text.count("\n", 0, match.end())
        lines.update(range(start_line + 1, end_line + 2))
    return lines


class Finding(NamedTuple):
    pattern_name: str
    file: Path
    line: int
    match: str


def _scan_file(path: Path) -> list[Finding]:
    """Return list of :class:`Finding` для file."""
    findings: list[Finding] = []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError, PermissionError:
        return findings
    pem_material = _pem_material_lines(text)
    for lineno, line in enumerate(text.splitlines(), start=1):
        for name, pattern in _PATTERNS:
            match = pattern.search(line)
            if match:
                # 2026-10-16: заголовок PEM без тела — не секрет. Пропускаем,
                # если файл не содержит ни одного PEM-блока с материалом
                # (пустые заглушки, assert-строки, FAKE-заглушки).
                if name == "private_key_pem" and lineno not in pem_material:
                    continue
                findings.append(
                    Finding(
                        pattern_name=name,
                        file=path,
                        line=lineno,
                        match=match.group(0)[:50]
                        + ("..." if len(match.group(0)) > 50 else ""),
                    )
                )
    return findings


def _iter_python_files() -> list[Path]:
    files: list[Path] = []
    for d in _SCAN_DIRS:
        target = _ROOT / d
        if not target.exists():
            continue
        files.extend(p for p in target.rglob("*.py") if p.is_file())
    return files


def _load_allowlist() -> set[tuple[str, int, str]]:
    """Прочитать allowlist: ``<path>:<lineno> <pattern_name>`` → set.

    Строки-комментарии и пустые игнорируются. Файл опционален: без него
    инструмент работает как раньше (allowlist пустой).
    """
    if not _ALLOWLIST_FILE.exists():
        return set()
    entries: set[tuple[str, int, str]] = set()
    for raw in _ALLOWLIST_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        location, _, rest = line.partition(" ")
        if "—" in rest:  # обоснование после em-dash отбрасываем
            pattern_name = rest.split("—")[0].strip()
        else:
            pattern_name = rest.split()[0] if rest.split() else ""
        path_part, _, lineno_part = location.rpartition(":")
        if not path_part or not lineno_part.isdigit():
            continue
        entries.add((path_part.strip(), int(lineno_part), pattern_name))
    return entries


def _apply_allowlist(findings: list[Finding]) -> list[Finding]:
    """Отфильтровать findings, покрытые allowlist'ом.

    Находка считается allowlisted'ом, если совпадают путь, номер строки
    И имя паттерна. Совпадение только по пути недостаточно — иначе
    allowlist одной строки скрыл бы новую утечку в соседней строке.
    """
    allowed = _load_allowlist()
    if not allowed:
        return findings
    kept: list[Finding] = []
    for f in findings:
        rel = f.file.relative_to(_ROOT)
        if (str(rel), f.line, f.pattern_name) in allowed:
            continue
        kept.append(f)
    return kept


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="S173 M8.4 / S176 M11.3 — simple secret-leakage detector"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Strict mode: exit 1 на любом finding (CI gate).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON для CI integration (S176 M11.3).",
    )
    args = parser.parse_args(argv)

    findings: list[Finding] = []
    for path in _iter_python_files():
        findings.extend(_scan_file(path))

    findings = _apply_allowlist(findings)

    if args.json:
        # S176 M11.3: JSON output mode для CI integration.
        import json as _json

        # Group findings по pattern_name для JSON aggregation.
        by_pattern: dict[str, int] = {}
        for f in findings:
            by_pattern[f.pattern_name] = by_pattern.get(f.pattern_name, 0) + 1
        payload = {
            "scanned_dirs": list(_SCAN_DIRS),
            "files_scanned": len(_iter_python_files()),
            "total_findings": len(findings),
            "by_pattern": by_pattern,
            "findings": [
                {
                    "pattern": f.pattern_name,
                    "file": str(f.file.relative_to(_ROOT)),
                    "line": f.line,
                    "match": f.match,
                }
                for f in findings
            ],
        }
        print(_json.dumps(payload, indent=2, ensure_ascii=False))
    elif findings:
        for f in findings[:20]:
            rel = f.file.relative_to(_ROOT)
            print(f"[{f.pattern_name}] {rel}:{f.line}: {f.match}", file=sys.stderr)
        if len(findings) > 20:
            print(f"... и ещё {len(findings) - 20} findings", file=sys.stderr)

    if args.strict and findings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
