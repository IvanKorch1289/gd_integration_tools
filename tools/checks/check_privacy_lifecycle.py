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

    # Erasure-адаптеры (W9 Phase 3): core/privacy/delete_data_subject/.
    # Гейт до фикса искал в infrastructure/* и давал false negatives —
    # см. PRIVACY_BACKENDS_INVESTIGATION_2026-09-24.
    adapters_dir = SRC_ROOT / "backend/core/privacy/delete_data_subject"
    adapter_content: dict[str, str] = {}
    if adapters_dir.exists():
        for py in adapters_dir.glob("_*.py"):
            try:
                adapter_content[py.name] = py.read_text(
                    encoding="utf-8", errors="ignore"
                )
            except OSError:
                continue

    def _adapter_has(fname: str, *markers: str) -> bool:
        content = adapter_content.get(fname, "")
        low = content.lower()
        return all(m.lower() in low for m in markers)

    # Redis: SCAN + UNLINK по subject-ключам.
    backends["redis"] = {
        "covered": _adapter_has("_redis.py", "scan", "unlink", "subject_id"),
        "evidence": "adapter _redis.py: SCAN+UNLINK subject keys"
        if "_redis.py" in adapter_content
        else "adapter missing",
    }

    # S3: delete/purge объектов субъекта.
    backends["s3"] = {
        "covered": _adapter_has("_s3.py", "subject_id", "delete"),
        "evidence": "adapter _s3.py: subject delete"
        if _adapter_has("_s3.py", "subject_id", "delete")
        else "no delete in adapter",
    }

    # Qdrant: subject-scoped vector delete.
    backends["qdrant"] = {
        "covered": _adapter_has("_qdrant.py", "subject_id")
        and (
            "delete" in adapter_content.get("_qdrant.py", "").lower()
            or "filter" in adapter_content.get("_qdrant.py", "").lower()
        ),
        "evidence": "adapter _qdrant.py: subject-scoped vector delete"
        if _adapter_has("_qdrant.py", "subject_id")
        else "no subject-scoped vector delete",
    }

    # AI memory (LangMem adapter).
    backends["ai_memory"] = {
        "covered": _adapter_has("_langmem.py", "subject_id", "delete")
        or _adapter_has("_langmem.py", "subject_id", "memory"),
        "evidence": "adapter _langmem.py present"
        if "_langmem.py" in adapter_content
        else "no LangMem adapter",
    }

    # PostgreSQL: stub-статус честно отражаем (real DELETE — Sprint 4+).
    pg_stub = _adapter_has("_postgres.py", "stub") or _adapter_has(
        "_postgres.py", "sleep(0)"
    )
    backends["postgresql"] = {
        "covered": not pg_stub and "_postgres.py" in adapter_content,
        "evidence": "adapter _postgres.py is a stub (Sprint 4+)" if pg_stub else "adapter present",
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
