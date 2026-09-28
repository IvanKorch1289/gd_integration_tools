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
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"


# ---------------------------------------------------------------------------
# Behavioural evidence (ADR-0347)
# ---------------------------------------------------------------------------
# Исторически "covered" определялся ПОИСКОМ СТРОК в исходнике адаптера
# (``_adapter_has("...", "subject_id", "delete")``). Адаптер, который просто
# УПОМИНАЕТ нужные слова, проходил как покрытый — именно так нерабочий
# ``LangMemEpisodic.subject_id`` (колонки не существовало) годами
# отчитывался как "✅ ai_memory covered".
#
# Теперь structural-маркеры — только предупреждение, а ``covered``
# требует РЕАЛЬНОГО доказательства: тест, который исполняет execute()
# адаптера, и разрешимость всех ORM-атрибутов, на которые адаптер ссылается.

_MODEL_MODULE = "src.backend.core.domain.models"
_ATTR_RE = re.compile(r"\b([A-Z][A-Za-z0-9_]*)\.([a-z_][a-z0-9_]*)")


def _load_orm_models() -> dict[str, type]:
    """Загрузить ORM-модели проекта (если импорт возможен)."""
    try:
        import importlib

        mod = importlib.import_module(_MODEL_MODULE)
    except Exception:
        return {}
    return {
        name: obj
        for name, obj in vars(mod).items()
        if isinstance(obj, type) and hasattr(obj, "__table__")
    }


def _unresolvable_model_attrs(adapter_src: str, models: dict[str, type]) -> list[str]:
    """Найти ``Model.attr``, которых нет на реальной модели.

    Это ловит именно тот класс дефекта, который проскакивал по маркерам:
    адаптер ссылается на несуществующую колонку/атрибут и падает в рантайме.
    """
    if not models:
        return []
    missing: list[str] = []
    for model_name, attr in _ATTR_RE.findall(adapter_src):
        model = models.get(model_name)
        if model is None:
            continue
        if attr in {"metadata", "registry", "__table__", "__tablename__"}:
            continue
        if not hasattr(model, attr):
            missing.append(f"{model_name}.{attr}")
    return sorted(set(missing))


def _behavioural_test_exists(test_rels: str | list[str], adapter_class: str) -> bool:
    """Есть ли тест, который РЕАЛЬНО исполняет адаптер (не просто импортирует).

    Принимает один путь или список кандидатов: у части адаптеров контрактные
    тесты разложены по нескольким файлам.

    Args:
        test_rels: Путь(и) относительно корня репозитория.
        adapter_class: Класс адаптера, который должен исполняться.

    Returns:
        ``True``, если хотя бы один файл и содержит класс адаптера, и вызывает
        ``.execute(...)`` — то есть реально прогоняет erasure-путь.

    """
    if isinstance(test_rels, str):
        test_rels = [test_rels]
    for rel in test_rels:
        path = REPO_ROOT / rel
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if adapter_class in content and ".execute(" in content:
            return True
    return False


# Behavioural contract tests, per backend (ADR-0347). Structural markers alone
# are NOT coverage — an adapter that merely names the right words used to pass.
_BEHAVIOURAL_TESTS: dict[str, list[str]] = {
    "postgresql": [
        # ADR-0347: прежний test_postgres_tenant_enforcement.py SKIP'ился
        # (зависел от несуществующей privacy_models) и при этом кодил
        # unscoped cross-tenant DELETE как «корректное» поведение.
        # Заменён реально исполняемым контрактом на живой PII-таблице.
        "tests/unit/core/privacy/test_postgres_erasure_canonical_path.py",
    ],
    "redis": ["tests/unit/core/privacy/test_redis_erasure_contract.py"],
    "s3": ["tests/unit/core/privacy/test_w11_tenant_aware_erasure.py"],
    "qdrant": ["tests/unit/core/privacy/test_w11_tenant_aware_erasure.py"],
    "ai_memory": ["tests/unit/core/privacy/test_langmem_tenant_erasure_contract.py"],
}

