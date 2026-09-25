"""Classify object authorization callsites (P0 gap analysis).

Per v4 §10 P0 audit:
- `check_object_authorization.py` reports 133 callsites as potential gaps.
- Per v4 §5 'presence != wiring': many likely false positives
  (in-memory infrastructure registries: route_semaphores, ws connections,
  watcher handlers — not user-data, no tenant context needed by design).

Выход: per-callsite classification (user-data vs infra-registry vs unknown)
с evidence per callsite и structured report.

Usage::
    python tools/classify_object_authorization.py --top 30
    python tools/classify_object_authorization.py --json
    python tools/classify_object_authorization.py --strict  # exit 1 на any unknown > 0

Per v4 §10 P1 evidence-first measurement: 133 callsites → classified
final set informs next-cycle P0 fix ADR scope.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src" / "backend"

# Receiver pattern detection — classifies CALL TARGET (not call site).
# User-data receiver: ORM / DB / cross-tenant cache.
USER_DATA_RECEIVER_PATTERNS = [
    (
        r"\.(get|filter_by|query)\(.*\b(?:tenant_id|user_id|org_id)\b",
        "filter-by-tenant",
    ),
    (r"\.filter\(", "sqlalchemy-filter"),
    (r"\.query\(.*Model\b", "orm-query"),
    (r"\bsession\.", "db-session"),
    (r"\.get_object\(", "repository-pattern"),
]

# Infra-registry receiver — by-name heuristics.
# Patterns matching variable/field names которые store infrastructure state
# (connections, watchers, sockets) — не user-data, no tenant needed.
INFRA_REGISTRY_NAMES = (
    # Original explicit list (high-confidence matches).
    "_connections",
    "_connections_by_action",
    "_route_semaphores",
    "_watchers",
    "_store",
    "_registry",
    "_cache",
    "_semaphores",
    "_instances",
    "_buffer",
    "_pools",
    "_clients",
    "_sessions",
    "_subscribers",
    "_contexts",
    "_tasks",
    "_running",
    "_pending",
    "_completed",
    # Graph/state infrastructure.
    "_nodes",  # graph nodes registry
    "_edges",  # graph edges registry
    "_configs",  # canary/route configs
    "_policies",  # policy registry
    # Stream/connection handlers.
    "_handlers",  # stream/connection handlers
    "_by_action",  # action-keyed lookup
    # Generic names.
    "registry",  # generic registry-like names
    "store",  # in-memory store
    "templates",  # template registry (compile-time constants)
    "_templates",  # private template registry
    "lookup",  # lookup tables
    "dedup",  # dedup tables
    "lock",  # locks registry
    "shadow",  # shadow copies
    "_shadow",
    "dedup_",
    "by_id",
    # v6 W3.3 heuristic upgrade per audit docs/roadmap/
    # W3_UNKNOWN_OWNERSHIP_CLASSIFICATION_2026-09-24.md:
    # cert_store backends → _services (Vault/Env/Consul/File backend registry).
    "_services",
    # integrations/facade → _sources / _sinks (NOT user data — connection metadata).
    # NB: name variants needed — `self.sinks.get` chain содержит `sinks`
    # (без underscore) после strip `self.` prefix.
    "_sources",
    "_sinks",
    "sources",
    "sinks",
    "backends",
)

# Generator expressions for pattern-based detection:
INFRA_NAME_PATTERNS = [
    # Anything ending with "_by_<key>" (action-keyed lookup).
    (re.compile(r"\b\w+_by_\w+\b"), "_by_<key>"),
    # Anything starting with "_registry", "registry_" (registry-like).
    (re.compile(r"\b_?registry_\w+|\b\w+_registry\b"), "registry-pattern"),
]

# Auth/admin paths skipped per check_object_authorization.py behavior.
# Cover both ``/admin/foo.py`` AND ``admin_foo.py`` patterns (entrypoints/{api,...}/admin_*).
_SKIP_PATH_PATTERNS = (
    "/auth/",
    "/admin/",
    "/tests/",
    "admin_",  # matches admin_nats.py, admin_actions.py, etc.
    "/migrations/",  # alembic versions — не runtime
)


@dataclass(frozen=True)
class Callsite:
    """One classified callsite."""

    file: str
    line: int
    receiver_type: str  # "user-data" | "infra-registry" | "unknown"
    detection_pattern: str
    snippet: str
    reason: str


# v6 W3.4: FALSE_POSITIVE allowlist (.baselines/object_ownership_false_positives.yaml).
# Каждый entry классифицируется как FALSE_POSITIVE вместо UNKNOWN, что
# разблокирует strict gate (UNKNOWN всегда блокирует per v6).
FALSE_POSITIVE_ALLOWLIST: dict[tuple[str, int], dict[str, str]] = {}


def _load_false_positive_allowlist() -> dict[tuple[str, int], dict[str, str]]:
    """Load FALSE_POSITIVE allowlist из ``.baselines/...yaml``.

    Per v6 W3.4: «Исключения хранятся в versioned allowlist с owner,
    причиной и сроком пересмотра».
    """
    import logging

    import yaml  # type: ignore[import-not-found]  # PyYAML optional.

    logger = logging.getLogger(__name__)

    allowlist_path = (
        Path(__file__).resolve().parents[1]
        / ".baselines"
        / "object_ownership_false_positives.yaml"
    )
    if not allowlist_path.exists():
        return {}

    try:
        data = yaml.safe_load(allowlist_path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError) as exc:  # pragma: no cover — defensive.
        logger.warning(
            "object_authorization.allowlist.load_failed: %s path=%s",
            exc,
            allowlist_path,
        )
        return {}

    entries: dict[tuple[str, int], dict[str, str]] = {}
    for entry in data.get("allowlist", []):
        key = (entry["file"], int(entry["line"]))
        entries[key] = entry
    return entries


def _classify_callsite(py: Path, node: ast.Call) -> Callsite | None:
    """Classify single AST Call node.

    Returns ``None`` если callsite не подходит под паттерны .get(id=) / .filter_by(id=).
    """
    src = ast.unparse(node)
    line_no = getattr(node, "lineno", 0)
    file = str(py.relative_to(PROJECT_ROOT))

    # Apply existing exclusion rules (per check_object_authorization.py).
    if "tenant" in src or "TenantContext" in src:
        return None
    rel_path = str(py)
    if any(p in rel_path for p in _SKIP_PATH_PATTERNS):
        return None

    # Match .get(id|uud|pk) or .filter_by(id=).
    if not (
        re.search(r"\.get\(\s*\w*(?:id|uuid|pk)\w*\s*\)", src)
        or ".filter_by(id=" in src
    ):
        return None

    # Try to determine receiver type via heuristic on `node.func`.
    receiver_str = ast.unparse(node.func) if hasattr(node, "func") else src

    # v6 W3.3: extract full attribute chain для корректного INFRA detection.
    # Пример: receiver `self._services.get` → attribute_chain = ['self', '_services'].
    # Без этого `self.get` не матчит `_services` pattern (только receiver_str).
    attribute_chain = (
        _extract_attribute_chain(node.func) if hasattr(node, "func") else []
    )
    chain_str = ".".join(attribute_chain)

    # Infra-registry receiver? Match by-name suffix в attribute chain.
    # Совпадение в любом сегменте цепочки (e.g., self._services, _services, services).
    if any(name in receiver_str or name in chain_str for name in INFRA_REGISTRY_NAMES):
        return Callsite(
            file=file,
            line=line_no,
            receiver_type="infra-registry",
            detection_pattern="infra-name-suffix",
            snippet=src[:120],
            reason=(
                f"receiver '{receiver_str}' (chain: '{chain_str}') matches "
                f"infra-registry name pattern; no tenant needed"
            ),
        )

    # v6 W3.3: path-based INFRA detection для cert_store/* — class-level
    # `self._services` registry невидим в AST (chain = ['self', 'get']),
    # но file path — strong signal. Per audit doc раздел 2.2.
    rel_path = str(py)
    if any(p in rel_path for p in PATH_INFRA_REGISTRY_PATTERNS):
        return Callsite(
            file=file,
            line=line_no,
            receiver_type="infra-registry",
            detection_pattern="path-infra-registry",
            snippet=src[:120],
            reason=(
                f"file '{rel_path}' in PATH_INFRA_REGISTRY_PATTERNS; "
                f"backend registry lookup (self._services), no tenant needed"
            ),
        )

    # Pattern-based infra-detection.
    for pattern, label in INFRA_NAME_PATTERNS:
        if pattern.search(receiver_str):
            return Callsite(
                file=file,
                line=line_no,
                receiver_type="infra-registry",
                detection_pattern=label,
                snippet=src[:120],
                reason=f"receiver '{receiver_str}' matches pattern '{label}'",
            )

    # User-data receiver? Match pattern in source text.
    for pattern, label in USER_DATA_RECEIVER_PATTERNS:
        if re.search(pattern, src):
            return Callsite(
                file=file,
                line=line_no,
                receiver_type="user-data",
                detection_pattern=label,
                snippet=src[:120],
                reason=f"matches '{label}' pattern; tenant filter expected",
            )

    # ORM/Django-style patterns via receiver AST inspection.
    # Heuristic: receiver contains "Model", "Repository", "Query", OR
    # is a service getter like ``get_xxx_service()``, OR bare matches
    # common service-locator names (``svc``, ``api_svc``, ``service``).
    # NB: regex trailing ``\b`` removed — ``()`` followed by ``.`` produces
    # non-word/non-word boundary, classic regex pitfall.
    # NB2: receiver_str includes the ``.get`` suffix (e.g. ``svc.get``)
    # — exact-match ``receiver_str == "svc"`` doesn't work. Use bare-strip.
    bare_receiver = receiver_str.removesuffix(".get")
    if (
        re.search(r"\b(Model|Repository|Query|Manager)\b", receiver_str)
        or re.search(r"\bget_\w+_service\(\)", receiver_str)
        or bare_receiver in {"svc", "service"}
        or bare_receiver.endswith("_svc")
        or bare_receiver.endswith("service")
    ):
        return Callsite(
            file=file,
            line=line_no,
            receiver_type="user-data",
            detection_pattern="service-getter",
            snippet=src[:120],
            reason=f"receiver '{receiver_str}' is service getter / Model; likely user-data needs tenant filter",
        )

    # Templates registry-style name.
    if receiver_str in ("templates", "_templates", "self._templates"):
        return Callsite(
            file=file,
            line=line_no,
            receiver_type="infra-registry",
            detection_pattern="templates-registry",
            snippet=src[:120],
            reason="templates registry is compile-time constants; no tenant",
        )

    # Common user-data receiver names (Domain services / Repositories).
    # Strip ``self.`` and ``self._`` prefix for the check.
    bare = receiver_str
    for prefix in ("self.", "self._"):
        if bare.startswith(prefix):
            bare = bare[len(prefix) :]
            break
    # User-data: receiver contains tenant/entity identifiers or DB patterns.
    USER_DATA_NAMES = (
        "service",  # 99% of user-data service locators
        "repo",  # 99% repo pattern
        "repository",
        "notebook",  # ai/notebooks domain
        "feedback",  # ai/feedback domain
        "feedback_service",
        "notebook_service",
        "doc",
        "docs",
    )
    if any(bare.endswith(name) or bare == name for name in USER_DATA_NAMES):
        return Callsite(
            file=file,
            line=line_no,
            receiver_type="user-data",
            detection_pattern="domain-service-name",
            snippet=src[:120],
            reason=f"receiver '{receiver_str}' ends with user-data marker '{bare}'",
        )

    # Generic self._<plural> heuristic — private collection fields are
    # usually infra registries (routes, contracts, agents, skills,
    # events, records, entries, etc.). User-data typically goes через
    # explicit ``service``/``repo`` getter, not raw ``self._foo.get()``.
    if bare.startswith("_") and len(bare) > 2:
        # Only short suffixes — keep conservative.
        # E.g., _routes, _contracts, _agents, _skills, _events, _records,
        # _entries, _hits, _registry, etc.
        return Callsite(
            file=file,
            line=line_no,
            receiver_type="infra-registry",
            detection_pattern="private-plural-collection",
            snippet=src[:120],
            reason=f"receiver '{receiver_str}' starts with 'self._' (private collection → infra-registry by convention)",
        )

    return Callsite(
        file=file,
        line=line_no,
        receiver_type="unknown",
        detection_pattern="none",
        snippet=src[:120],
        reason="no classifier rule matched; needs manual review",
    )


def _extract_attribute_chain(node: ast.AST) -> list[str]:
    """Extract attribute chain from ast.Call.func as list of names.

    Примеры:
    - ``self.get`` → ['self', 'get']
    - ``self._services.get`` → ['self', '_services', 'get']
    - ``svc.get`` → ['svc', 'get']
    - ``manager.scheduler.add_job`` → ['manager', 'scheduler', 'add_job']

    Используется для расширения INFRA detection: receiver `self.get`
    не содержит `_services`, но chain `self._services.get` содержит.
    """
    chain: list[str] = []
    current: ast.AST | None = node
    while current is not None:
        if isinstance(current, ast.Attribute):
            chain.append(current.attr)
            current = current.value
        elif isinstance(current, ast.Name):
            chain.append(current.id)
            break
        else:
            break
    return list(reversed(chain))


# v6 W3.3 path-based INFRA_REGISTRY patterns. Used when AST-level heuristics
# insufficient (e.g., ``self.get(service_id)`` в cert_store — receiver
# type невидим без class-level analysis).
PATH_INFRA_REGISTRY_PATTERNS: tuple[str, ...] = (
    # cert_store/* — backend registry lookups by service_id/agent_id.
    # Per audit docs/roadmap/W3_UNKNOWN_OWNERSHIP_CLASSIFICATION_2026-09-24.md:
    # backend_vault.py, backend_env.py, backend_registry.py, fallback.py,
    # backend_consul.py, backend_file.py — все содержат `self._services`
    # registry (class-level attribute, AST-невидим).
    "/infrastructure/security/cert_store/",
)


def collect_all_callsites() -> list[Callsite]:
    """Scan all .py in src/backend (excluding tests/auth/admin) per
    ``check_object_authorization.py`` baseline logic.

    v6 W3.4: После _classify_callsite, scan allowlist: matching
    (file, line) → override type to FALSE_POSITIVE with allowlist reason.
    """
    # Lazy-load allowlist per call (single YAML load, simple data).
    if not FALSE_POSITIVE_ALLOWLIST:
        FALSE_POSITIVE_ALLOWLIST.update(_load_false_positive_allowlist())

    out: list[Callsite] = []
    for py in SRC_ROOT.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        if "/tests/" in str(py) or "tests/" in str(py):
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                cs = _classify_callsite(py, node)
                if cs is not None:
                    # v6 W3.4: allowlist override → FALSE_POSITIVE.
                    rel_path = str(py.relative_to(PROJECT_ROOT))
                    key = (rel_path, cs.line)
                    entry = FALSE_POSITIVE_ALLOWLIST.get(key)
                    if entry is not None:
                        cs = Callsite(
                            file=cs.file,
                            line=cs.line,
                            receiver_type="false-positive",
                            detection_pattern="allowlist",
                            snippet=cs.snippet,
                            reason=(
                                f"allowlist: {entry.get('reason', '').strip()} "
                                f"(owner={entry.get('owner', 'n/a')}, "
                                f"review={entry.get('review_date', 'n/a')})"
                            ),
                        )
                    out.append(cs)
    return out


def render_table(rows: list[Callsite], top: int | None) -> str:
    """Human-readable table."""
    if not rows:
        return "No callsites found.\n"

    by_type: dict[str, int] = Counter(r.receiver_type for r in rows)
    pct = {t: f"{100 * n / len(rows):.1f}%" for t, n in by_type.items()}

    lines = [
        f"Object authorization callsites classifier — {len(rows)} callsites",
        f"Generated: {datetime.now(UTC).isoformat()}",
        "",
        "Summary:",
    ]
    for t in ("user-data", "infra-registry", "unknown"):
        n = by_type.get(t, 0)
        lines.append(f"  {t}: {n} ({pct.get(t, '0.0%')})")
    lines.append("")
    lines.append("Sample (first {}):".format("all" if top is None else top))
    lines.append(f"{'File':<60} {'Line':>5}  {'Type':<14}  {'Snippet':<40}")
    lines.append("-" * 130)
    for r in rows if top is None else rows[:top]:
        snip = r.snippet[:38] + "..." if len(r.snippet) > 40 else r.snippet
        lines.append(f"{r.file:<60} {r.line:>5}  {r.receiver_type:<14}  {snip:<40}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Classify object authorization callsites"
    )
    parser.add_argument(
        "--top",
        type=int,
        default=30,
        help="Show top N sample callsites (default 30, 0 = show all)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON для machine-readable consumption",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Exit 1 if any unknown callsite present (CI gate per v6 W1). "
            "Per v6: UNKNOWN всегда блокирует strict gate; USER_DATA без "
            "ownership check — отдельная wave."
        ),
    )
    args = parser.parse_args(argv)

    rows = collect_all_callsites()
    if args.json:
        payload = {
            "generated_at": datetime.now(UTC).isoformat(),
            "total": len(rows),
            "by_type": dict(Counter(r.receiver_type for r in rows)),
            "rows": [asdict(r) for r in rows],
        }
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    else:
        top = args.top if args.top != 0 else None
        sys.stdout.write(render_table(rows, top))

    if args.strict:
        # Per v6 W1: UNKNOWN всегда блокирует strict gate. Раньше был
        # threshold 20% — слишком lenient, скрывал 23 unknown callsites.
        n_unknown = sum(1 for r in rows if r.receiver_type == "unknown")
        n_user_data = sum(1 for r in rows if r.receiver_type == "user-data")
        if n_unknown > 0:
            sys.stderr.write(
                f"\nv6 W1 strict gate FAILED: {n_unknown} unknown callsites "
                f"(of {len(rows)} total; {n_user_data} user-data). "
                f"All UNKNOWN требует ручной классификации или "
                f"FALSE_POSITIVE allowlist entry.\n"
            )
            return 1
        # Optional info line при success — counts для transparency.
        sys.stderr.write(
            f"\nv6 W1 strict gate OK: {n_user_data} user-data, "
            f"{n_unknown} unknown, {len(rows)} total.\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
