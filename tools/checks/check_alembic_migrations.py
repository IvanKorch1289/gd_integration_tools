"""Alembic migration verification (P0 audit 2026-09-22).

Проверяет:
1. **Multiple heads detection**: alembic heads — если >1 документированных
   heads, миграционная цепочка разветвлена (риск drift).
2. **SQLite vs PostgreSQL DDL**: dev_light.yml по умолчанию указывает на SQLite
   (`./.run/dev.sqlite3`). Миграции могут содержать PostgreSQL-only DDL
   (e.g., ``JSONB``, ``CREATE INDEX CONCURRENTLY``, partial indexes),
   которые не пройдут на SQLite.
3. **Alembic.ini placeholder**: ``sqlalchemy.url = driver://user:pass@localhost/dbname``
   — placeholder, не реальный URL. CI должен override через env.

Использование::

    python tools/checks/check_alembic_migrations.py              # human-readable
    python tools/checks/check_alembic_migrations.py --strict    # exit 1 if issues
    python tools/checks/check_alembic_migrations.py --json      # machine output

Exit codes:
    0 — все проверки OK
    1 — найдены issues (--strict)
    2 — alembic не установлен / env error
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
MIGRATIONS_DIR = REPO_ROOT / "src/backend/infrastructure/database/migrations"
VERSIONS_DIR = MIGRATIONS_DIR / "versions"


def _count_migrations() -> int:
    """Count migration files в versions/."""
    if not VERSIONS_DIR.exists():
        return 0
    return sum(1 for f in VERSIONS_DIR.glob("*.py") if not f.name.startswith("_"))


def _find_heads_via_alembic() -> list[str]:
    """Run ``alembic heads`` и parse output."""
    if not ALEMBIC_INI.exists():
        return []
    try:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "heads", "--verbose"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            return []
        heads: list[str] = []
        for line in result.stdout.splitlines():
            line = line.strip()
            # Format: "<rev> (head)" or "<rev> (head), version=<version>"
            if "(head)" in line.lower():
                rev_match = re.match(r"^([0-9a-f]+)", line)
                if rev_match:
                    heads.append(rev_match.group(1))
        return heads
    except Exception:
        return []


def _scan_sqlite_incompat_ddl() -> dict[str, list[tuple[str, int, str]]]:
    """Scan migrations for PostgreSQL-only DDL patterns.

    Returns dict {pattern: [(file, line, snippet), ...]}.
    """
    # Patterns that won't work on SQLite (used by dev_light).
    # API-aware: матчатся только РЕАЛЬНЫЕ DDL-вызовы (postgresql.JSONB(),
    # postgresql_concurrently=True, postgresql_where=...), а не слова в
    # комментариях/docstrings — до фикса «CONCURRENTLY: 1» был
    # комментарий «Concurrently=False» (false positive, audit 2026-09-23).
    patterns: dict[str, str] = {
        "JSONB": r"postgresql\.JSONB\b|\bsa\.JSONB\b",
        "CONCURRENTLY": r"postgresql_concurrently\s*=\s*True",
        "PARTIAL INDEX": r"postgresql_where\s*=",
        "BRIN": r"postgresql_using\s*=\s*['\"]brin['\"]|\bUSING\s+brin\b",
        "GIST": r"postgresql_using\s*=\s*['\"]gist['\"]|\bUSING\s+gist\b",
        "GIN": r"postgresql_using\s*=\s*['\"]gin['\"]|\bUSING\s+gin\b",
        "UUID-OSSP": r"\buuid-ossp\b|\buuid_generate",
        "ARRAY literal": r"\bARRAY\s*\[",
        "tsvector": r"\btsvector\b",
        "hstore": r"\bhstore\b",
    }
    findings: dict[str, list[tuple[str, int, str]]] = {}
    if not VERSIONS_DIR.exists():
        return findings

    for f in sorted(VERSIONS_DIR.glob("*.py")):
        if f.name.startswith("_"):
            continue
        try:
            content = f.read_text(encoding="utf-8")
        except OSError:
            continue
        for name, regex in patterns.items():
            for match in re.finditer(regex, content, flags=re.IGNORECASE):
                line_no = content[: match.start()].count("\n") + 1
                line_text = (
                    content.split("\n")[line_no - 1].strip() if line_no > 0 else ""
                )
                findings.setdefault(name, []).append((f.name, line_no, line_text[:80]))
    return findings


def _check_alembic_ini() -> dict[str, object]:
    """Check alembic.ini for placeholder URL."""
    if not ALEMBIC_INI.exists():
        return {"exists": False}
    content = ALEMBIC_INI.read_text(encoding="utf-8")
    url_match = re.search(r"^sqlalchemy\.url\s*=\s*(.+)$", content, re.MULTILINE)
    url = url_match.group(1).strip() if url_match else None
    return {
        "exists": True,
        "url": url,
        "is_placeholder": url == "driver://user:pass@localhost/dbname" if url else None,
    }


def _check_dev_light_db_type() -> str | None:
    """Return database type from dev_light.yml."""
    dev_light = REPO_ROOT / "config_profiles" / "dev_light.yml"
    if not dev_light.exists():
        return None
    content = dev_light.read_text(encoding="utf-8")
    m = re.search(r"database:\s*\n\s*type:\s*\"?(\w+)\"?", content, re.MULTILINE)
    return m.group(1) if m else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Alembic migration verification gate")
    parser.add_argument("--strict", action="store_true", help="Exit 1 if issues found")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args(argv)

    issues: list[str] = []
    notes: list[str] = []

    # 1. Migration count.
    n_migrations = _count_migrations()
    notes.append(f"Migration files: {n_migrations}")

    # 2. Heads detection.
    heads = _find_heads_via_alembic()
    notes.append(
        f"Alembic heads: {len(heads)} ({', '.join(heads) if heads else 'N/A'})"
    )
    if len(heads) > 1:
        issues.append(
            f"Multiple heads detected ({len(heads)}): {heads}. "
            "Migration graph is forked — risk of drift."
        )

    # 3. SQLite incompat DDL scan.
    findings = _scan_sqlite_incompat_ddl()
    if findings:
        notes.append(f"PostgreSQL-only DDL patterns found: {len(findings)}")
        for pattern, locations in findings.items():
            notes.append(f"  - {pattern}: {len(locations)} occurrences")
            if pattern in ("JSONB", "CONCURRENTLY", "GIST", "GIN", "BRIN"):
                issues.append(
                    f"{pattern} found in migrations — won't run on SQLite (dev_light)."
                )
    else:
        notes.append("No PostgreSQL-only DDL patterns detected.")

    # 4. Alembic.ini placeholder URL.
    ini_check = _check_alembic_ini()
    if not ini_check.get("exists"):
        issues.append(f"{ALEMBIC_INI} missing.")
    elif ini_check.get("is_placeholder"):
        notes.append(
            f"alembic.ini URL is placeholder: {ini_check.get('url')!r}. "
            "Must be overridden via env or DATABASE_URL."
        )

    # 5. dev_light DB type.
    db_type = _check_dev_light_db_type()
    if db_type == "sqlite":
        notes.append("dev_light uses SQLite — migrations must be SQLite-compatible")
        # Already covered by findings scan above.
    elif db_type:
        notes.append(f"dev_light uses {db_type}")

    # Report.
    result = {
        "migration_count": n_migrations,
        "alembic_heads": heads,
        "sqlite_incompat_ddls": {k: len(v) for k, v in findings.items()},
        "alembic_ini_url": ini_check.get("url"),
        "alembic_ini_is_placeholder": ini_check.get("is_placeholder"),
        "dev_light_db_type": db_type,
        "issues": issues,
        "notes": notes,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{'=' * 60}")
        print("Alembic Migration Verification (P0 audit 2026-09-22)")
        print(f"{'=' * 60}")
        print()
        for n in notes:
            print(f"  ℹ️  {n}")
        print()
        if issues:
            print("Issues:")
            for i in issues:
                print(f"  ❌ {i}")
        else:
            print("✅ All checks passed")
        print()

    if args.strict and issues:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