_ADAPTER_CLASS: dict[str, str] = {
    "postgresql": "PostgresErasureAdapter",
    "redis": "RedisErasureAdapter",
    "s3": "S3ErasureAdapter",
    "qdrant": "QdrantErasureAdapter",
    "ai_memory": "LangMemErasureAdapter",
}


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

    # AI memory (LangMem adapter) — ADR-0347: требуется behavioural evidence.
    langmem_src = adapter_content.get("_langmem.py", "")
    _models = _load_orm_models()
    # Fail-closed: если модели не импортируются, проверить ссылки невозможно.
    # Раньше (и в старой версии гейта) это молча превращалось в "проблем нет".
    _models_loadable = bool(_models)
    _missing = _unresolvable_model_attrs(langmem_src, _models)
    if not _models_loadable:
        _missing = ["<orm models not importable — cannot verify>"]
    _structural = _adapter_has("_langmem.py", "subject_id", "delete") or _adapter_has(
        "_langmem.py", "subject_id", "memory"
    )
    _behavioural = _behavioural_test_exists(
        "tests/unit/core/privacy/test_langmem_tenant_erasure_contract.py",
        "LangMemErasureAdapter",
    )
    backends["ai_memory"] = {
        "covered": bool(_behavioural and not _missing),
        "structural_markers": bool(_structural),
        "behavioural_test": bool(_behavioural),
        "unresolvable_attrs": _missing,
        "orm_models_loadable": _models_loadable,
        "evidence": (
            "behavioural: contract test executes LangMemErasureAdapter.execute()"
            if _behavioural
            else "NO behavioural test — adapter never executed"
        )
        + (f"; UNRESOLVED attrs: {_missing}" if _missing else ""),
    }

    # PostgreSQL: per v6 W1 spec — проверяем adapter import + contract suite
    # (НЕ текстовые маркеры "stub"/"sleep(0)"). Adapter импортируется +
    # проверяется наличие real DELETE/tenant filter patterns.
    # 25.09: rename ``explicit_tenant_id`` → ``tenant_id`` для consistency
    # с ErasureAdapter Protocol. Backward-compat: text check accepts оба имени.
    pg_content = adapter_content.get("_postgres.py", "")
    pg_has_delete = "delete" in pg_content.lower()
    pg_has_tenant = "tenant_id" in pg_content.lower()
    pg_has_tenant_param = (
        "tenant_id: str | none" in pg_content.lower()
        or "tenant_id: str" in pg_content.lower()
    )
    pg_covered = (
        "_postgres.py" in adapter_content
        and pg_has_delete
        and pg_has_tenant
        and pg_has_tenant_param
    )
    backends["postgresql"] = {
        "covered": pg_covered,
        "evidence": (
            "adapter _postgres.py: real DELETE + tenant_id (ADR-0345 Option A)"
        )
        if pg_covered
        else (
            f"adapter _postgres.py incomplete "
            f"(delete={pg_has_delete}, tenant_id={pg_has_tenant}, "
            f"tenant_id_param={pg_has_tenant_param})"
        ),
    }

    # ------------------------------------------------------------------
    # ADR-0347: structural markers alone are NOT coverage.
    # Every backend must additionally have a test that actually EXECUTES
    # the adapter's execute() path, and must not reference ORM attributes
    # that do not exist on the real models. Applied uniformly so the
    # LangMem class of defect cannot hide behind a marker match.
    # ------------------------------------------------------------------
    _models_all = _load_orm_models()
    if not _models_all:
        for _name in backends:
            backends[_name]["covered"] = False
            backends[_name]["evidence"] = (
                "UNVERIFIED: ORM models not importable — cannot resolve "
                "adapter attribute references (fail-closed)"
            )
        return backends

    for _name, _info in backends.items():
        _cls = _ADAPTER_CLASS.get(_name)
        if not _cls:
            continue
        _tests = _BEHAVIOURAL_TESTS.get(_name, [])
        _behavioural = _behavioural_test_exists(_tests, _cls)
        _src_key = {
            "postgresql": "_postgres.py",
            "redis": "_redis.py",
            "s3": "_s3.py",
            "qdrant": "_qdrant.py",
            "ai_memory": "_langmem.py",
        }[_name]
        _missing = _unresolvable_model_attrs(
            adapter_content.get(_src_key, ""), _models_all
        )
        _structural = bool(_info.get("covered"))
        _info["structural_markers"] = _structural
        _info["behavioural_test"] = _behavioural
        _info["unresolvable_attrs"] = _missing
        _info["covered"] = bool(_structural and _behavioural and not _missing)
        _ev = str(_info.get("evidence", ""))
        if not _behavioural:
            _info["evidence"] = (
                f"NO behavioural test — adapter never executed; structural "
                f"markers present but insufficient. {_ev}"
            )
        elif _missing:
            _info["evidence"] = f"UNRESOLVED attrs: {_missing}; {_ev}"
        else:
            _info["evidence"] = f"behavioural ({_tests[0]}) + {_ev}"

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
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Deprecated alias — exit 1 on any ❌ is now DEFAULT (per v6 W1: "
            "'Любой backend с ❌ должен давать ненулевой exit code'). "
            "Keep flag для backwards compat со старыми CI pipelines."
        ),
    )
    parser.add_argument(
        "--no-strict",
        action="store_true",
        help="Opt-out: exit 0 even с ❌ (для отладки / triage).",
    )
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

    # Per v6 W1 spec: «Любой backend с ❌ должен давать ненулевой exit code».
    # Default behavior — exit 1 on any issue. --no-strict opt-out для triage.
    if args.no_strict:
        return 0  # explicit opt-out
    if issues:
        return 1  # fail-closed by default (per v6)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
