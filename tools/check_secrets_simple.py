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

# S173 M8.4: high-confidence secret patterns.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "aws_access_key",
        re.compile(r"AKIA[0-9A-Z]{16}"),
    ),
    (
        "aws_secret_key",
        re.compile(
            r"(?i)aws[_\-]?secret[_\-]?(?:access[_\-]?)?key"
            r"[\s\"':=]+([A-Za-z0-9/+=]{40})"
        ),
    ),
    (
        "github_pat",
        re.compile(r"ghp_[A-Za-z0-9]{36}"),
    ),
    (
        "private_key_pem",
        re.compile(
            r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |)PRIVATE KEY-----"
        ),
    ),
    (
        "jwt_token",
        re.compile(r"eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),
    ),
    (
        "slack_token",
        re.compile(r"xox[abposr]-[A-Za-z0-9-]{10,48}"),
    ),
    (
        "stripe_key",
        re.compile(r"(?:sk|pk)_(?:live|test)_[0-9a-zA-Z]{24,}"),
    ),
)


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
    except (OSError, PermissionError):
        return findings
    for lineno, line in enumerate(text.splitlines(), start=1):
        for name, pattern in _PATTERNS:
            match = pattern.search(line)
            if match:
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="S173 M8.4 — simple secret-leakage detector"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Strict mode: exit 1 на любом finding (CI gate).",
    )
    args = parser.parse_args(argv)

    findings: list[Finding] = []
    for path in _iter_python_files():
        findings.extend(_scan_file(path))

    if findings:
        for f in findings[:20]:
            rel = f.file.relative_to(_ROOT)
            print(
                f"[{f.pattern_name}] {rel}:{f.line}: {f.match}",
                file=sys.stderr,
            )
        if len(findings) > 20:
            print(
                f"... и ещё {len(findings) - 20} findings",
                file=sys.stderr,
            )

    if args.strict and findings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
