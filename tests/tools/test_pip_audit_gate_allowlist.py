"""D-AUDIT-10301: regression-тест allowlist loading в pip_audit_gate.

Бывший баг (DEPENDENCIES-P0-001): 4-way drift между
  - .security/pip-audit-allowlist.txt (27 entries, canonical)
  - .github/workflows/security.yml (inline --ignore-vuln: 2)
  - .gitlab/ci/.gitlab-ci.yml (inline --ignore-vuln: 1)
  - tools/pip_audit_gate.py (hardcoded IGNORED_VULNS: 0)

Раньше: gate использовал hardcoded (пустой) allowlist, поэтому все 27
allowlist entries не работали — fail-OPEN.

Фикс (cycle 103): _load_allowlist() читает .security/pip-audit-allowlist.txt
at runtime, gate использует loaded IDs.

История prune-ов (S58 / ADR-0290, S96, 2026-09-11): 22 stale CVE удалены,
PYSEC-2026-3552 (cryptography) снята после обновления uv.lock до 50.0.1,
diskcache (PYSEC-2026-2447 / CVE-2025-69872) удалены после устранения
зависимости. Текущий файл содержит только комментарии, Active count = 0.

Этот тест НЕ должен падать, когда allowlist пуст — это ожидаемое
состояние после prune. Регрессия, которую мы ловим: loader должен
возвращать пустой frozenset, а не hardcoded fallback, и должен
честно обрабатывать отсутствие файла.
"""

from __future__ import annotations

from pathlib import Path

from tools.pip_audit_gate import _CANONICAL_ALLOWLIST, IGNORED_VULNS, _load_allowlist


def test_canonical_allowlist_exists() -> None:
    """Canonical allowlist файл должен существовать в репо."""
    assert _CANONICAL_ALLOWLIST.exists(), (
        f"Canonical allowlist {_CANONICAL_ALLOWLIST} not found; "
        f"gate cannot enforce security policy without it"
    )


def test_load_allowlist_returns_set_matching_file_content() -> None:
    """_load_allowlist() обязан отражать фактическое содержимое файла.

    S58 / ADR-0290: 22 stale CVE удалены, PYSEC-2026-3552 (cryptography) снята,
    diskcache CVE удалены. Файл был пуст до Dependabot 2026-10-15.

    2026-10-15 Dependabot: 5 entries re-added (см. .security/pip-audit-allowlist.txt):
    - diskcache PYSEC-2026-2447 (transitive через dspy-ai, upstream archived)
    - chromadb PYSEC-2026-311/3813/3814/3815 (rag extra, src/ doesn't import)

    Каждая запись имеет documented mitigation + Rev. date. Active count = 5.
    Это НЕ fail-OPEN: gate читает файл, а не hardcoded set, и каждая
    запись прошла review (см. .security/pip-audit-allowlist.txt history).

    Регрессия, которую этот тест ловит: если кто-то снова введёт hardcoded
    fallback (бывший D-AUDIT-10301 bug) и файл случайно совпадёт с
    hardcoded-пустым set — тест должен упасть на этом.
    """

    body = _CANONICAL_ALLOWLIST.read_text(encoding="utf-8")
    # Считаем непустые не-комментарные строки, как делает _load_allowlist.
    file_ids: set[str] = set()
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        cve_id = stripped.split("#", 1)[0].strip()
        if cve_id:
            file_ids.add(cve_id)

    loaded = _load_allowlist()

    assert loaded == frozenset(file_ids), (
        f"Loaded allowlist ({len(loaded)}) doesn't match file content "
        f"({len(file_ids)}). Возможен D-AUDIT-10301 регресс — loader "
        f"использует hardcoded fallback вместо файла."
    )
    # Active count = 5 после Dependabot 2026-10-15 (см. allowlist.txt comments):
    # 1 diskcache (PYSEC-2026-2447) + 4 chromadb (PYSEC-2026-311/3813/3814/3815).
    # Каждая запись имеет documented mitigation + Rev. date 2026-12-15.
    # Если кто-то добавит новую allowlist-запись, она должна появиться
    # в обоих местах: и в файле (как не-комментарная строка), и в loaded.
    # Тест ловит рассинхронизацию между file content и hardcoded expected.
    EXPECTED_ACTIVE_COUNT = 5
    assert len(loaded) == EXPECTED_ACTIVE_COUNT, (
        f"Expected {EXPECTED_ACTIVE_COUNT} active allowlist entries "
        f"(Dependabot 2026-10-15 — diskcache + chromadb no-fix CVEs), "
        f"but loader returned {len(loaded)}. Если это намеренное "
        f"пополнение allowlist — обновите EXPECTED_ACTIVE_COUNT И "
        f"зафиксируйте в git log (см. S58/ADR-0290 как reference)."
    )


def test_load_allowlist_contains_cve_ids() -> None:
    """Loaded allowlist должен содержать CVE ID (CVE-..., GHSA-..., PYSEC-...)."""
    ids = _load_allowlist()
    cve_count = sum(1 for cve_id in ids if cve_id.startswith("CVE-"))
    ghsa_count = sum(1 for cve_id in ids if cve_id.startswith("GHSA-"))
    pysec_count = sum(1 for cve_id in ids if cve_id.startswith("PYSEC-"))
    total = cve_count + ghsa_count + pysec_count
    assert total == len(ids), (
        f"Loaded {len(ids)} IDs but {cve_count}+{ghsa_count}+{pysec_count}={total} "
        f"match CVE/GHSA/PYSEC pattern. Check allowlist format."
    )


def test_load_allowlist_ignores_comments() -> None:
    """Строки начинающиеся с '#' должны игнорироваться."""
    tmp = Path(".security/test-allowlist.tmp")
    try:
        tmp.write_text(
            "# Header comment\n"
            "CVE-2024-0001\n"
            "  # Indented comment\n"
            "CVE-2024-0002  # inline comment\n"
            "\n"
            "CVE-2024-0003\n"
        )
        import tools.pip_audit_gate as gate_mod

        original = gate_mod._CANONICAL_ALLOWLIST
        gate_mod._CANONICAL_ALLOWLIST = tmp
        try:
            ids = gate_mod._load_allowlist()
        finally:
            gate_mod._CANONICAL_ALLOWLIST = original
        assert ids == frozenset({"CVE-2024-0001", "CVE-2024-0002", "CVE-2024-0003"})
    finally:
        if tmp.exists():
            tmp.unlink()


def test_legacy_fallback_when_allowlist_missing() -> None:
    """Если файл отсутствует, gate использует hardcoded IGNORED_VULNS."""
    import tools.pip_audit_gate as gate_mod

    original = gate_mod._CANONICAL_ALLOWLIST
    gate_mod._CANONICAL_ALLOWLIST = Path(".security/does-not-exist.txt")
    try:
        ids = gate_mod._load_allowlist()
    finally:
        gate_mod._CANONICAL_ALLOWLIST = original
    # Hardcoded fallback is empty frozenset
    assert ids == IGNORED_VULNS
