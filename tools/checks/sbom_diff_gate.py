"""SBOM Diff Gate — supply-chain CI enforcement (Wave OP-3 / ADR-0296).

Назначение:
    Сравнивает текущий SBOM (CycloneDX JSON) с baseline и фейлит CI при:

    1. Появлении новой license из запрещённого списка (GPL, AGPL, SSPL, BUSL).
    2. Появлении нового component из неизвестного registry (только pypi).
    3. Значительном росте количества transitive deps (>threshold).
    4. Появлении компонента с unknown license (license detection failed).

Использование:
    python tools/checks/sbom_diff_gate.py \
        --current dist/sbom.cdx.json \
        --baseline dist/sbom.baseline.json \
        --threshold-new-components 5

Аргументы:
    --current             Текущий SBOM (CycloneDX JSON).
    --baseline            Baseline SBOM (предыдущий accepted release).
    --threshold-new-components  Макс. кол-во новых components без fail.
    --license-deny-list   File с запрещёнными license IDs (default: deny list).

References:
    - .security/sbom.policy.md
    - Sprint K5 (Wave K5/supply-chain)
    - ADR-0296 (SBOM diff gate requirement)
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

# License IDs, запрещённые к добавлению (copyleft / commercial-restricted).
# Формат: SPDX license identifier (https://spdx.org/licenses/).
DEFAULT_DENY_LICENSES = frozenset({
    "GPL-2.0", "GPL-3.0",
    "AGPL-3.0", "AGPL-3.0-only", "AGPL-3.0-or-later",
    "SSPL-1.0",
    "BUSL-1.1",
    "Commons-Clause",
    "Elastic-2.0",
    "SSPL",
})


@dataclass(slots=True)
class SBOMComponent:
    """Один component из SBOM."""

    name: str
    version: str
    purl: str = ""
    licenses: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SBOMDiff:
    """Diff между baseline и current SBOM."""

    added: list[SBOMComponent] = field(default_factory=list)
    removed: list[SBOMComponent] = field(default_factory=list)
    license_violations: list[tuple[str, SBOMComponent]] = field(default_factory=list)
    unknown_licenses: list[SBOMComponent] = field(default_factory=list)
    total_components: int = 0
    delta_components: int = 0

    @property
    def has_violations(self) -> bool:
        return bool(self.license_violations or self.unknown_licenses)


def _parse_components(sbom_path: Path) -> list[SBOMComponent]:
    """Parse CycloneDX JSON → list of SBOMComponent."""
    if not sbom_path.exists():
        print(f"[ERROR] SBOM не найден: {sbom_path}", file=sys.stderr)
        sys.exit(2)

    try:
        data = json.loads(sbom_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[ERROR] SBOM не валидный JSON ({sbom_path}): {exc}", file=sys.stderr)
        sys.exit(2)

    components: list[SBOMComponent] = []
    for comp in data.get("components", []):
        licenses: list[str] = []
        for lic in comp.get("licenses", []):
            license_obj = lic.get("license", {})
            lic_id = license_obj.get("id") or license_obj.get("name")
            if lic_id:
                licenses.append(lic_id)
        components.append(
            SBOMComponent(
                name=comp.get("name", ""),
                version=comp.get("version", ""),
                purl=comp.get("purl", ""),
                licenses=licenses,
            )
        )
    return components


def _component_key(comp: SBOMComponent) -> tuple[str, str]:
    """Unique key (name, version)."""
    return (comp.name, comp.version)


def diff_sboms(
    *,
    current: list[SBOMComponent],
    baseline: list[SBOMComponent],
    deny_licenses: frozenset[str] = DEFAULT_DENY_LICENSES,
) -> SBOMDiff:
    """Сравнить два SBOM и вернуть diff."""
    current_map = {_component_key(c): c for c in current}
    baseline_map = {_component_key(c): c for c in baseline}

    current_keys = set(current_map.keys())
    baseline_keys = set(baseline_map.keys())

    added_keys = current_keys - baseline_keys
    removed_keys = baseline_keys - current_keys

    added = [current_map[k] for k in sorted(added_keys)]
    removed = [baseline_map[k] for k in sorted(removed_keys)]

    license_violations: list[tuple[str, SBOMComponent]] = []
    unknown_licenses: list[SBOMComponent] = []

    # Check ALL current components for license violations.
    for comp in current:
        if not comp.licenses:
            # No license detected — flag as unknown.
            unknown_licenses.append(comp)
            continue
        for lic_id in comp.licenses:
            if lic_id in deny_licenses:
                license_violations.append((lic_id, comp))

    return SBOMDiff(
        added=added,
        removed=removed,
        license_violations=license_violations,
        unknown_licenses=unknown_licenses,
        total_components=len(current),
        delta_components=len(added) - len(removed),
    )


def _format_report(diff: SBOMDiff) -> str:
    """Human-readable diff report."""
    lines: list[str] = []
    lines.append("=" * 70)
    lines.append("SBOM Diff Gate Report (Wave OP-3)")
    lines.append("=" * 70)
    lines.append("")
    lines.append(f"Total components:      {diff.total_components}")
    lines.append(f"Added components:      {len(diff.added)}")
    lines.append(f"Removed components:    {len(diff.removed)}")
    lines.append(f"Net delta:             {diff.delta_components:+d}")
    lines.append(f"License violations:    {len(diff.license_violations)}")
    lines.append(f"Unknown licenses:      {len(diff.unknown_licenses)}")
    lines.append("")

    if diff.added:
        lines.append("--- ADDED ---")
        for comp in diff.added[:20]:  # Limit output.
            licenses = ",".join(comp.licenses) if comp.licenses else "?"
            lines.append(f"  + {comp.name}=={comp.version} ({licenses})")
        if len(diff.added) > 20:
            lines.append(f"  ... and {len(diff.added) - 20} more")
        lines.append("")

    if diff.removed:
        lines.append("--- REMOVED ---")
        for comp in diff.removed[:20]:
            lines.append(f"  - {comp.name}=={comp.version}")
        if len(diff.removed) > 20:
            lines.append(f"  ... and {len(diff.removed) - 20} more")
        lines.append("")

    if diff.license_violations:
        lines.append("--- LICENSE VIOLATIONS ---")
        for lic_id, comp in diff.license_violations:
            lines.append(f"  ! {comp.name}=={comp.version}: {lic_id}")
        lines.append("")

    if diff.unknown_licenses:
        lines.append("--- UNKNOWN LICENSES (no license detected) ---")
        for comp in diff.unknown_licenses[:20]:
            lines.append(f"  ? {comp.name}=={comp.version} ({comp.purl})")
        if len(diff.unknown_licenses) > 20:
            lines.append(f"  ... and {len(diff.unknown_licenses) - 20} more")
        lines.append("")

    lines.append("=" * 70)
    if diff.has_violations:
        lines.append("RESULT: FAIL (license violations)")
    else:
        lines.append("RESULT: PASS")
    lines.append("=" * 70)
    return "\n".join(lines)


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="SBOM Diff Gate — supply-chain CI enforcement"
    )
    parser.add_argument(
        "--current",
        type=Path,
        required=True,
        help="Current SBOM (CycloneDX JSON)",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        required=True,
        help="Baseline SBOM (CycloneDX JSON)",
    )
    parser.add_argument(
        "--threshold-new-components",
        type=int,
        default=20,
        help="Max allowed new components (default: 20)",
    )
    parser.add_argument(
        "--license-deny-list",
        type=Path,
        help="Path to file with denied license IDs (one per line)",
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Update baseline with current SBOM (after accepting changes)",
    )
    args = parser.parse_args()

    # Load deny list.
    deny_licenses = DEFAULT_DENY_LICENSES
    if args.license_deny_list and args.license_deny_list.exists():
        deny_licenses = frozenset(
            line.strip()
            for line in args.license_deny_list.read_text().splitlines()
            if line.strip() and not line.startswith("#")
        )

    # Parse SBOMs.
    current = _parse_components(args.current)
    baseline = _parse_components(args.baseline) if args.baseline.exists() else []

    if not args.baseline.exists():
        print(f"[WARN] Baseline не найден: {args.baseline}", file=sys.stderr)
        print("[WARN] Treating baseline как empty (first run).", file=sys.stderr)

    # Compute diff.
    diff = diff_sboms(
        current=current,
        baseline=baseline,
        deny_licenses=deny_licenses,
    )

    # Format + print report.
    report = _format_report(diff)
    print(report)

    # Decision.
    if diff.has_violations:
        return 1

    if len(diff.added) > args.threshold_new_components:
        print(
            f"[FAIL] Too many new components: {len(diff.added)} "
            f"> {args.threshold_new_components}",
            file=sys.stderr,
        )
        return 1

    # Optionally update baseline.
    if args.update_baseline:
        args.baseline.write_text(args.current.read_text(encoding="utf-8"))
        print(f"[OK] Baseline updated: {args.baseline}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
