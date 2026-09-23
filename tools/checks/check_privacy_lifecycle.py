"""Privacy lifecycle coverage check (P1 audit 2026-09-22).

Аудит finding #5: PII masking не решает задачи удаления данных.
Нужна orchestration-команда DeleteDataSubject которая:
  - Находит записи субъекта по stable internal identity.
  - Удаляет или анонимизирует PostgreSQL-записи.
  - Инвалидирует Redis/KeyDB cache.
  - Удаляет S3-объекты и версии.
  - Удаляет Qdrant vectors.
  - Удаляет RAG chunks и AI memory.
  - Публикует tombstone для downstream consumers.
  - Сохраняет минимальное непротиворечивое доказательство исполнения.
  - Поддерживает legal hold.
  - Выполняет повторную reconciliation-проверку.

Проверяет:
1. Наличие ``DeleteDataSubject`` orchestration (или эквивалента).
2. Какие storage backends покрыты erasure (PG, Redis, S3, Qdrant, RAG, AI memory).
3. Tombstone publication для downstream.
4. Legal hold support.
5. Reconciliation/recheck capability.

Использование::

    python tools/checks/check_privacy_lifecycle.py              # human-readable
    python tools/checks/check_privacy_lifecycle.py --strict    # exit 1
    python tools/checks/check_privacy_lifecycle.py --json      # machine output
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"


def _check_storage_coverage() -> dict[str, dict[str, object]]:
    """Check which storage backends have erasure support."""
    backends: dict[str, dict[str, object]] = {}

    # PostgreSQL — check for SQL DELETE/erasure in pii_erase or similar.
    pg_files = [
        REPO_ROOT / "src/backend/dsl/engine/processors/security/pii_erase.py",
        REPO_ROOT / "src/backend/core/security/pii_tokenizer.py",
        REPO_ROOT / "src/backend/core/security/pii_masker.py",
    ]
    pg_erasure = False
    for f in pg_files:
        if f.exists():
            content = f.read_text(encoding="utf-8", errors="ignore")
            if "DELETE" in content.upper() or "anonymize" in content.lower():
                pg_erasure = True
                break
    backends["postgresql"] = {
        "covered": pg_erasure,
        "evidence": "pii_erase.py has DELETE/anonymize logic",
    }

    # Redis — search for cache invalidation patterns.
    redis_files = []
    for py in (SRC_ROOT / "src/backend/infrastructure/cache").rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        redis_files.append(py)
    redis_invalidate = False
    for f in redis_files:
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "delete" in content.lower() and "subject" in content.lower():
            redis_invalidate = True
            break
    backends["redis"] = {
        "covered": redis_invalidate,
        "evidence": "no subject-specific cache invalidation"
        if not redis_invalidate
        else "found",
    }

    # S3 — search for object deletion patterns.
    s3_files = []
    for py in (SRC_ROOT / "src/backend/infrastructure/storage").rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        s3_files.append(py)
    s3_delete = False
    for f in s3_files:
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "delete_object" in content.lower() or "delete_objects" in content.lower():
            s3_delete = True
            break
    backends["s3"] = {"covered": s3_delete, "evidence": "no delete_object API used"}

    # Qdrant — vector store.
    qdrant_dir = SRC_ROOT / "src/backend/infrastructure/vectorstore"
    qdrant_erase = False
    if qdrant_dir.exists():
        for py in qdrant_dir.rglob("*.py"):
            if "__pycache__" in py.parts:
                continue
            try:
                content = py.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if "delete" in content.lower() and (
                "filter" in content.lower() or "subject_id" in content.lower()
            ):
                qdrant_erase = True
                break
    backends["qdrant"] = {
        "covered": qdrant_erase,
        "evidence": "no subject-specific vector delete",
    }

    # AI memory (LangMem).
    ai_memory_files = list((SRC_ROOT / "src/backend/core/domain/models").rglob("*.py"))
    ai_memory_erase = False
    for f in ai_memory_files:
        if "__pycache__" in f.parts:
            continue
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "langmem" in f.name.lower() and "delete" in content.lower():
            ai_memory_erase = True
            break
    backends["ai_memory"] = {
        "covered": ai_memory_erase,
        "evidence": "LangMem models have delete logic"
        if ai_memory_erase
        else "no LangMem delete",
    }

    return backends


def _check_tombstone_publication() -> bool:
    """Check tombstone publication to MQ after erasure."""
    for py in (SRC_ROOT / "src/backend/services/messaging").rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        try:
            content = py.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "tombstone" in content.lower():
            return True
    # Also check pii_erase for publish event.
    pii_erase = REPO_ROOT / "src/backend/dsl/engine/processors/security/pii_erase.py"
    if pii_erase.exists():
        content = pii_erase.read_text(encoding="utf-8", errors="ignore")
        if "audit" in content.lower() and "erasure" in content.lower():
            return True
    return False


def _check_legal_hold() -> bool:
    """Check legal hold support."""
    for py in SRC_ROOT.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        try:
            content = py.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "legal_hold" in content.lower() or "legalhold" in content.lower():
            return True
    return False


def _check_reconciliation() -> bool:
    """Check reconciliation/recheck after erasure."""
    for py in SRC_ROOT.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        try:
            content = py.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        # Heuristic: reconciliation pattern.
        if "reconcil" in content.lower() and "erasure" in content.lower():
            return True
    return False


def _check_orchestration_command() -> tuple[bool, str]:
    """Check for DeleteDataSubject orchestration command."""
    for py in SRC_ROOT.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        try:
            content = py.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "DeleteDataSubject" in content or "delete_data_subject" in content.lower():
            return True, py.relative_to(REPO_ROOT).as_posix()
    return False, "no DeleteDataSubject command found"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Privacy lifecycle coverage check")
    parser.add_argument("--strict", action="store_true", help="Exit 1 if issues found")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args(argv)

    notes: list[str] = []
    issues: list[str] = []

    backends = _check_storage_coverage()
    n_backends = len(backends)
    n_covered = sum(1 for b in backends.values() if b["covered"])
    notes.append(f"Storage coverage: {n_covered}/{n_backends} backends have erasure")

    for name, info in backends.items():
        notes.append(
            f"  - {name}: {'✅' if info['covered'] else '❌'} {info['evidence']}"
        )

    if n_covered < n_backends:
        missing = [n for n, i in backends.items() if not i["covered"]]
        issues.append(
            f"Storage backends without erasure coverage: {', '.join(missing)}"
        )

    has_tombstone = _check_tombstone_publication()
    notes.append(f"Tombstone publication: {'✅' if has_tombstone else '❌'}")
    if not has_tombstone:
        issues.append(
            "No tombstone publication after erasure — downstream consumers not notified"
        )

    has_legal_hold = _check_legal_hold()
    notes.append(f"Legal hold support: {'✅' if has_legal_hold else '❌'}")
    if not has_legal_hold:
        issues.append(
            "No legal hold support — erasure can violate litigation requirements"
        )

    has_reconciliation = _check_reconciliation()
    notes.append(f"Reconciliation check: {'✅' if has_reconciliation else '❌'}")
    if not has_reconciliation:
        issues.append(
            "No reconciliation check after erasure — silent failures possible"
        )

    has_orchestration, evidence = _check_orchestration_command()
    notes.append(
        f"Orchestration command: {'✅' if has_orchestration else '❌'} {evidence}"
    )
    if not has_orchestration:
        issues.append(
            "No DeleteDataSubject orchestration — erasure is DSL step, not standalone command"
        )

    output = {
        "storage_coverage": backends,
        "tombstone": has_tombstone,
        "legal_hold": has_legal_hold,
        "reconciliation": has_reconciliation,
        "orchestration": has_orchestration,
        "issues": issues,
        "notes": notes,
    }

    if args.json:
        print(json.dumps(output, indent=2))
    else:
        print(f"{'=' * 60}")
        print("Privacy Lifecycle Coverage (P1 audit 2026-09-22)")
        print(f"{'=' * 60}")
        print()
        for n in notes:
            print(f"  {n}")
        print()
        if issues:
            print("Issues:")
            for i in issues:
                print(f"  ❌ {i}")
        else:
            print("✅ Privacy lifecycle complete")
        print()

    if args.strict and issues:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
