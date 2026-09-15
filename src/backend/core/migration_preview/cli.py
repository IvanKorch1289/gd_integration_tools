"""CLI entry point для migration preview gate."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from src.backend.core.migration_preview.preview import MigrationPreviewer


def scan_alembic_versions(alembic_dir: Path) -> list[Path]:
    """Find all .py migration files в alembic versions/."""
    versions_dir = alembic_dir / "versions"
    if not versions_dir.exists():
        return []
    return sorted(versions_dir.glob("*.py"))


def main() -> int:
    """CLI entry point.

    Usage:
        python -m src.backend.core.migration_preview.cli_main \\
            --alembic-dir src/backend/infrastructure/database/migrations \\
            --output /tmp/migration_preview.json
    """
    parser = argparse.ArgumentParser(
        description="Preview Alembic migrations (CRITICAL/HIGH detection)"
    )
    parser.add_argument(
        "--alembic-dir",
        type=Path,
        default=Path("src/backend/infrastructure/database/migrations"),
        help="Alembic migrations directory",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(tempfile.gettempdir()) / "migration_preview.json",  # noqa: S108
        help="Output JSON file",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail (exit 1) on CRITICAL operations",
    )

    args = parser.parse_args()

    previewer = MigrationPreviewer()
    total_critical = 0
    total_high = 0
    all_reports = []

    files = scan_alembic_versions(args.alembic_dir)
    if not files:
        print(f"No migration files found in {args.alembic_dir}/versions/")
        result = {
            "total_files": 0,
            "total_critical": 0,
            "total_high": 0,
            "safe": True,
            "files": [],
        }
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return 0

    for f in files:
        try:
            report = previewer.preview_file(f)
        except Exception as exc:  # broad — best effort
            print(f"Error previewing {f}: {exc}")
            continue
        all_reports.append(
            {
                "file": str(f.relative_to(args.alembic_dir.parent)),
                "total_operations": report.total,
                "critical_count": report.critical_count,
                "high_count": report.high_count,
                "is_safe": report.is_safe,
            }
        )
        total_critical += report.critical_count
        total_high += report.high_count

    result = {
        "total_files": len(files),
        "total_critical": total_critical,
        "total_high": total_high,
        "safe": total_critical == 0,
        "files": all_reports,
    }
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(
        f"Scanned {len(files)} migrations: "
        f"{total_critical} CRITICAL, {total_high} HIGH"
    )

    if args.strict and total_critical > 0:
        print(f"STRICT mode: {total_critical} CRITICAL operations found — FAIL")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
